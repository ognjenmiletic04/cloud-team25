import html
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3
import pandas as pd
import awswrangler as wr
from botocore.exceptions import ClientError


HN_TYPES = ["story", "comment", "ask", "job", "poll"]

s3_client = boto3.client("s3")


def lambda_handler(event, context):
    bronze_bucket = os.environ["BRONZE_BUCKET_NAME"]
    silver_bucket = os.environ["SILVER_BUCKET_NAME"]
    bronze_hn_prefix = os.environ.get("BRONZE_HN_PREFIX", "bronze/hacker-news")
    bronze_x_prefix = os.environ.get("BRONZE_X_PREFIX", "bronze/x")
    silver_prefix = os.environ.get("SILVER_PREFIX", "silver")

    target_date = _get_target_date(event)
    sources = set((event or {}).get("sources", ["hacker-news", "x"]))

    users: list[dict[str, Any]] = []
    posts: list[dict[str, Any]] = []
    source_summary: dict[str, Any] = {}

    if "hacker-news" in sources:
        hn_users, hn_posts, hn_summary = _load_and_normalize_hacker_news(
            bronze_bucket,
            bronze_hn_prefix,
            target_date,
        )
        users.extend(hn_users)
        posts.extend(hn_posts)
        source_summary["hacker-news"] = hn_summary

    if "x" in sources:
        x_users, x_posts, x_summary = _load_and_normalize_x(
            bronze_bucket,
            bronze_x_prefix,
            target_date,
        )
        users.extend(x_users)
        posts.extend(x_posts)
        source_summary["x"] = x_summary

    users_df = _build_users_dataframe(users)
    posts_df = _build_posts_dataframe(posts, target_date)

    users_path = f"s3://{silver_bucket}/{silver_prefix}/users/"
    posts_path = f"s3://{silver_bucket}/{silver_prefix}/posts/"
    quality_path = f"s3://{silver_bucket}/{silver_prefix}/_quality/"

    users_written = _write_users_table(users_df, users_path)
    posts_written = _write_posts_table(posts_df, posts_path)
    quality_summary = _write_quality_summary(
        users_df,
        posts_df,
        quality_path,
        target_date,
        source_summary,
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Silver normalization completed",
                "target_date": target_date.isoformat(),
                "users_written": users_written,
                "posts_written": posts_written,
                "source_summary": source_summary,
                "data_quality": quality_summary,
            },
            ensure_ascii=False,
            default=str,
        ),
    }


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------


def _get_target_date(event: dict[str, Any] | None) -> date:
    if isinstance(event, dict) and event.get("target_date"):
        return datetime.strptime(event["target_date"], "%Y-%m-%d").date()
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _load_and_normalize_hacker_news(
    bucket_name: str,
    bronze_prefix: str,
    target_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    users: list[dict[str, Any]] = []
    posts: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    for hn_type in HN_TYPES:
        key = (
            f"{bronze_prefix}/"
            f"year={target_date.year}/"
            f"month={target_date.month:02d}/"
            f"day={target_date.day:02d}/"
            f"type={hn_type}/data.json"
        )
        raw_items = _read_json_array_from_s3(bucket_name, key)
        summary[hn_type] = {"bronze_key": key, "raw_count": len(raw_items)}

        for item in raw_items:
            user = _normalize_hn_user(item)
            if user:
                users.append(user)
            post = _normalize_hn_post(item, hn_type)
            if post:
                posts.append(post)

    return users, posts, summary


def _load_and_normalize_x(
    bucket_name: str,
    bronze_prefix: str,
    target_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    key = (
        f"{bronze_prefix}/"
        f"year={target_date.year}/"
        f"month={target_date.month:02d}/"
        f"day={target_date.day:02d}/data.json"
    )
    raw_rows = _read_json_array_from_s3(bucket_name, key)

    users: list[dict[str, Any]] = []
    posts: list[dict[str, Any]] = []

    for index, row in enumerate(raw_rows):
        user = _normalize_x_user(row)
        if user:
            users.append(user)
        post = _normalize_x_post(row, index)
        if post:
            posts.append(post)

    return users, posts, {"bronze_key": key, "raw_count": len(raw_rows)}


def _read_json_array_from_s3(bucket_name: str, key: str) -> list[dict[str, Any]]:
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return []
        raise

    raw = response["Body"].read().decode("utf-8")
    if not raw.strip():
        return []

    data = json.loads(raw)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


# ---------------------------------------------------------------------------
# Hacker News normalization
# ---------------------------------------------------------------------------


def _normalize_hn_user(item: dict[str, Any]) -> dict[str, Any] | None:
    username = _clean_string(item.get("author") or item.get("by"))
    if not username:
        return None

    return {
        "user_id": _stable_uuid("hacker_news", username),
        "platform": "hacker_news",
        "username": username,
        "display_name": username,
        "created_at": None,
        "karma_score": _to_int(item.get("karma")),
        "is_verified": None,
        "followers_count": None,
        "last_seen_at": _normalize_datetime(item.get("created_at_i") or item.get("created_at")),
    }


def _normalize_hn_post(item: dict[str, Any], hn_type: str) -> dict[str, Any] | None:
    post_id = _clean_string(item.get("objectID") or item.get("id"))
    if not post_id:
        return None

    author_username = _clean_string(item.get("author") or item.get("by"))
    created_at = _normalize_datetime(item.get("created_at_i") or item.get("created_at"))
    title = _clean_text(item.get("title") or item.get("story_title"))
    content = _first_non_empty(
        _clean_text(item.get("story_text")),
        _clean_text(item.get("comment_text")),
        title,
    )

    return {
        "post_id": post_id,
        "platform": "hacker_news",
        "author_user_id": _stable_uuid("hacker_news", author_username) if author_username else None,
        "author_username": author_username,
        "post_type": hn_type,
        "title": title,
        "content_text": content,
        "url": _clean_string(item.get("url") or item.get("story_url")),
        "created_at": created_at,
        "score": _to_int(item.get("points") or item.get("score")),
        "num_comments": _to_int(item.get("num_comments")),
        "parent_post_id": _clean_string(item.get("parent_id") or item.get("parent")),
        "source_tags": _json_to_string(item.get("_tags") or item.get("tags")),
        "child_post_ids": _json_to_string(item.get("kids") or item.get("children")),
    }


# ---------------------------------------------------------------------------
# X normalization
# ---------------------------------------------------------------------------


def _normalize_x_user(row: dict[str, Any]) -> dict[str, Any] | None:
    username = _clean_string(
        row.get("user_name")
        or row.get("username")
        or row.get("user_screen_name")
        or row.get("screen_name")
    )
    if not username:
        return None

    return {
        "user_id": _stable_uuid("x", username),
        "platform": "x",
        "username": username,
        "display_name": _clean_string(row.get("user_name") or username),
        "created_at": _normalize_datetime(row.get("user_created") or row.get("created_at")),
        "karma_score": None,
        "is_verified": _to_bool(row.get("user_verified") or row.get("verified")),
        "followers_count": _to_int(row.get("user_followers") or row.get("followers_count")),
        "last_seen_at": _normalize_datetime(row.get("date")),
    }


def _normalize_x_post(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    text = _clean_text(row.get("text") or row.get("tweet") or row.get("content"))
    if not text:
        return None

    created_at = _normalize_datetime(row.get("date") or row.get("created_at"))
    username = _clean_string(
        row.get("user_name")
        or row.get("username")
        or row.get("user_screen_name")
        or row.get("screen_name")
    )
    raw_id = _clean_string(row.get("tweet_id") or row.get("id") or row.get("id_str"))
    post_id = raw_id or _stable_uuid("x-post", f"{username}|{created_at}|{text[:80]}|{index}")
    is_retweet = _to_bool(row.get("is_retweet"))

    return {
        "post_id": post_id,
        "platform": "x",
        "author_user_id": _stable_uuid("x", username) if username else None,
        "author_username": username,
        "post_type": "retweet" if is_retweet else "tweet",
        "title": None,
        "content_text": text,
        "url": None,
        "created_at": created_at,
        "score": None,
        "num_comments": None,
        "parent_post_id": None,
        "source_tags": _json_to_string(row.get("hashtags")),
        "child_post_ids": None,
    }


# ---------------------------------------------------------------------------
# DataFrame construction and writes
# ---------------------------------------------------------------------------


def _build_users_dataframe(users: list[dict[str, Any]]) -> pd.DataFrame:
    columns = [
        "user_id",
        "platform",
        "username",
        "display_name",
        "created_at",
        "karma_score",
        "is_verified",
        "followers_count",
        "last_seen_at",
    ]
    df = pd.DataFrame(users, columns=columns)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=["user_id"], keep="last")
    return df.astype(
        {
            "user_id": "string",
            "platform": "string",
            "username": "string",
            "display_name": "string",
            "created_at": "string",
            "karma_score": "Int64",
            "is_verified": "boolean",
            "followers_count": "Int64",
            "last_seen_at": "string",
        }
    )


def _build_posts_dataframe(posts: list[dict[str, Any]], target_date: date) -> pd.DataFrame:
    columns = [
        "post_id",
        "platform",
        "author_user_id",
        "author_username",
        "post_type",
        "title",
        "content_text",
        "url",
        "created_at",
        "score",
        "num_comments",
        "parent_post_id",
        "source_tags",
        "child_post_ids",
    ]
    df = pd.DataFrame(posts, columns=columns)
    if df.empty:
        return df

    df = df.drop_duplicates(subset=["platform", "post_id"], keep="last")
    df["created_date"] = df["created_at"].str.slice(0, 10)
    df["year"] = target_date.year
    df["month"] = f"{target_date.month:02d}"
    df["day"] = f"{target_date.day:02d}"

    return df.astype(
        {
            "post_id": "string",
            "platform": "string",
            "author_user_id": "string",
            "author_username": "string",
            "post_type": "string",
            "title": "string",
            "content_text": "string",
            "url": "string",
            "created_at": "string",
            "score": "Int64",
            "num_comments": "Int64",
            "parent_post_id": "string",
            "source_tags": "string",
            "child_post_ids": "string",
            "created_date": "string",
            "year": "int64",
            "month": "string",
            "day": "string",
        }
    )


def _write_users_table(users_df: pd.DataFrame, users_path: str) -> int:
    if users_df.empty:
        return 0

    # Users is a dimension table. We merge existing silver users with the newly
    # observed users and overwrite the whole users dataset to avoid duplicates.
    existing_users = _read_existing_parquet_dataset(users_path)
    if existing_users is not None and not existing_users.empty:
        merged = pd.concat([existing_users, users_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["user_id"], keep="last")
    else:
        merged = users_df

    try:
        wr.s3.delete_objects(users_path)
    except Exception:
        # It is fine if the table does not exist yet.
        pass

    wr.s3.to_parquet(
        df=merged,
        path=users_path,
        dataset=True,
        mode="overwrite",
        partition_cols=["platform"],
        index=False,
    )
    return int(len(merged))


def _write_posts_table(posts_df: pd.DataFrame, posts_path: str) -> int:
    if posts_df.empty:
        return 0

    wr.s3.to_parquet(
        df=posts_df,
        path=posts_path,
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["platform", "year", "month", "day"],
        index=False,
    )
    return int(len(posts_df))


def _write_quality_summary(
    users_df: pd.DataFrame,
    posts_df: pd.DataFrame,
    quality_path: str,
    target_date: date,
    source_summary: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        _quality_row("users", users_df, target_date),
        _quality_row("posts", posts_df, target_date),
    ]
    df = pd.DataFrame(rows)
    if not df.empty:
        wr.s3.to_parquet(
            df=df,
            path=quality_path,
            dataset=True,
            mode="overwrite_partitions",
            partition_cols=["year", "month", "day"],
            index=False,
        )

    # Also leave a tiny JSON run report for easy manual inspection in S3.
    silver_bucket_name = os.environ["SILVER_BUCKET_NAME"]
    quality_prefix = quality_path.replace(f"s3://{silver_bucket_name}/", "")

    if quality_prefix and not quality_prefix.endswith("/"):
        quality_prefix += "/"

    report_key = (
        f"{quality_prefix}"
        f"run_reports/year={target_date.year}/month={target_date.month:02d}/day={target_date.day:02d}/report.json"
    )

    s3_client.put_object(
        Bucket=silver_bucket_name,
        Key=report_key,
        Body=json.dumps(
            {"tables": rows, "sources": source_summary},
            ensure_ascii=False,
            default=str,
        ).encode("utf-8"),
        ContentType="application/json",
    )
    return {row["table_name"]: row for row in rows}


def _read_existing_parquet_dataset(path: str) -> pd.DataFrame | None:
    try:
        return wr.s3.read_parquet(path=path, dataset=True)
    except Exception:
        return None


def _quality_row(table_name: str, df: pd.DataFrame, target_date: date) -> dict[str, Any]:
    if df.empty or len(df.columns) == 0:
        quality_score = 0.0
        non_null_cells = 0
        total_cells = 0
    else:
        total_cells = int(df.shape[0] * df.shape[1])
        non_null_cells = int(df.notna().sum().sum())
        quality_score = round((non_null_cells / total_cells) * 100, 2) if total_cells else 0.0

    return {
        "table_name": table_name,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "non_null_cells": non_null_cells,
        "total_cells": total_cells,
        "data_quality_score": quality_score,
        "year": target_date.year,
        "month": f"{target_date.month:02d}",
        "day": f"{target_date.day:02d}",
    }


# ---------------------------------------------------------------------------
# Generic normalization helpers
# ---------------------------------------------------------------------------


def _stable_uuid(namespace: str, value: str | None) -> str:
    normalized = (value or "").strip().lower()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"social-media/{namespace}/{normalized}"))


def _normalize_datetime(value: Any) -> str | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    value_str = str(value).strip()
    if not value_str:
        return None

    if value_str.isdigit():
        return datetime.fromtimestamp(int(value_str), tz=timezone.utc).isoformat().replace("+00:00", "Z")

    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a %b %d %H:%M:%S %z %Y",
    ):
        try:
            parsed = datetime.strptime(value_str, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            continue

    try:
        parsed = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _clean_text(value: Any) -> str | None:
    value = _clean_string(value)
    if value is None:
        return None
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if value == "" or value.lower() in {"none", "null", "nan"}:
        return None
    return value


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    value_str = str(value).strip().lower()
    if value_str in {"true", "1", "yes", "y"}:
        return True
    if value_str in {"false", "0", "no", "n"}:
        return False
    return None


def _json_to_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return _clean_string(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value:
            return value
    return None

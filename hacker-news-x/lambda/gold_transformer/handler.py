import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import awswrangler as wr


HN_CONTENT_TYPES = ["story", "ask", "comment", "job", "poll"]
TOP_N = 10


def lambda_handler(event, context):
    silver_bucket = os.environ["SILVER_BUCKET_NAME"]
    gold_bucket = os.environ["GOLD_BUCKET_NAME"]
    silver_prefix = os.environ.get("SILVER_PREFIX", "silver")
    gold_prefix = os.environ.get("GOLD_PREFIX", "gold")

    target_date = _get_target_date(event)

    users_path = f"s3://{silver_bucket}/{silver_prefix}/users/"
    posts_path = f"s3://{silver_bucket}/{silver_prefix}/posts/"

    users_df = _read_users(users_path)
    hn_posts_df = _read_posts_for_date(posts_path, "hacker_news", target_date)
    x_posts_df = _read_posts_for_date(posts_path, "x", target_date)

    tables_written: dict[str, int] = {}

    tables_written["daily_content_metrics"] = _write_daily_content_metrics(
        hn_posts_df, target_date, gold_bucket, gold_prefix
    )
    tables_written["daily_users_metric"] = _write_daily_users_metric(
        users_df, hn_posts_df, x_posts_df, target_date, gold_bucket, gold_prefix
    )
    tables_written["top_x_users_by_followers"] = _write_top_x_users_by_followers(
        users_df, target_date, gold_bucket, gold_prefix
    )
    tables_written["top_hn_users_by_karma"] = _write_hn_users_by_karma(
        users_df, target_date, gold_bucket, gold_prefix,
        ascending=False, table_name="top_hn_users_by_karma",
    )
    tables_written["bottom_hn_users_by_karma"] = _write_hn_users_by_karma(
        users_df, target_date, gold_bucket, gold_prefix,
        ascending=True, table_name="bottom_hn_users_by_karma",
    )
    tables_written["top_hn_jobs_by_score"] = _write_hn_posts_by_score(
        hn_posts_df, target_date, gold_bucket, gold_prefix,
        post_type="job", table_name="top_hn_jobs_by_score",
    )
    tables_written["top_hn_posts_by_score"] = _write_hn_posts_by_score(
        hn_posts_df, target_date, gold_bucket, gold_prefix,
        post_type="story", table_name="top_hn_posts_by_score",
    )
    tables_written["data_quality_metric"] = _write_data_quality_metric(
        users_df, hn_posts_df, x_posts_df, target_date, gold_bucket, gold_prefix
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Gold transformation completed",
                "target_date": target_date.isoformat(),
                "tables_written": tables_written,
            },
            ensure_ascii=False,
            default=str,
        ),
    }


# ---------------------------------------------------------------------------
# Date / read helpers
# ---------------------------------------------------------------------------


def _get_target_date(event: dict[str, Any] | None) -> date:
    if isinstance(event, dict) and event.get("target_date"):
        return datetime.strptime(event["target_date"], "%Y-%m-%d").date()
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _read_users(users_path: str) -> pd.DataFrame:
    try:
        df = wr.s3.read_parquet(path=users_path, dataset=True)
        return df if not df.empty else _empty_users_df()
    except Exception:
        return _empty_users_df()


def _empty_users_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "user_id", "platform", "username", "display_name", "created_at",
            "karma_score", "is_verified", "followers_count", "last_seen_at",
        ]
    )


def _read_posts_for_date(posts_path: str, platform: str, target_date: date) -> pd.DataFrame:
    year, month, day = str(target_date.year), f"{target_date.month:02d}", f"{target_date.day:02d}"
    try:
        df = wr.s3.read_parquet(
            path=posts_path,
            dataset=True,
            partition_filter=lambda part: (
                part.get("platform") == platform
                and part.get("year") == year
                and part.get("month") == month
                and part.get("day") == day
            ),
        )
        return df if not df.empty else _empty_posts_df()
    except Exception:
        return _empty_posts_df()


def _empty_posts_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "post_id", "platform", "author_user_id", "author_username", "post_type",
            "title", "content_text", "url", "created_at", "score", "num_comments",
            "parent_post_id", "source_tags", "child_post_ids", "created_date",
            "year", "month", "day",
        ]
    )


def _gold_path(gold_bucket: str, gold_prefix: str, table_name: str) -> str:
    return f"s3://{gold_bucket}/{gold_prefix}/{table_name}/"


def _date_partition_cols(target_date: date) -> dict[str, Any]:
    return {
        "year": target_date.year,
        "month": f"{target_date.month:02d}",
        "day": f"{target_date.day:02d}",
    }


# ---------------------------------------------------------------------------
# Metric 1: daily content counts on Hacker News (story/ask/comment/job/poll)
# ---------------------------------------------------------------------------


def _write_daily_content_metrics(
    hn_posts_df: pd.DataFrame, target_date: date, gold_bucket: str, gold_prefix: str
) -> int:
    if hn_posts_df.empty:
        counts: dict[str, int] = {t: 0 for t in HN_CONTENT_TYPES}
    else:
        counts = hn_posts_df["post_type"].value_counts().to_dict()

    parts = _date_partition_cols(target_date)
    rows = [
        {
            "date": target_date.isoformat(),
            "platform": "hacker_news",
            "post_type": post_type,
            "post_count": int(counts.get(post_type, 0)),
            **parts,
        }
        for post_type in HN_CONTENT_TYPES
    ]
    df = pd.DataFrame(rows)
    wr.s3.to_parquet(
        df=df,
        path=_gold_path(gold_bucket, gold_prefix, "daily_content_metrics"),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["platform", "year", "month", "day"],
        index=False,
    )
    return int(len(df))


# ---------------------------------------------------------------------------
# Metric 2 & 3: daily user counts per platform (total + new)
#
# ---------------------------------------------------------------------------


def _known_users_state_path(gold_bucket: str, gold_prefix: str) -> str:
    return f"s3://{gold_bucket}/{gold_prefix}/_state/known_users/"


def _read_known_users(gold_bucket: str, gold_prefix: str) -> pd.DataFrame:
    try:
        df = wr.s3.read_parquet(path=_known_users_state_path(gold_bucket, gold_prefix), dataset=True)
        return df if not df.empty else _empty_known_users_df()
    except Exception:
        return _empty_known_users_df()


def _empty_known_users_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["user_id", "platform", "first_seen_date"])


def _active_user_ids(posts_df: pd.DataFrame, users_df: pd.DataFrame, platform: str) -> set:
    if not posts_df.empty and "author_user_id" in posts_df.columns:
        active_ids = set(posts_df["author_user_id"].dropna().unique())
    else:
        active_ids = set()

    if not active_ids and not users_df.empty:
        active_ids = set(users_df.loc[users_df["platform"] == platform, "user_id"].dropna().unique())

    return active_ids


def _write_daily_users_metric(
    users_df: pd.DataFrame,
    hn_posts_df: pd.DataFrame,
    x_posts_df: pd.DataFrame,
    target_date: date,
    gold_bucket: str,
    gold_prefix: str,
) -> int:
    known_users = _read_known_users(gold_bucket, gold_prefix)
    parts = _date_partition_cols(target_date)

    metric_rows = []
    new_state_rows = []

    for platform, posts_df in (("hacker_news", hn_posts_df), ("x", x_posts_df)):
        active_ids = _active_user_ids(posts_df, users_df, platform)
        existing_ids = (
            set(known_users.loc[known_users["platform"] == platform, "user_id"])
            if not known_users.empty
            else set()
        )

        new_ids = active_ids - existing_ids
        cumulative_total = len(existing_ids | active_ids)

        metric_rows.append(
            {
                "date": target_date.isoformat(),
                "platform": platform,
                "total_users": int(cumulative_total),
                "new_users": int(len(new_ids)),
                **parts,
            }
        )

        new_state_rows.extend(
            {"user_id": uid, "platform": platform, "first_seen_date": target_date.isoformat()}
            for uid in new_ids
        )

    metrics_df = pd.DataFrame(metric_rows)
    wr.s3.to_parquet(
        df=metrics_df,
        path=_gold_path(gold_bucket, gold_prefix, "daily_users_metric"),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["platform", "year", "month", "day"],
        index=False,
    )

    if new_state_rows:
        updated_state = pd.concat([known_users, pd.DataFrame(new_state_rows)], ignore_index=True)
        updated_state = updated_state.drop_duplicates(subset=["user_id", "platform"], keep="first")
        wr.s3.to_parquet(
            df=updated_state,
            path=_known_users_state_path(gold_bucket, gold_prefix),
            dataset=True,
            mode="overwrite",
            partition_cols=["platform"],
            index=False,
        )

    return int(len(metrics_df))


# ---------------------------------------------------------------------------
# Metric 4: top 10 X users by followers
# ---------------------------------------------------------------------------


def _write_top_x_users_by_followers(
    users_df: pd.DataFrame, target_date: date, gold_bucket: str, gold_prefix: str
) -> int:
    x_users = users_df[users_df["platform"] == "x"].copy()
    x_users = x_users[x_users["followers_count"].notna()]
    ranked = x_users.sort_values("followers_count", ascending=False).head(TOP_N)

    parts = _date_partition_cols(target_date)
    df = pd.DataFrame(
        {
            "date": target_date.isoformat(),
            "rank": range(1, len(ranked) + 1),
            "user_id": ranked["user_id"].values,
            "username": ranked["username"].values,
            "followers_count": ranked["followers_count"].astype("Int64").values,
            **parts,
        }
    )
    wr.s3.to_parquet(
        df=df,
        path=_gold_path(gold_bucket, gold_prefix, "top_x_users_by_followers"),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["year", "month", "day"],
        index=False,
    )
    return int(len(df))


# ---------------------------------------------------------------------------
# Metric 5 & 6: top / bottom 10 HN users by karma
# ---------------------------------------------------------------------------


def _write_hn_users_by_karma(
    users_df: pd.DataFrame,
    target_date: date,
    gold_bucket: str,
    gold_prefix: str,
    ascending: bool,
    table_name: str,
) -> int:
    hn_users = users_df[users_df["platform"] == "hacker_news"].copy()
    hn_users = hn_users[hn_users["karma_score"].notna()]
    ranked = hn_users.sort_values("karma_score", ascending=ascending).head(TOP_N)

    parts = _date_partition_cols(target_date)
    df = pd.DataFrame(
        {
            "date": target_date.isoformat(),
            "rank": range(1, len(ranked) + 1),
            "user_id": ranked["user_id"].values,
            "username": ranked["username"].values,
            "karma_score": ranked["karma_score"].astype("Int64").values,
            **parts,
        }
    )
    wr.s3.to_parquet(
        df=df,
        path=_gold_path(gold_bucket, gold_prefix, table_name),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["year", "month", "day"],
        index=False,
    )
    return int(len(df))


# ---------------------------------------------------------------------------
# Metric 7 & 8: top 10 HN job postings / top 10 HN posts (stories) by score
# ---------------------------------------------------------------------------


def _write_hn_posts_by_score(
    hn_posts_df: pd.DataFrame,
    target_date: date,
    gold_bucket: str,
    gold_prefix: str,
    post_type: str,
    table_name: str,
) -> int:
    if hn_posts_df.empty:
        subset = hn_posts_df
    else:
        subset = hn_posts_df[hn_posts_df["post_type"] == post_type].copy()
        subset = subset[subset["score"].notna()]

    ranked = subset.sort_values("score", ascending=False).head(TOP_N) if not subset.empty else subset

    parts = _date_partition_cols(target_date)
    df = pd.DataFrame(
        {
            "date": target_date.isoformat(),
            "rank": range(1, len(ranked) + 1),
            "post_id": ranked["post_id"].values,
            "author_username": ranked["author_username"].values,
            "title": ranked["title"].values,
            "score": ranked["score"].astype("Int64").values,
            "url": ranked["url"].values,
            **parts,
        }
    )
    wr.s3.to_parquet(
        df=df,
        path=_gold_path(gold_bucket, gold_prefix, table_name),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["year", "month", "day"],
        index=False,
    )
    return int(len(df))


# ---------------------------------------------------------------------------
# KPI: Data Quality Score
#
# ---------------------------------------------------------------------------


def _row_completeness_score(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    complete_rows = int(df.notna().all(axis=1).sum())
    return round((complete_rows / len(df)) * 100, 2)


def _write_data_quality_metric(
    users_df: pd.DataFrame,
    hn_posts_df: pd.DataFrame,
    x_posts_df: pd.DataFrame,
    target_date: date,
    gold_bucket: str,
    gold_prefix: str,
) -> int:
    if hn_posts_df.empty and x_posts_df.empty:
        day_posts_df = _empty_posts_df()
    else:
        day_posts_df = pd.concat([hn_posts_df, x_posts_df], ignore_index=True)

    parts = _date_partition_cols(target_date)
    rows = [
        {
            "date": target_date.isoformat(),
            "table_name": "users",
            "row_count": int(len(users_df)),
            "data_quality_score": _row_completeness_score(users_df),
            **parts,
        },
        {
            "date": target_date.isoformat(),
            "table_name": "posts",
            "row_count": int(len(day_posts_df)),
            "data_quality_score": _row_completeness_score(day_posts_df),
            **parts,
        },
    ]
    df = pd.DataFrame(rows)
    wr.s3.to_parquet(
        df=df,
        path=_gold_path(gold_bucket, gold_prefix, "data_quality_metric"),
        dataset=True,
        mode="overwrite_partitions",
        partition_cols=["table_name", "year", "month", "day"],
        index=False,
    )
    return int(len(df))

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3


HN_SEARCH_API_URL = "https://hn.algolia.com/api/v1/search_by_date"

ITEM_TYPES = ["story", "comment", "ask_hn", "job", "poll"]

S3_TYPE_NAMES = {
    "story": "story",
    "comment": "comment",
    "ask_hn": "ask",
    "job": "job",
    "poll": "poll",
}

s3_client = boto3.client("s3")


def lambda_handler(event, context):
    bucket_name = os.environ["BRONZE_BUCKET_NAME"]
    bronze_prefix = os.environ.get("BRONZE_PREFIX", "bronze/hacker-news")

    target_date = _get_target_date(event)
    start_ts, end_ts = _get_day_timestamp_range(target_date)

    result_summary = {}

    for item_type in ITEM_TYPES:
        raw_items = _fetch_all_items_by_time_windows(item_type, start_ts, end_ts)

        s3_key = (
            f"{bronze_prefix}/"
            f"year={target_date.year}/"
            f"month={target_date.month:02d}/"
            f"day={target_date.day:02d}/"
            f"type={S3_TYPE_NAMES[item_type]}/"
            f"data.json"
        )

        _write_json_to_s3(bucket_name, s3_key, raw_items)

        result_summary[item_type] = {
            "count": len(raw_items),
            "s3_key": s3_key,
        }

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "Hacker News bronze collection completed",
                "target_date": target_date.isoformat(),
                "summary": result_summary,
            },
            ensure_ascii=False,
        ),
    }


def _get_target_date(event):
    if isinstance(event, dict) and event.get("target_date"):
        return datetime.strptime(event["target_date"], "%Y-%m-%d").date()

    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _get_day_timestamp_range(target_date):
    start_dt = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    )
    end_dt = start_dt + timedelta(days=1)

    return int(start_dt.timestamp()), int(end_dt.timestamp())


def _fetch_all_items_by_time_windows(item_type, start_ts, end_ts):
    window_seconds = 60 * 60
    all_items = []
    seen_object_ids = set()

    current_start = start_ts

    while current_start < end_ts:
        current_end = min(current_start + window_seconds, end_ts)

        items = _fetch_all_items(item_type, current_start, current_end)

        for item in items:
            object_id = item.get("objectID")

            if object_id is None:
                all_items.append(item)
                continue

            if object_id not in seen_object_ids:
                seen_object_ids.add(object_id)
                all_items.append(item)

        current_start = current_end
        time.sleep(0.1)

    return all_items


def _fetch_all_items(item_type, start_ts, end_ts):
    page = 0
    hits_per_page = 1000
    all_items = []

    while True:
        url = (
            f"{HN_SEARCH_API_URL}"
            f"?tags={item_type}"
            f"&numericFilters=created_at_i>={start_ts},created_at_i<{end_ts}"
            f"&hitsPerPage={hits_per_page}"
            f"&page={page}"
        )

        response = _http_get_json(url)

        hits = response.get("hits", [])
        all_items.extend(hits)

        total_pages = response.get("nbPages", 0)

        if page + 1 >= total_pages:
            break

        page += 1
        time.sleep(0.1)

    return all_items


def _http_get_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "hacker-news-bronze-collector/1.0"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json_to_s3(bucket_name, s3_key, data):
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
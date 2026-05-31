import csv
import io
import json
import os
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime

import boto3


DATE_COLUMN = "date"

s3_client = boto3.client("s3")


def lambda_handler(event, context):
    bucket_name = os.environ["BRONZE_BUCKET_NAME"]
    bronze_prefix = os.environ.get("BRONZE_PREFIX", "bronze/x")

    rows = _load_dataset(bucket_name)

    date_groups = defaultdict(list)
    skipped = 0
    for row in rows:
        date_str = _extract_date(row.get(DATE_COLUMN, ""))
        if date_str:
            date_groups[date_str].append(row)
        else:
            skipped += 1

    result_summary = {}
    for date_str, date_rows in sorted(date_groups.items()):
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        s3_key = (
            f"{bronze_prefix}/"
            f"year={date_obj.year}/"
            f"month={date_obj.month:02d}/"
            f"day={date_obj.day:02d}/"
            f"data.json"
        )
        _write_json_to_s3(bucket_name, s3_key, date_rows)
        result_summary[date_str] = {
            "count": len(date_rows),
            "s3_key": s3_key,
        }

    total_written = sum(v["count"] for v in result_summary.values())

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "message": "X (Twitter) bronze collection completed",
                "total_rows_written": total_written,
                "total_rows_skipped": skipped,
                "days_processed": len(result_summary),
                "summary": result_summary,
            },
            ensure_ascii=False,
        ),
    }


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def _load_dataset(bucket_name: str) -> list[dict]:
    """
    Load tweet rows from whichever source is configured via environment variables.

    Priority:
      1. DATASET_S3_KEY — CSV (or ZIP) already uploaded to the bronze bucket.
      2. DATASET_URL    — Download CSV (or ZIP) on the fly from a public URL.

    Raises EnvironmentError if neither variable is set.
    """
    dataset_s3_key = os.environ.get("DATASET_S3_KEY", "")
    dataset_url = os.environ.get("DATASET_URL", "")

    if dataset_s3_key:
        return _load_from_s3(bucket_name, dataset_s3_key)
    if dataset_url:
        return _load_from_url(dataset_url)

    raise EnvironmentError(
        "No dataset source configured: set DATASET_S3_KEY or DATASET_URL."
    )


def _load_from_s3(bucket_name: str, s3_key: str) -> list[dict]:
    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    raw_bytes = response["Body"].read()
    return _parse_csv_bytes(raw_bytes)


def _load_from_url(url: str) -> list[dict]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "x-bronze-collector/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw_bytes = response.read()

    if url.lower().endswith(".zip"):
        return _parse_zip_bytes(raw_bytes)
    return _parse_csv_bytes(raw_bytes)


def _parse_zip_bytes(raw_bytes: bytes) -> list[dict]:
    """Extract the first CSV found inside a ZIP archive and parse it."""
    with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_names:
            raise ValueError("No CSV files found inside ZIP archive.")
        with zf.open(csv_names[0]) as csv_file:
            return _parse_csv_bytes(csv_file.read())


def _parse_csv_bytes(raw_bytes: bytes) -> list[dict]:
    """
    Decode CSV bytes and return a list of row dicts.

    Tries UTF-8 first; falls back to latin-1 for datasets that use
    extended Latin characters (common in older Kaggle exports).
    """
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _extract_date(date_value: str) -> str | None:
    """
    Return 'YYYY-MM-DD' from the various date formats found in tweet datasets,
    or None if the value cannot be parsed.

    Formats handled:
      2020-07-24 15:12:16           (covid19_tweets.csv default)
      2020-07-24T15:12:16Z          (ISO-8601 with Z)
      2020-07-24T15:12:16           (ISO-8601 without Z)
      2020-07-24                    (date only)
      Mon Jul 13 20:31:17 +0000 2020  (raw Twitter API format)
    """
    if not date_value:
        return None

    date_value = date_value.strip()

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%a %b %d %H:%M:%S %z %Y",
    ):
        try:
            return datetime.strptime(date_value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Last-resort: accept leading YYYY-MM-DD even with unknown trailing chars.
    if len(date_value) >= 10 and date_value[4] == "-" and date_value[7] == "-":
        return date_value[:10]

    return None


# ---------------------------------------------------------------------------
# S3 output
# ---------------------------------------------------------------------------

def _write_json_to_s3(bucket_name: str, s3_key: str, data: list[dict]) -> None:
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )
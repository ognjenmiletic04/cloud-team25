import boto3
from datetime import datetime, timezone

s3_client = boto3.client("s3")


def lambda_handler(event, context):
    return {"statusCode": 200, "body": "placeholder"}
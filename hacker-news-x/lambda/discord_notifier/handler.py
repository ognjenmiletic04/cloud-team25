import json
import os
import urllib.error
import urllib.request

import boto3

secrets_client = boto3.client("secretsmanager")

DISCORD_TIMEOUT_SECONDS = 10


def lambda_handler(event, context):
    """Triggered by Lambda Destinations (on_failure) when an async-invoked
    function fails. Posts a formatted message to a Discord channel via webhook.
    """
    webhook_url = _get_webhook_url()
    message = _build_message(event)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(message).encode("utf-8"),
        headers=headers,  
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=DISCORD_TIMEOUT_SECONDS) as response:
            return {"statusCode": response.status}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"Discord webhook returned {exc.code}: {body}")
        raise


def _get_webhook_url() -> str:
    secret = secrets_client.get_secret_value(SecretId=os.environ["DISCORD_SECRET_ARN"])
    return json.loads(secret["SecretString"])["webhook_url"]


def _build_message(event: dict) -> dict:
    request_context = event.get("requestContext", {})
    response_payload = event.get("responsePayload", {}) or {}
    request_payload = event.get("requestPayload", {})

    function_arn = request_context.get("functionArn", "unknown function")
    condition = request_context.get("condition", "unknown")
    error_type = response_payload.get("errorType", "Unknown error")
    error_message = response_payload.get("errorMessage", "No message")

    content = (
        f"🔴 **Lambda Failed**\n"
        f"**Function:** `{function_arn}`\n"
        f"**Condition:** `{condition}`\n"
        f"**Error:** `{error_type}: {error_message}`\n"
        f"**Input:** `{json.dumps(request_payload, default=str)[:500]}`"
    )
    return {"content": content}
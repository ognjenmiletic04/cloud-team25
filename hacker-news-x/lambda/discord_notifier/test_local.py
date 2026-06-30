import os

os.environ["DISCORD_SECRET_ARN"] = "discord-webhook-url"

from handler import lambda_handler


fake_failure_event = {
    "version": "1.0",
    "requestContext": {
        "functionArn": "arn:aws:lambda:us-east-1:803992934310:function:GoldStack-GoldTransformerLambda",
        "condition": "RetriesExhausted",
    },
    "requestPayload": {"target_date": "2026-06-29"},
    "responseContext": {"statusCode": 200, "functionError": "Unhandled"},
    "responsePayload": {
        "errorType": "NoSuchBucket",
        "errorMessage": "The specified bucket does not exist",
        "trace": ["..."],
    },
}

result = lambda_handler(fake_failure_event, None)
print(result)
import os
os.environ["BRONZE_BUCKET_NAME"] = "social-media-bronze-cloud-team25"
os.environ["SILVER_BUCKET_NAME"] = "social-media-silver-cloud-team25"

from handler import lambda_handler

result = lambda_handler({"target_date": "2026-06-29"}, None)
print(result)
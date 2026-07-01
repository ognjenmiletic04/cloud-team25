import os
os.environ["SILVER_BUCKET_NAME"] = "social-media-silver-cloud-team25"
os.environ["GOLD_BUCKET_NAME"] = "social-media-gold-cloud-team25"
os.environ["SILVER_PREFIX"] = "silver"
os.environ["GOLD_PREFIX"] = "gold"

from handler import lambda_handler

print("=== HN day (2026-06-29) ===")
result1 = lambda_handler({"target_date": "2026-06-29"}, None)
print(result1)

print("\n=== X day (2020-07-25) ===")
result2 = lambda_handler({"target_date": "2020-07-25"}, None)
print(result2)

print("\n=== TOP 10 HN KORISNIKA ===")
print(top_hn_users_by_karma_df[['username', 'karma']].to_string())

print("\n=== BOTTOM 10 HN KORISNIKA ===")
print(bottom_hn_users_by_karma_df[['username', 'karma']].to_string())
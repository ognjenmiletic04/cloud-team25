#!/usr/bin/env python3
import aws_cdk as cdk

from lib.data_lake_stack import SocialMediaDataLakeStack
from lib.hacker_news_bronze_stack import HackerNewsBronzeStack
from lib.x_bronze_stack import XBronzeStack
from lib.silver_stack import SilverStack
from lib.gold_stack import GoldStack
from lib.discord_notifier_stack import DiscordNotifierStack


app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

data_lake = SocialMediaDataLakeStack(app, "SocialMediaDataLakeStack", env=env)

hacker_news_bronze = HackerNewsBronzeStack(
    app,
    "HackerNewsBronzeStack",
    bronze_bucket=data_lake.bronze_bucket,
    vpc=data_lake.vpc,
    env=env,
)

x_bronze = XBronzeStack(
    app,
    "XBronzeStack",
    bronze_bucket=data_lake.bronze_bucket,
    vpc=data_lake.vpc,
    env=env,
)

silver = SilverStack(
    app,
    "SilverStack",
    bronze_bucket=data_lake.bronze_bucket,
    silver_bucket=data_lake.silver_bucket,
    vpc=data_lake.vpc,
    env=env,
)
discord_notifier = DiscordNotifierStack(app, "DiscordNotifierStack", env=env)
gold = GoldStack(
    app,
    "GoldStack",
    silver_bucket=data_lake.silver_bucket,
    gold_bucket=data_lake.gold_bucket,
    vpc=data_lake.vpc,
    notifier_lambda=discord_notifier.notifier_lambda,   # <-- DODATO
    env=env,
)

hacker_news_bronze.add_dependency(data_lake)
x_bronze.add_dependency(data_lake)
silver.add_dependency(data_lake)
gold.add_dependency(data_lake)
gold.add_dependency(discord_notifier)

app.synth()

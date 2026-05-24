from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
)
from constructs import Construct


class HackerNewsBronzeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bronze_bucket = s3.Bucket(
            self,
            "SocialMediaBronzeBucket",
            bucket_name="social-media-bronze-cloud-team25",
            versioned=False,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        collector_lambda = _lambda.Function(
            self,
            "HackerNewsCollectorLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda/hacker_news_collector"),
            timeout=Duration.minutes(15),
            memory_size=512,
            environment={
                "BRONZE_BUCKET_NAME": bronze_bucket.bucket_name,
                "BRONZE_PREFIX": "bronze/hacker-news",
            },
        )

        bronze_bucket.grant_write(collector_lambda)

        daily_schedule = events.Rule(
            self,
            "DailyHackerNewsCollectionSchedule",
            schedule=events.Schedule.cron(
                minute="0",
                hour="2",
            ),
        )

        daily_schedule.add_target(targets.LambdaFunction(collector_lambda))
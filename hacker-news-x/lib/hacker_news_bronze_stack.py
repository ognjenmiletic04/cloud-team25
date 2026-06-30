from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_lambda as _lambda,
    aws_events as events,
    aws_events_targets as targets,
    CfnOutput,
)
from constructs import Construct


class HackerNewsBronzeStack(Stack):
    """Bronze collector for Hacker News.

    The bronze bucket is no longer created in this stack. It is passed in from
    SocialMediaDataLakeStack so that S3/data-lake infrastructure and Lambda
    compute are separated.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bronze_bucket: s3.IBucket,
        vpc: ec2.IVpc | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        collector_lambda = _lambda.Function(
            self,
            "HackerNewsCollectorLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda/hacker_news_collector"),
            timeout=Duration.minutes(15),
            memory_size=512,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS) if vpc else None,
            environment={
                "BRONZE_BUCKET_NAME": bronze_bucket.bucket_name,
                "BRONZE_PREFIX": "bronze/hacker-news",
            },
        )

        bronze_bucket.grant_write(collector_lambda, "bronze/hacker-news/*")

        daily_schedule = events.Rule(
            self,
            "DailyHackerNewsCollectionSchedule",
            schedule=events.Schedule.cron(minute="0", hour="2"),
        )
        daily_schedule.add_target(targets.LambdaFunction(collector_lambda))

        CfnOutput(
            self,
            "HackerNewsCollectorLambdaArn",
            value=collector_lambda.function_arn,
            description="ARN of the Hacker News bronze collector Lambda",
        )

        self.collector_lambda = collector_lambda

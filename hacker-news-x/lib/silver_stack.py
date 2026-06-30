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


class SilverStack(Stack):
    """Silver normalization stack.

    Reads raw JSON from the bronze bucket and writes normalized Parquet datasets
    to the silver bucket.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        bronze_bucket: s3.IBucket,
        silver_bucket: s3.IBucket,
        vpc: ec2.IVpc | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        normalizer_lambda = _lambda.DockerImageFunction(
            self,
            "SilverNormalizerLambda",
            code=_lambda.DockerImageCode.from_image_asset("lambda/silver_normalizer"),
            timeout=Duration.minutes(15),
            memory_size=2048,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS) if vpc else None,
            environment={
                "BRONZE_BUCKET_NAME": bronze_bucket.bucket_name,
                "SILVER_BUCKET_NAME": silver_bucket.bucket_name,
                "BRONZE_HN_PREFIX": "bronze/hacker-news",
                "BRONZE_X_PREFIX": "bronze/x",
                "SILVER_PREFIX": "silver",
            },
        )

        bronze_bucket.grant_read(normalizer_lambda, "bronze/*")
        silver_bucket.grant_read_write(normalizer_lambda, "silver/*")
        silver_bucket.grant_delete(normalizer_lambda, "silver/*")

        daily_schedule = events.Rule(
            self,
            "DailySilverNormalizationSchedule",
            schedule=events.Schedule.cron(minute="0", hour="3"),
        )
        daily_schedule.add_target(
            targets.LambdaFunction(
                normalizer_lambda,
                event=events.RuleTargetInput.from_object(
                    {
                        "sources": ["hacker-news", "x"],
                        "mode": "overwrite_partitions",
                    }
                ),
            )
        )

        CfnOutput(
            self,
            "SilverNormalizerLambdaArn",
            value=normalizer_lambda.function_arn,
            description="ARN of the Silver normalization Lambda",
        )

        self.normalizer_lambda = normalizer_lambda

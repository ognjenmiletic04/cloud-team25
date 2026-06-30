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


class GoldStack(Stack):
    """
    Gold transformation stack.

    Reads normalized parquet datasets from the silver bucket,
    calculates metrics/KPIs and writes them into the gold bucket.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        silver_bucket: s3.IBucket,
        gold_bucket: s3.IBucket,
        vpc: ec2.IVpc | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        gold_lambda = _lambda.DockerImageFunction(
            self,
            "GoldTransformerLambda",
            code=_lambda.DockerImageCode.from_image_asset(
                "lambda/gold_transformer"
            ),
            timeout=Duration.minutes(15),
            memory_size=2048,
            vpc=vpc,
            vpc_subnets=(
                ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                )
                if vpc
                else None
            ),
            environment={
                "SILVER_BUCKET_NAME": silver_bucket.bucket_name,
                "GOLD_BUCKET_NAME": gold_bucket.bucket_name,
                "SILVER_PREFIX": "silver",
                "GOLD_PREFIX": "gold",
            },
        )

        silver_bucket.grant_read(gold_lambda, "silver/*")

        gold_bucket.grant_read_write(
            gold_lambda,
            "gold/*",
        )

        gold_bucket.grant_delete(
            gold_lambda,
            "gold/*",
        )

        daily_schedule = events.Rule(
            self,
            "DailyGoldTransformationSchedule",
            schedule=events.Schedule.cron(
                minute="30",
                hour="3",
            ),
        )

        daily_schedule.add_target(
            targets.LambdaFunction(
                gold_lambda,
                event=events.RuleTargetInput.from_object(
                    {
                        "mode": "overwrite_partitions",
                    }
                ),
            )
        )

        CfnOutput(
            self,
            "GoldTransformerLambdaArn",
            value=gold_lambda.function_arn,
            description="ARN of the Gold transformation Lambda",
        )

        self.gold_lambda = gold_lambda
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


class XBronzeStack(Stack):
    DATASET_S3_KEY = "bronze/x/dataset/covid19_tweets.csv"

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
            "XCollectorLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset("lambda/x_collector"),
            timeout=Duration.minutes(5),
            memory_size=2048,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS) if vpc else None,
            environment={
                "BRONZE_BUCKET_NAME": bronze_bucket.bucket_name,
                "BRONZE_PREFIX": "bronze/x",
                "DATASET_S3_KEY": self.DATASET_S3_KEY,
                "DATASET_URL": "",
            },
        )

        bronze_bucket.grant_read(collector_lambda, self.DATASET_S3_KEY)
        bronze_bucket.grant_write(collector_lambda, "bronze/x/*")

        daily_schedule = events.Rule(
            self,
            "DailyXCollectionSchedule",
            schedule=events.Schedule.cron(minute="15", hour="2"),
            enabled=False,
        )
        daily_schedule.add_target(targets.LambdaFunction(collector_lambda))

        CfnOutput(
            self,
            "XCollectorLambdaArn",
            value=collector_lambda.function_arn,
            description="ARN of the X (Twitter) bronze collector Lambda",
        )
        CfnOutput(
            self,
            "DatasetS3Key",
            value=self.DATASET_S3_KEY,
            description=(
                "Upload the COVID-19 tweets CSV to this S3 key before invoking the Lambda: "
                f"s3://{bronze_bucket.bucket_name}/{self.DATASET_S3_KEY}"
            ),
        )

        self.collector_lambda = collector_lambda

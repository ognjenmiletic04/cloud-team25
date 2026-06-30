from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
)
from constructs import Construct


class DiscordNotifierStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        discord_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "DiscordWebhookSecret", "discord-webhook-url"
        )

        self.notifier_lambda = _lambda.Function(
            self,
            "DiscordNotifierLambda",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="handler.lambda_handler",
            code=_lambda.Code.from_asset(
                "lambda/discord_notifier",
                exclude=[".venv", "venv", "__pycache__", "*.pyc", ".git"],
            ),
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "DISCORD_SECRET_ARN": discord_secret.secret_arn,
            },
        )
        discord_secret.grant_read(self.notifier_lambda)

        CfnOutput(
            self,
            "DiscordNotifierLambdaArn",
            value=self.notifier_lambda.function_arn,
            description="ARN of the Discord notifier Lambda",
        )
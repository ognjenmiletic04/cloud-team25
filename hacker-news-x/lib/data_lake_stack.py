from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_s3 as s3,
    CfnOutput,
)
from constructs import Construct


class SocialMediaDataLakeStack(Stack):
    """
    Shared infrastructure for the medalion architecture.

    Buckets are intentionally separated by responsibility:
      - bronze bucket: raw source data, no transformations
      - silver bucket: normalized parquet tables
      - artifacts bucket: optional project artifacts / uploaded datasets

    CDK still uses its bootstrap bucket/ECR repository for synthesized Lambda assets.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "SocialMediaVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private-egress",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.vpc.add_gateway_endpoint(
            "S3GatewayEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        self.bronze_bucket = s3.Bucket.from_bucket_name(
            self,
            "ImportedSocialMediaBronzeBucket",
            "social-media-bronze-cloud-team25",
        )

        self.silver_bucket = self._create_data_bucket(
            "SocialMediaSilverBucket",
            "social-media-silver-cloud-team25",
        )

        self.artifacts_bucket = self._create_data_bucket(
            "SocialMediaArtifactsBucket",
            "social-media-artifacts-cloud-team25",
        )

        CfnOutput(self, "BronzeBucketName", value=self.bronze_bucket.bucket_name)
        CfnOutput(self, "SilverBucketName", value=self.silver_bucket.bucket_name)
        CfnOutput(self, "ArtifactsBucketName", value=self.artifacts_bucket.bucket_name)
        CfnOutput(self, "VpcId", value=self.vpc.vpc_id)

    def _create_data_bucket(self, construct_id: str, bucket_name: str) -> s3.Bucket:
        return s3.Bucket(
            self,
            construct_id,
            bucket_name=bucket_name,
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

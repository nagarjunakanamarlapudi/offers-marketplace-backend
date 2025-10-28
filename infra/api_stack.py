from __future__ import annotations

from pathlib import Path
from typing import Sequence

import aws_cdk as cdk
from aws_cdk import (
    BundlingOptions,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as integrations,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
)


class ApiStack(Stack):
    def __init__(
        self,
        scope: cdk.App,
        construct_id: str,
        *,
        allowed_origins: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project_root = Path(__file__).resolve().parent.parent
        backend_path = project_root / "backend"
        if not backend_path.exists():
            raise FileNotFoundError(f"Backend path not found: {backend_path}")

        table = dynamodb.Table(
            self,
            "ItemsTable",
            table_name=f"{self.stack_name}-items",
            partition_key=dynamodb.Attribute(
                name="item_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        lambda_code = lambda_.Code.from_asset(
            path=str(project_root),
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                command=[
                    "bash",
                    "-c",
                    "\n".join(
                        [
                            "set -euo pipefail",
                            "cd /asset-input",
                            "export HOME=/tmp",
                            "curl -LsSf https://astral.sh/uv/install.sh | sh",
                            'export PATH=\"$HOME/.local/bin:$HOME/.cargo/bin:$PATH\"',
                            "uv export --frozen --no-dev --no-group infra --output-file requirements.txt",
                            "python -m pip install --no-compile -r requirements.txt -t /asset-output",
                            "cp -r backend /asset-output/",
                            "rm -rf /asset-output/backend/tests",
                            "rm -f requirements.txt",
                        ]
                    ),
                ],
                environment={"PIP_DISABLE_PIP_VERSION_CHECK": "1"},
                working_directory="/asset-input",
            ),
        )

        allowed_origins = list(allowed_origins or ["*"])
        allow_credentials = "*" not in allowed_origins
        lambda_fn = lambda_.Function(
            self,
            "OffersBackendFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="backend.main.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment={
                "ITEMS_TABLE_NAME": table.table_name,
                "ALLOWED_ORIGINS": ",".join(allowed_origins),
            },
        )

        table.grant(
            lambda_fn,
            "dynamodb:GetItem",
            "dynamodb:PutItem",
        )

        integration = integrations.HttpLambdaIntegration(
            "OffersLambdaIntegration",
            handler=lambda_fn,
        )

        http_api = apigwv2.HttpApi(
            self,
            "OffersHttpApi",
            default_integration=integration,
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_credentials=allow_credentials,
                allow_headers=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_origins=allowed_origins,
                max_age=Duration.days(10),
            ),
        )

        cdk.CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)

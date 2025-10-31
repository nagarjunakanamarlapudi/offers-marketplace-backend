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
    aws_apigatewayv2_authorizers as apigw_authorizers,
    aws_apigatewayv2_integrations as integrations,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_ssm as ssm,
)


class ApiStack(Stack):
    def __init__(
        self,
        scope: cdk.App,
        construct_id: str,
        *,
        stage: str,
        allowed_origins: Sequence[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project_root = Path(__file__).resolve().parent.parent
        backend_path = project_root / "backend"
        if not backend_path.exists():
            raise FileNotFoundError(f"Backend path not found: {backend_path}")

        otp_ttl_seconds = 300
        otp_max_attempts = 5
        sms_dev_echo = "true" if stage in {"dev", "local"} else "false"

        table = dynamodb.Table(
            self,
            "ItemsTable",
            table_name=f"{stage}-items",
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
                platform="linux/arm64",
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
                            "rm -f requirements.txt",
                            "cp -r backend /asset-output/",
                            "cp -r lambdas /asset-output/",
                            "rm -rf /asset-output/backend/tests",
                        ]
                    ),
                ],
                environment={"PIP_DISABLE_PIP_VERSION_CHECK": "1"},
                working_directory="/asset-input",
            ),
        )

        trigger_env = {
            "OTP_TTL_SECONDS": str(otp_ttl_seconds),
            "OTP_MAX_ATTEMPTS": str(otp_max_attempts),
            "SMS_DEV_ECHO": sms_dev_echo,
        }

        define_challenge_fn = lambda_.Function(
            self,
            "DefineAuthChallengeFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/auth/define_auth_challenge.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=trigger_env,
        )

        create_challenge_fn = lambda_.Function(
            self,
            "CreateAuthChallengeFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/auth/create_auth_challenge.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=trigger_env,
        )

        verify_challenge_fn = lambda_.Function(
            self,
            "VerifyAuthChallengeFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/auth/verify_auth_challenge.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=trigger_env,
        )

        create_challenge_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                resources=["*"],
            )
        )

        user_pool = cognito.UserPool(
            self,
            "OffersUserPool",
            user_pool_name=f"{stage}-offers-users",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(phone=True),
            auto_verify=cognito.AutoVerifiedAttrs(phone=True),
            removal_policy=RemovalPolicy.RETAIN,
        )

        user_pool.add_trigger(
            cognito.UserPoolOperation.DEFINE_AUTH_CHALLENGE,
            define_challenge_fn,
        )
        user_pool.add_trigger(
            cognito.UserPoolOperation.CREATE_AUTH_CHALLENGE,
            create_challenge_fn,
        )
        user_pool.add_trigger(
            cognito.UserPoolOperation.VERIFY_AUTH_CHALLENGE_RESPONSE,
            verify_challenge_fn,
        )

        user_pool_client = user_pool.add_client(
            "OffersAppClient",
            auth_flows=cognito.AuthFlow(custom=True),
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
            ),
            access_token_validity=Duration.minutes(60),
            id_token_validity=Duration.minutes(60),
            refresh_token_validity=Duration.days(30),
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
        )

        allowed_origins = list(allowed_origins or ["*"])
        allow_credentials = "*" not in allowed_origins

        offers_lambda = lambda_.Function(
            self,
            "OffersBackendFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="backend.main.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment={
                "ITEMS_TABLE_NAME": table.table_name,
                "ALLOWED_ORIGINS": ",".join(allowed_origins),
                "STAGE": stage,
                "ENV": stage,
                "REGION": self.region,
                "USER_POOL_ID": user_pool.user_pool_id,
                "USER_POOL_CLIENT_ID": user_pool_client.user_pool_client_id,
            },
        )

        table.grant(
            offers_lambda,
            "dynamodb:GetItem",
            "dynamodb:PutItem",
        )

        common_http_env = {
            "ENV": stage,
            "REGION": self.region,
            "OTP_TTL_SECONDS": str(otp_ttl_seconds),
            "OTP_MAX_ATTEMPTS": str(otp_max_attempts),
            "SMS_DEV_ECHO": sms_dev_echo,
        }

        auth_start_fn = lambda_.Function(
            self,
            "AuthStartFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/http/auth_start.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=common_http_env,
        )

        auth_verify_fn = lambda_.Function(
            self,
            "AuthVerifyFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/http/auth_verify.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=common_http_env,
        )

        auth_refresh_fn = lambda_.Function(
            self,
            "AuthRefreshFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="lambdas/http/auth_refresh.handler",
            code=lambda_code,
            timeout=Duration.seconds(30),
            environment=common_http_env,
        )

        for fn in (auth_start_fn, auth_verify_fn, auth_refresh_fn):
            fn.add_environment("USER_POOL_ID", user_pool.user_pool_id)
            fn.add_environment("USER_POOL_CLIENT_ID", user_pool_client.user_pool_client_id)

        auth_start_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:AdminGetUser",
                    "cognito-idp:AdminUpdateUserAttributes",
                    "cognito-idp:AdminConfirmSignUp",
                    "cognito-idp:AdminInitiateAuth",
                ],
                resources=[user_pool.user_pool_arn],
            )
        )
        auth_start_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:SignUp",
                ],
                resources=["*"],
            )
        )

        auth_verify_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:AdminRespondToAuthChallenge",
                ],
                resources=[user_pool.user_pool_arn],
            )
        )

        auth_refresh_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "cognito-idp:InitiateAuth",
                ],
                resources=[user_pool.user_pool_arn],
            )
        )

        offers_integration = integrations.HttpLambdaIntegration(
            "OffersLambdaIntegration",
            handler=offers_lambda,
        )

        auth_start_integration = integrations.HttpLambdaIntegration(
            "AuthStartIntegration",
            handler=auth_start_fn,
        )

        auth_verify_integration = integrations.HttpLambdaIntegration(
            "AuthVerifyIntegration",
            handler=auth_verify_fn,
        )

        auth_refresh_integration = integrations.HttpLambdaIntegration(
            "AuthRefreshIntegration",
            handler=auth_refresh_fn,
        )

        http_api = apigwv2.HttpApi(
            self,
            f"OffersHttpApi-{stage}",
            api_name=f"OffersHttpApi-{stage}",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_credentials=allow_credentials,
                allow_headers=["*"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_origins=allowed_origins,
                max_age=Duration.days(10),
            ),
        )

        http_api.add_routes(
            path="/auth/start",
            methods=[apigwv2.HttpMethod.POST],
            integration=auth_start_integration,
        )
        http_api.add_routes(
            path="/auth/verify",
            methods=[apigwv2.HttpMethod.POST],
            integration=auth_verify_integration,
        )
        http_api.add_routes(
            path="/auth/refresh",
            methods=[apigwv2.HttpMethod.POST],
            integration=auth_refresh_integration,
        )

        http_api.add_routes(
            path="/healthz",
            methods=[apigwv2.HttpMethod.ANY],
            integration=offers_integration,
        )

        jwt_authorizer = apigw_authorizers.HttpJwtAuthorizer(
            "OffersJwtAuthorizer",
            jwt_issuer=f"https://cognito-idp.{self.region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[user_pool_client.user_pool_client_id],
        )

        http_api.add_routes(
            path="/offers",
            methods=[apigwv2.HttpMethod.ANY],
            integration=offers_integration,
            authorizer=jwt_authorizer,
        )
        http_api.add_routes(
            path="/offers/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=offers_integration,
            authorizer=jwt_authorizer,
        )
        http_api.add_routes(
            path="/items",
            methods=[apigwv2.HttpMethod.ANY],
            integration=offers_integration,
            authorizer=jwt_authorizer,
        )
        http_api.add_routes(
            path="/items/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=offers_integration,
            authorizer=jwt_authorizer,
        )

        ssm.StringParameter(
            self,
            "UserPoolIdParameter",
            parameter_name=f"/offers/{stage}/auth/user-pool-id",
            string_value=user_pool.user_pool_id,
        )

        ssm.StringParameter(
            self,
            "UserPoolClientIdParameter",
            parameter_name=f"/offers/{stage}/auth/app-client-id",
            string_value=user_pool_client.user_pool_client_id,
        )

        cdk.CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
        cdk.CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=user_pool_client.user_pool_client_id)

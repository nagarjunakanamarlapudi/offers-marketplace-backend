# Offers Marketplace Backend

Serverless FastAPI backend deployed on AWS Lambda using API Gateway (HTTP API v2) and DynamoDB. Dependency management and builds are handled exclusively with [`uv`](https://github.com/astral-sh/uv). Infrastructure is defined with the AWS CDK (Python).

## Features
- Python 3.12 FastAPI application packaged with Mangum for Lambda.
- DynamoDB table for item storage with `PutItem` and `GetItem` access scoped to the Lambda.
- Fully serverless deployment via AWS CDK with uv-powered bundling.
- Local development, unit tests, and smoke tests orchestrated with `make`.
- GitHub Actions pipeline for linting, testing, synthesis, and gated production deploys.
- Single uv-managed virtual environment shared across application and infrastructure tooling.
- Amazon Cognito user pool configured for passwordless custom authentication with SMS OTP delivery and JWT-protected API routes.

## Project Layout
```
backend/    # FastAPI application and tests
infra/      # AWS CDK app and stack
lambdas/    # Cognito triggers and HTTP Lambda handlers
scripts/    # Utility scripts (e.g. smoke test)
.github/    # CI/CD workflows
```

## Prerequisites
- Python 3.12+
- uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- AWS CDK CLI (`npm install -g aws-cdk`)
- AWS credentials with rights to synth/deploy the stack

## Local Development
1. **Install dependencies**
   ```bash
   make setup
   ```
2. **Run the API locally**
   ```bash
   AWS_PROFILE=local-dev \
   AWS_REGION=us-east-1 \
   ITEMS_TABLE_NAME=local-items \
   DYNAMODB_ENDPOINT_URL=http://localhost:8000 \
   ALLOWED_ORIGINS="*" \
   PORT=8002 \
   make run-local
   ```
   Override `PORT` if 8000 is busy. Point `DYNAMODB_ENDPOINT_URL` at DynamoDB Local/LocalStack, or omit it to talk to AWS directly (requires valid credentials and a provisioned table).
3. **Execute tests**
   ```bash
   make test
   ```

## Deployment
1. Bootstrap your AWS environment for CDK if needed:
   ```bash
   uv run cdk bootstrap
   ```
2. Deploy the stack (defaults to the `dev` stage locally):
   ```bash
   make deploy AWS_PROFILE=local-dev AWS_REGION=us-east-1 STACK_STAGE=dev
   ```
   To target production, set the stage explicitly (CI sets `STACK_STAGE=prod` automatically):
   ```bash
   make deploy AWS_PROFILE=prod-profile AWS_REGION=us-east-1 STACK_STAGE=prod
   ```
3. Destroy when finished:
   ```bash
   make destroy AWS_PROFILE=local-dev AWS_REGION=us-east-1 STACK_STAGE=dev
   ```

### Environment Configuration
- `ITEMS_TABLE_NAME` is injected into the Lambda by the stack and must be set for local runs.
- `ALLOWED_ORIGINS` controls CORS (comma-separated list or `*`).
- `DYNAMODB_ENDPOINT_URL` (optional) targets a custom DynamoDB endpoint for local development.
- `STACK_STAGE` controls the stack suffix and resource names (`dev` by default locally, `prod` in GitHub Actions).
- Authentication-specific environment variables (all injected by CDK):
  - `ENV`, `REGION`
  - `USER_POOL_ID`, `USER_POOL_CLIENT_ID`
  - `OTP_TTL_SECONDS` (default 300), `OTP_MAX_ATTEMPTS` (default 5)
  - `SMS_DEV_ECHO` (`true` for non-prod stages, `false` for `prod`)
- Configure GitHub repository variables/secrets:
  - `vars.AWS_REGION` – target AWS region
  - `secrets.AWS_DEPLOY_ROLE` – IAM role ARN for CDK deployments

### Stack Outputs and Parameters
Deployment surfaces the following for downstream consumers:
- CloudFormation outputs:
  - `ApiUrl` – invoke URL for the HTTP API
  - `UserPoolId` – Cognito user pool id
  - `UserPoolClientId` – Cognito app client id
- SSM parameters:
  - `/offers/{stage}/auth/user-pool-id`
  - `/offers/{stage}/auth/app-client-id`

## CI/CD
- Pull requests: lint (`ruff`) and test (`pytest`) using uv-managed environments.
- Main branch: reuses checks, synthesizes the CDK app, and deploys after environment approval.

## Smoke Testing
After deployment, run:
```bash
make smoke API_URL=https://xxxx.execute-api.<region>.amazonaws.com
```
This hits the `/healthz` endpoint and validates the deployment.

## Lambda Bundling (CDK)
- The stack uses `uv export --frozen` to produce a lock-backed `requirements.txt` inside the bundling container.
- Dependencies are installed with `pip install -r requirements.txt -t /asset-output`.
- Application modules plus Cognito/HTTP handlers are copied into the asset bundle, enabling both the FastAPI backend (`backend.main.handler`) and the auth-specific Lambda entrypoints.

## Passwordless Authentication Flow
The API exposes public routes for initiating and verifying SMS OTP challenges and protects `/offers*` with a Cognito JWT authorizer.

```bash
API="https://<api-id>.execute-api.<REGION>.amazonaws.com"
PHONE="+91XXXXXXXXXX"

# 1) Start login (issues CUSTOM_CHALLENGE and sends OTP via SNS)
curl -s -X POST "$API/auth/start" \
  -H "content-type: application/json" \
  -d "{\"phone\":\"$PHONE\"}"
# → { "session":"<opaque>", "phone":"+91…", "dev_otp":"123456" }   # dev_otp only if SMS_DEV_ECHO=true

# 2) Verify OTP and receive Cognito tokens
SESSION="<paste session>"
OTP="123456"   # from SMS (or dev_otp in dev)
curl -s -X POST "$API/auth/verify" \
  -H "content-type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"otp\":\"$OTP\",\"session\":\"$SESSION\"}"
# → { "access_token":"…", "id_token":"…", "refresh_token":"…", "expires_in":3600, "token_type":"Bearer" }

# 3) Call a protected endpoint
ACCESS_TOKEN="…"
curl -s -X POST "$API/items" \
  -H "content-type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d '{"item_id":"demo","name":"Sample","price":19.99}'


curl -s "$API/items/demo" \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# 4) Refresh tokens (optional)
REFRESH_TOKEN="…"
curl -s -X POST "$API/auth/refresh" \
  -H "content-type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}"
# → { "access_token":"…", "id_token":"…", "expires_in":3600, "token_type":"Bearer" }

# 5) Public health check
curl -i "$API/healthz"
```

## Runbook
```bash
make setup
make deploy AWS_PROFILE=local-dev AWS_REGION=us-east-1 STACK_STAGE=dev
make smoke API_URL=https://xxxx.execute-api.<region>.amazonaws.com
curl <API>/healthz
```

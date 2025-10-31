# Offers Marketplace Backend

Serverless FastAPI backend deployed on AWS Lambda using API Gateway (HTTP API v2) and DynamoDB. Dependency management and builds are handled exclusively with [`uv`](https://github.com/astral-sh/uv). Infrastructure is defined with the AWS CDK (Python).

## Features
- Python 3.12 FastAPI application packaged with Mangum for Lambda.
- DynamoDB table for item storage with `PutItem` and `GetItem` access scoped to the Lambda.
- Fully serverless deployment via AWS CDK with uv-powered bundling.
- Local development, unit tests, and smoke tests orchestrated with `make`.
- GitHub Actions pipeline for linting, testing, synthesis, and gated production deploys.
- Single uv-managed virtual environment shared across application and infrastructure tooling.

## Project Layout
```
backend/    # FastAPI application and tests
infra/      # AWS CDK app and stack
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
- Configure GitHub repository variables/secrets:
  - `vars.AWS_REGION` – target AWS region
  - `secrets.AWS_DEPLOY_ROLE` – IAM role ARN for CDK deployments

## CI/CD
- Pull requests: lint (`ruff`) and test (`pytest`) using uv-managed environments.
- Main branch: reuses checks, synthesizes the CDK app, and deploys after environment approval.

## Smoke Testing
After deployment, run:
```bash
make smoke API_URL=https://xxxx.execute-api.<region>.amazonaws.com
```
This hits the `/health` endpoint and validates the deployment.

## Lambda Bundling (CDK)
- The stack uses `uv export --frozen` to produce a lock-backed `requirements.txt` inside the bundling container.
- Dependencies are installed with `pip install -r requirements.txt -t /asset-output`.
- Application modules are copied into `/asset-output/backend`, enabling the `backend.main.handler` Lambda entrypoint.

## Runbook
```bash
make setup
make deploy AWS_PROFILE=local-dev AWS_REGION=us-east-1 STACK_STAGE=dev
make smoke API_URL=https://xxxx.execute-api.<region>.amazonaws.com
curl <API>/health
```

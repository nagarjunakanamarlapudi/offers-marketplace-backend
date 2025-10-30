# AI Agent Instructions for Offers Marketplace Backend

## Project Overview
This is a serverless FastAPI backend deployed on AWS Lambda with API Gateway v2 and DynamoDB. The project uses `uv` for dependency management and AWS CDK (Python) for infrastructure.

## Key Architecture Components

### FastAPI Application (`backend/`)
- Main application logic in `backend/main.py`
- Uses Mangum adapter for Lambda deployment
- Environment variables:
  - `ITEMS_TABLE_NAME`: DynamoDB table name (required)
  - `ALLOWED_ORIGINS`: CORS configuration
  - `DYNAMODB_ENDPOINT_URL`: Optional local endpoint

### Infrastructure (`infra/`)
- CDK stack in `api_stack.py` defines:
  - DynamoDB table with `item_id` partition key
  - Lambda function with Python 3.12 runtime
  - HTTP API Gateway v2 integration
  - CORS configuration

## Development Workflows

### Local Development
1. Use `make setup` to install dependencies via `uv`
2. Run API locally:
   ```bash
   AWS_PROFILE=local-dev \
   AWS_REGION=us-east-1 \
   ITEMS_TABLE_NAME=local-items \
   ALLOWED_ORIGINS="*" \
   make run-local
   ```

### Testing
- Run tests with `make test` (uses pytest)
- Smoke test deployment: `make smoke API_URL=<api-url>`

### Deployment
- Deploy: `make deploy`
- Destroy: `make destroy`
- Environment variables needed in CI:
  - `AWS_REGION`
  - `AWS_DEPLOY_ROLE` (IAM role ARN)

## Project Conventions

### Dependency Management
- Uses `uv` exclusively - no pip/poetry/virtualenv
- Dependencies defined in `pyproject.toml` groups:
  - Default: Core runtime deps
  - `dev`: Testing tools
  - `infra`: CDK libraries

### Code Structure
- FastAPI route handlers in `backend/main.py`
- Data models in `backend/models.py`
- Infrastructure as code strictly in `infra/`
- Helper scripts in `scripts/`

### Testing Patterns
- API tests in `backend/tests/`
- Test DynamoDB operations using local endpoints
- Smoke tests validate deployed endpoints

## Common Operations
- Adding dependencies: Edit `pyproject.toml`, then `make setup`
- Local testing: Start API with test environment variables
- Deployment checks: Run smoke tests against new endpoint
- Infrastructure changes: Edit `api_stack.py`, then `make deploy`
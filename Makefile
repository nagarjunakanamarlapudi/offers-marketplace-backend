SHELL := /bin/bash
AWS_PROFILE ?= local-dev
AWS_REGION ?= us-east-1
AWS_SDK_LOAD_CONFIG ?= 1
CDK_USE_CLI ?= 1
STACK_STAGE ?= dev
PORT ?= 8000
export AWS_PROFILE
export AWS_REGION
export AWS_SDK_LOAD_CONFIG
export CDK_USE_CLI
export STACK_STAGE

CDK_PROFILE_ARG :=
ifneq ($(AWS_PROFILE),)
CDK_PROFILE_ARG := --profile $(AWS_PROFILE)
endif

CDK_REGION_ARG :=
ifneq ($(AWS_REGION),)
CDK_REGION_ARG := --region $(AWS_REGION)
endif

CDK_CONTEXT_ARG := -c stage=$(STACK_STAGE)
CDK_ARGS := $(CDK_PROFILE_ARG) $(CDK_REGION_ARG) $(CDK_CONTEXT_ARG)

.PHONY: setup deploy destroy run-local test smoke synth

setup:
	uv sync --group dev --group infra

deploy:
	uv run cdk deploy $(CDK_ARGS)

destroy:
	uv run cdk destroy $(CDK_ARGS)

run-local:
	PYTHONPATH=. uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port $(PORT)

test:
	PYTHONPATH=. uv run pytest

synth:
	uv run cdk synth $(CDK_ARGS)

smoke:
ifndef API_URL
	$(error API_URL is not set. Usage: make smoke API_URL=https://xxx.execute-api.region.amazonaws.com)
endif
	uv run python scripts/smoke_test.py --api-url $(API_URL)

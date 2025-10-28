SHELL := /bin/bash
PORT ?= 8000

.PHONY: setup deploy destroy run-local test smoke synth

setup:
	uv sync --group dev --group infra

deploy:
	uv run cdk deploy

destroy:
	uv run cdk destroy

run-local:
	PYTHONPATH=. uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port $(PORT)

test:
	PYTHONPATH=. uv run pytest

synth:
	uv run cdk synth

smoke:
ifndef API_URL
	$(error API_URL is not set. Usage: make smoke API_URL=https://xxx.execute-api.region.amazonaws.com)
endif
	uv run python scripts/smoke_test.py --api-url $(API_URL)

SHELL := /bin/sh

DEV_ENV_FILE ?= infra/.env.local
PROD_ENV_FILE ?= infra/.env.prod
DEV_COMPOSE := docker compose --env-file $(DEV_ENV_FILE) -f infra/docker-compose.dev.yml
PROD_COMPOSE := docker compose --env-file $(PROD_ENV_FILE) -f infra/docker-compose.yml
DEV_AIRFLOW_PROFILE := --profile airflow
DEV_OBSERVABILITY_PROFILE := --profile observability
UV ?= uv
UV_RUN := $(UV) run

.PHONY: env env-local env-prod init bootstrap lint format test test-unit test-contracts test-integration test-integration-smoke test-integration-gpu up down restart logs ps config dev-up dev-up-airflow dev-up-observability dev-up-full dev-down prod-up prod-down verify verify-health seed build-index validate-index promote-index rollback-index demo minimal-slice retrieval-api bench-small bench-medium

env: env-local

env-local:
	@if [ ! -f $(DEV_ENV_FILE) ]; then echo "Missing $(DEV_ENV_FILE). Use infra/.env.local as the local bootstrap template."; exit 1; fi

env-prod:
	@if [ ! -f $(PROD_ENV_FILE) ]; then cp infra/.env.prod.example $(PROD_ENV_FILE); fi

bootstrap:
	$(UV) venv .venv --python 3.11
	$(UV) sync --group runtime-retrieval-api --group runtime-minimal-slice --group dev --locked

init: env-local
	$(DEV_COMPOSE) pull

lint:
	$(UV_RUN) ruff check .

format:
	$(UV_RUN) ruff format .

test:
	$(MAKE) test-unit

test-unit:
	$(UV_RUN) pytest -q tests/unit

test-contracts:
	$(UV_RUN) pytest -q tests/contracts

test-integration:
	$(UV_RUN) pytest -q tests/integration

test-integration-smoke:
	SKIP_GPU_TESTS=1 $(UV_RUN) pytest -q tests/integration/test_minimal_slice_smoke.py -k cpu

test-integration-gpu:
	SKIP_GPU_TESTS=0 $(UV_RUN) pytest -q tests/integration/test_minimal_slice_smoke.py -k gpu

dev-up: env-local
	$(DEV_COMPOSE) up -d

dev-up-airflow: env-local
	$(DEV_COMPOSE) $(DEV_AIRFLOW_PROFILE) up -d

dev-up-observability: env-local
	$(DEV_COMPOSE) $(DEV_OBSERVABILITY_PROFILE) up -d

dev-up-full: env-local
	$(DEV_COMPOSE) $(DEV_AIRFLOW_PROFILE) $(DEV_OBSERVABILITY_PROFILE) up -d

dev-down:
	$(DEV_COMPOSE) down

prod-up: env-prod
	$(PROD_COMPOSE) up -d

prod-down:
	$(PROD_COMPOSE) down

up: dev-up

down: dev-down

restart: down up

logs:
	$(DEV_COMPOSE) logs -f --tail=150

ps:
	$(DEV_COMPOSE) ps

config:
	$(DEV_COMPOSE) config

verify-health:
	docker compose --env-file $(DEV_ENV_FILE) -f infra/docker-compose.dev.yml ps
	$(UV_RUN) python -c "import urllib.request; urllib.request.urlopen('http://localhost:6333/healthz', timeout=5)"
	$(UV_RUN) python -c "import os, urllib.request; base=os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/'); urllib.request.urlopen(f'{base}/api/tags', timeout=5)"

verify: env-local
	$(DEV_COMPOSE) up -d
	$(UV_RUN) python scripts/verify_e2e.py

seed:
	$(UV_RUN) python -c "from pipelines.minimal_slice.synthetic_data import generate_synthetic_data; print(generate_synthetic_data(customer_count=200, seed=7))"

build-index:
	$(UV_RUN) python -c "from pipelines.minimal_slice.feature_mart import build_feature_mart_snapshot; from pipelines.minimal_slice.embedding import build_embeddings; from pipelines.minimal_slice.qdrant_index import build_generation; from pipelines.minimal_slice.config import RAW_PATH; fm=build_feature_mart_snapshot(raw_path=RAW_PATH); ep, vs = build_embeddings(feature_mart_path=fm); print(build_generation(embeddings_path=ep, vector_size=vs))"

validate-index:
	$(UV_RUN) python -c "from pipelines.minimal_slice.config import EMBEDDINGS_PATH; from pipelines.minimal_slice.lifecycle_service import build_system_actor, validate_latest; actor=build_system_actor('makefile'); print(validate_latest(actor=actor, embeddings_path=EMBEDDINGS_PATH))"

promote-index:
	$(UV_RUN) python -c "from pipelines.minimal_slice.lifecycle_service import build_system_actor, promote_latest; actor=build_system_actor('makefile'); print(promote_latest(actor=actor))"

rollback-index:
	$(UV_RUN) python -c "from pipelines.minimal_slice.lifecycle_service import build_system_actor, rollback_latest; actor=build_system_actor('makefile'); print(rollback_latest(actor=actor))"

demo:
	$(UV_RUN) python -m pipelines.minimal_slice.run_flow

minimal-slice:
	$(UV_RUN) python -m pipelines.minimal_slice.run_flow

retrieval-api:
	$(UV_RUN) python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000

bench-small:
	$(UV_RUN) python -m pipelines.minimal_slice.benchmark_harness --num-points 100000 --vector-size 384 --num-queries 200 --top-k 20 --batch-size 1000 --seed 42

bench-medium:
	$(UV_RUN) python -m pipelines.minimal_slice.benchmark_harness --num-points 1000000 --vector-size 384 --num-queries 500 --top-k 20 --batch-size 2000 --seed 42

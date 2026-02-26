SHELL := /bin/sh

ENV_FILE ?= infra/.env
DEV_COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/docker-compose.dev.yml
PROD_COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/docker-compose.yml

.PHONY: env init up down restart logs ps config dev-up dev-down prod-up prod-down verify minimal-slice retrieval-api

env:
	@if [ ! -f $(ENV_FILE) ]; then cp infra/.env.example $(ENV_FILE); fi

init: env
	$(DEV_COMPOSE) pull

dev-up: env
	$(DEV_COMPOSE) up -d

dev-down:
	$(DEV_COMPOSE) down

prod-up: env
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

verify:
	docker compose --env-file $(ENV_FILE) -f infra/docker-compose.dev.yml ps
	docker compose --env-file $(ENV_FILE) -f infra/docker-compose.dev.yml exec -T qdrant curl -fsS http://localhost:6333/healthz
	docker compose --env-file $(ENV_FILE) -f infra/docker-compose.dev.yml exec -T ollama ollama list

minimal-slice:
	python -m pipelines.minimal_slice.run_flow

retrieval-api:
	python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000

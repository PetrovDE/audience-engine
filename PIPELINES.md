# Pipelines

This project provides Airflow DAGs for the minimal slice pipeline in:

- `pipelines/airflow_dags/audience_engine_dags.py`

## DAGs

### `build_feature_mart`
- Purpose: build governed feature mart snapshot from raw records.
- Callable: `task_build_feature_mart`.
- Inputs: `data/minimal_slice/run/synthetic_customers.jsonl`.
- Outputs: `data/minimal_slice/run/feature_mart_snapshot.jsonl`.
- Schedule: `@daily`.

### `build_embeddings`
- Purpose: generate LLM embeddings from the feature mart.
- Callable: `task_build_embeddings`.
- Inputs: `data/minimal_slice/run/feature_mart_snapshot.jsonl`.
- Outputs: `data/minimal_slice/run/embeddings.jsonl`.
- Schedule: `@daily`.

### `build_index_blue`
- Purpose: build/recreate the blue Qdrant collection and upsert vectors.
- Callable: `task_build_index_blue`.
- Inputs: `data/minimal_slice/run/embeddings.jsonl`.
- Outputs: Qdrant collection `audience-credit-v1-blue`.
- Schedule: manual (`None`).

### `switch_alias`
- Purpose: atomically repoint serving alias to the blue index generation.
- Callable: `task_switch_alias`.
- Inputs: existing blue collection.
- Outputs: Qdrant alias `audience-serving` -> `audience-credit-v1-blue`.
- Schedule: manual (`None`).

### `data_contract_checks`
- Purpose: validate required contract fields for raw and feature mart datasets.
- Callable: `run_data_contract_checks`.
- Inputs:
  - `governance/contracts/raw.yaml`
  - `governance/contracts/feature_mart.yaml`
  - `data/minimal_slice/run/synthetic_customers.jsonl`
  - `data/minimal_slice/run/feature_mart_snapshot.jsonl`
- Outputs: pass/fail task result.
- Schedule: `@daily`.

## Recommended Run Order

1. `build_feature_mart`
2. `data_contract_checks`
3. `build_embeddings`
4. `build_index_blue`
5. `switch_alias`

## Notes

- `build_index_blue` currently performs alias switching through the shared index utility as part of collection build, and `switch_alias` can be run independently as an explicit promotion step.
- DAGs are intentionally independent so they can be run ad hoc from the Airflow UI.

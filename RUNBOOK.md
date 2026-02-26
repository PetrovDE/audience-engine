# Audience Engine Monitoring Runbook

## Scope
This runbook covers Prometheus + Grafana monitoring for:
- embedding throughput
- retrieval latency
- policy reject reasons
- data freshness

## Services and Endpoints
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`
- Retrieval API metrics endpoint: `http://localhost:8000/metrics`

## Bring-up
1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Start infra with monitoring:
   ```bash
   make dev-up
   ```
3. Start retrieval API:
   ```bash
   python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000
   ```
4. (Optional but recommended) Run one pipeline flow to seed embedding/policy/freshness metrics:
   ```bash
   python -m pipelines.minimal_slice.run_flow
   ```

## Grafana Dashboard
- Login to Grafana with `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD`.
- Open folder `Audience Engine`.
- Open dashboard `Audience Engine Monitoring`.

## Key Metrics
- `audience_embedding_throughput_docs_per_second{model=...}`
- `audience_retrieval_latency_seconds_bucket{query_mode=...}`
- `audience_policy_reject_reasons_total{reason_code=...}`
- `audience_data_freshness_seconds{dataset=...}`

## Prometheus Query Snippets
- Retrieval p95 latency:
  ```promql
  histogram_quantile(0.95, sum(rate(audience_retrieval_latency_seconds_bucket[5m])) by (le, query_mode))
  ```
- Policy rejects in last 15m:
  ```promql
  sum by (reason_code) (increase(audience_policy_reject_reasons_total[15m]))
  ```
- Current data freshness:
  ```promql
  audience_data_freshness_seconds
  ```
- Embedding throughput:
  ```promql
  audience_embedding_throughput_docs_per_second
  ```

## Alerts and Triage

### High retrieval latency
Symptoms:
- p95 retrieval latency is elevated for `query_text` or `query_customer_id`.

Checks:
1. Verify Qdrant health:
   ```bash
   curl -fsS http://localhost:6333/healthz
   ```
2. Check API process logs for errors/timeouts.
3. Compare `query_text` vs `query_customer_id` latency to isolate embedding-generation overhead.

Actions:
- Reduce `top_k` in callers for emergency mitigation.
- Confirm Ollama availability and model warm-up if `query_text` is slow.
- Scale API workers if CPU saturation is observed.

### Policy reject spike
Symptoms:
- Sudden increase in `audience_policy_reject_reasons_total` for one reason code.

Checks:
1. Run the minimal slice and inspect summary:
   ```bash
   python -m pipelines.minimal_slice.run_flow
   type data\minimal_slice\run\run_summary.json
   ```
2. Inspect blacklist and communication history inputs for drift.

Actions:
- Validate policy input feeds (`blacklist.txt`, `comm_history.jsonl`).
- If expected (campaign surge), communicate to stakeholders and continue monitoring.

### Stale data
Symptoms:
- `audience_data_freshness_seconds` crosses SLO threshold.

Checks:
1. Confirm pipeline execution completed successfully.
2. Validate source event timestamps in `synthetic_customers.jsonl` or upstream equivalent.

Actions:
- Re-run pipeline to refresh feature/embedding artifacts.
- Investigate upstream ingestion delay if freshness does not recover.

## Known Behavior
- Batch metrics (embedding throughput, policy rejects, freshness) are emitted when running pipeline code paths.
- Retrieval latency metrics are emitted by live API traffic on `/v1/retrieve`.

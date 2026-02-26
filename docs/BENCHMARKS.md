# Benchmarks: Qdrant 10M Readiness Harness

This benchmark harness measures:

- Synthetic vector + payload generation at configurable scale (`N` points).
- Qdrant generation build/load with batched upserts.
- Filtered kNN query latency percentiles (`p50`, `p95`, `p99`) for typical retrieval filters.
- Upsert throughput in points/second.

## Prerequisites

- Qdrant and Postgres are running (`make dev-up`).
- Python environment is bootstrapped (`make bootstrap`).
- Dependencies for `runtime-minimal-slice` are installed.

## Run

Preset targets:

- Small benchmark:
  - `make bench-small`
- Medium benchmark:
  - `make bench-medium`

Direct CLI usage:

```bash
uv run python -m pipelines.minimal_slice.benchmark_harness \
  --num-points 500000 \
  --vector-size 384 \
  --num-queries 400 \
  --top-k 20 \
  --batch-size 2000 \
  --seed 42
```

## Outputs

Each run writes:

- Embeddings JSONL:
  - `data/minimal_slice/benchmarks/bench_<timestamp>_embeddings.jsonl`
- Benchmark summary JSON:
  - `data/minimal_slice/benchmarks/bench_<timestamp>_results.json`

Summary includes:

- Config used (`num_points`, `vector_size`, `num_queries`, filter versions).
- Generation metadata (collection, alias, generation id, point count).
- Upsert metrics (`batch_size`, `batches`, `retries`, `elapsed_seconds`, `throughput_points_per_second`).
- kNN metrics (`p50`, `p95`, `p99`, `min`, `max`, average hits).

## Interpretation for 10M Readiness

- Latency shape:
  - `p95` and `p99` matter more than `p50` for campaign SLA safety.
  - Large `p99/p50` spread indicates tail instability under filters.
- Upsert throughput:
  - Use `throughput_points_per_second` to estimate full-load ingest time:
    - `estimated_seconds_for_10m = 10000000 / throughput_points_per_second`
  - Rising retries suggest backpressure or transient availability issues.
- Filter realism:
  - Harness queries include product, region, segment, suppression flags, tenure range, delinquency range, and version filters.
  - Keep these representative of production filter selectivity when comparing runs.

## Recommended Comparison Method

- Run each profile at least 3 times.
- Compare median of `p95`, `p99`, and throughput across runs.
- Keep hardware, Qdrant config, and background workload constant between runs.

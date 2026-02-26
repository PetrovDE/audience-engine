from datetime import datetime, timezone
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram

EMBEDDING_DOCS_TOTAL = Counter(
    "audience_embedding_docs_total",
    "Total number of documents embedded.",
    ["model"],
)

EMBEDDING_BATCH_DURATION_SECONDS = Histogram(
    "audience_embedding_batch_duration_seconds",
    "Time spent generating embeddings for a batch.",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 40, 60, 120),
)

EMBEDDING_THROUGHPUT_DOCS_PER_SECOND = Gauge(
    "audience_embedding_throughput_docs_per_second",
    "Latest embedding throughput measured for a batch.",
    ["model"],
)

RETRIEVAL_LATENCY_SECONDS = Histogram(
    "audience_retrieval_latency_seconds",
    "End-to-end retrieval latency.",
    ["query_mode"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5),
)

POLICY_REJECT_REASONS_TOTAL = Counter(
    "audience_policy_reject_reasons_total",
    "Policy rejections partitioned by reason code.",
    ["reason_code"],
)

DATA_FRESHNESS_SECONDS = Gauge(
    "audience_data_freshness_seconds",
    "Age of most recent source event in seconds.",
    ["dataset"],
)


def record_embedding_batch(model: str, doc_count: int, duration_seconds: float) -> None:
    EMBEDDING_DOCS_TOTAL.labels(model=model).inc(doc_count)
    EMBEDDING_BATCH_DURATION_SECONDS.observe(duration_seconds)
    if duration_seconds > 0:
        throughput = doc_count / duration_seconds
        EMBEDDING_THROUGHPUT_DOCS_PER_SECOND.labels(model=model).set(throughput)


def observe_retrieval_latency(query_mode: str, duration_seconds: float) -> None:
    RETRIEVAL_LATENCY_SECONDS.labels(query_mode=query_mode).observe(duration_seconds)


def record_policy_reject_reason(reason_code: str, count: int = 1) -> None:
    POLICY_REJECT_REASONS_TOTAL.labels(reason_code=reason_code).inc(count)


def record_data_freshness(dataset: str, latest_event_ts: Optional[str]) -> None:
    if not latest_event_ts:
        return
    ts = latest_event_ts.replace("Z", "+00:00")
    latest = datetime.fromisoformat(ts)
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - latest).total_seconds()
    DATA_FRESHNESS_SECONDS.labels(dataset=dataset).set(max(age_seconds, 0.0))

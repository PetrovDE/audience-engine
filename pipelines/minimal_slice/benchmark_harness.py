import argparse
import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from . import qdrant_index
from .config import DATA_DIR, POLICY_VERSION, QDRANT_URL
from .retrieval import _build_ann_filter


def _utc_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot compute percentile of empty values")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _sample_vector(rng: random.Random, vector_size: int) -> list[float]:
    vector = [rng.uniform(-1.0, 1.0) for _ in range(vector_size)]
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        return _sample_vector(rng, vector_size)
    return [v / norm for v in vector]


def _payload_for_customer(customer_idx: int, rng: random.Random) -> dict[str, Any]:
    return {
        "customer_id": f"bench_{customer_idx:08d}",
        "fs_version": "fs_credit_v1",
        "emb_version": "emb_bench_v1",
        "policy_version": POLICY_VERSION,
        "product_line": rng.choice(["credit_card", "personal_loan", "auto_loan"]),
        "region_code": rng.choice(["us_west", "us_central", "us_east"]),
        "segment_id": rng.choice(["mass", "affluent", "student", "smb"]),
        "is_employee_flag": rng.random() < 0.03,
        "do_not_contact_flag": rng.random() < 0.07,
        "opt_out_flag": rng.random() < 0.05,
        "legal_suppression_flag": rng.random() < 0.01,
        "customer_tenure_months": rng.randint(1, 180),
        "delinquency_12m_count": rng.randint(0, 6),
    }


def _write_embeddings(
    *,
    output_path: Path,
    num_points: int,
    vector_size: int,
    seed: int,
    fs_version: str,
    emb_version: str,
    policy_version: str,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    query_candidates: list[dict[str, Any]] = []
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for idx in range(num_points):
            vector = _sample_vector(rng, vector_size)
            payload = _payload_for_customer(idx, rng)
            payload["fs_version"] = fs_version
            payload["emb_version"] = emb_version
            payload["policy_version"] = policy_version
            row = {"vector": vector, **payload}
            handle.write(json.dumps(row) + "\n")

            # Keep a bounded query candidate pool with non-suppressed records.
            if (
                not payload["is_employee_flag"]
                and not payload["do_not_contact_flag"]
                and not payload["opt_out_flag"]
                and not payload["legal_suppression_flag"]
            ):
                if len(query_candidates) < 2000:
                    query_candidates.append(row)
                else:
                    replace_idx = rng.randint(0, idx)
                    if replace_idx < len(query_candidates):
                        query_candidates[replace_idx] = row
    return query_candidates


def _measure_query_latency_ms(
    *,
    collection_name: str,
    query_candidates: list[dict[str, Any]],
    top_k: int,
    num_queries: int,
    seed: int,
) -> dict[str, Any]:
    if not query_candidates:
        raise ValueError("No eligible query candidates available for benchmark queries")

    client = QdrantClient(url=QDRANT_URL)
    rng = random.Random(seed + 17)
    latencies_ms: list[float] = []
    total_hits = 0

    for _ in range(num_queries):
        sample = rng.choice(query_candidates)
        ann_filter = _build_ann_filter(
            product_line=sample["product_line"],
            region_codes=[sample["region_code"]],
            segment_ids=[sample["segment_id"]],
            min_tenure_months=max(1, int(sample["customer_tenure_months"]) - 24),
            max_delinquency_12m_count=min(
                8, int(sample["delinquency_12m_count"]) + 1
            ),
            fs_version=sample["fs_version"],
            emb_version=sample["emb_version"],
            policy_version=sample["policy_version"],
        )

        started = time.perf_counter()
        hits = client.search(
            collection_name=collection_name,
            query_vector=sample["vector"],
            query_filter=ann_filter,
            limit=top_k,
            with_payload=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies_ms.append(elapsed_ms)
        total_hits += len(hits)

    return {
        "query_count": num_queries,
        "top_k": top_k,
        "hits_avg": round(total_hits / max(1, num_queries), 3),
        "latency_ms": {
            "p50": round(_percentile(latencies_ms, 0.50), 3),
            "p95": round(_percentile(latencies_ms, 0.95), 3),
            "p99": round(_percentile(latencies_ms, 0.99), 3),
            "min": round(min(latencies_ms), 3),
            "max": round(max(latencies_ms), 3),
        },
    }


def run_benchmark(
    *,
    num_points: int,
    vector_size: int,
    num_queries: int,
    top_k: int,
    batch_size: int,
    seed: int,
    fs_version: str,
    emb_version: str,
    policy_version: str,
) -> dict[str, Any]:
    generation = f"bench_{_utc_token()}"
    run_dir = DATA_DIR / "benchmarks"
    embeddings_path = run_dir / f"{generation}_embeddings.jsonl"
    output_path = run_dir / f"{generation}_results.json"
    run_dir.mkdir(parents=True, exist_ok=True)

    query_candidates = _write_embeddings(
        output_path=embeddings_path,
        num_points=num_points,
        vector_size=vector_size,
        seed=seed,
        fs_version=fs_version,
        emb_version=emb_version,
        policy_version=policy_version,
    )

    qdrant_index.QDRANT_UPSERT_BATCH_SIZE = batch_size
    build_result = qdrant_index.build_generation(
        embeddings_path=embeddings_path,
        vector_size=vector_size,
        emb_version=emb_version,
        generation=generation,
    )

    latency_result = _measure_query_latency_ms(
        collection_name=build_result["collection"],
        query_candidates=query_candidates,
        top_k=top_k,
        num_queries=num_queries,
        seed=seed,
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "num_points": num_points,
            "vector_size": vector_size,
            "num_queries": num_queries,
            "top_k": top_k,
            "batch_size": batch_size,
            "seed": seed,
            "fs_version": fs_version,
            "emb_version": emb_version,
            "policy_version": policy_version,
        },
        "generation": {
            "alias": build_result["alias"],
            "collection": build_result["collection"],
            "generation": build_result["generation"],
            "points_count": build_result["points_count"],
        },
        "upsert": build_result["upsert"],
        "knn": latency_result,
        "files": {
            "embeddings_jsonl": str(embeddings_path),
            "results_json": str(output_path),
        },
    }

    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Qdrant 10M-readiness benchmark harness for synthetic vector data."
    )
    parser.add_argument("--num-points", type=int, required=True)
    parser.add_argument("--vector-size", type=int, default=384)
    parser.add_argument("--num-queries", type=int, default=200)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fs-version", default="fs_credit_v1")
    parser.add_argument("--emb-version", default="emb_bench_v1")
    parser.add_argument("--policy-version", default=POLICY_VERSION)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = run_benchmark(
        num_points=args.num_points,
        vector_size=args.vector_size,
        num_queries=args.num_queries,
        top_k=args.top_k,
        batch_size=args.batch_size,
        seed=args.seed,
        fs_version=args.fs_version,
        emb_version=args.emb_version,
        policy_version=args.policy_version,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

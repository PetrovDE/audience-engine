# Scale 10M: Qdrant Payload and Filter Strategy

## Payload Schema (Retrieval-Critical Fields)

The ANN retrieval path uses payload filters before policy evaluation. These fields are written with each point payload:

- `customer_id` (`keyword`): deterministic lookup and traceability.
- `fs_version` (`keyword`): retrieval/version isolation.
- `emb_version` (`keyword`): retrieval/version isolation.
- `policy_version` (`keyword`): policy-version-aware retrieval slices.
- `product_line` (`keyword`): product-aware retrieval partitioning.
- `region_code` (`keyword`): regional audience scoping.
- `segment_id` (`keyword`): customer segment scoping.
- `is_employee_flag` (`bool`): hard suppression at query-time.
- `do_not_contact_flag` (`bool`): hard suppression at query-time.
- `opt_out_flag` (`bool`): hard suppression at query-time.
- `legal_suppression_flag` (`bool`): hard suppression at query-time.
- `customer_tenure_months` (`integer`): eligibility threshold filtering.
- `delinquency_12m_count` (`integer`): risk threshold filtering.

## Indexed Fields Rationale

Payload indexes are created during `build_generation` for all retrieval-time filter keys above.

- `keyword` indexes support exact-match and set-membership filters used for product/region/segment/version isolation.
- `bool` indexes support low-latency hard suppressions (DNC/employee/opt-out/legal) during ANN search.
- `integer` indexes support range filters (`min_tenure_months`, `max_delinquency_12m_count`) to reduce policy-stage rejects.
- Indexing only retrieval-critical payload fields limits index footprint while preserving filter selectivity at 10M scale.

## Expected Query Patterns

Primary ANN query patterns:

1. Customer-seeded ANN:
   - Query vector from `query_customer_id`.
   - Filter by `product_line`, optional `region_code`/`segment_id`, hard suppressions, and eligibility ranges.

2. Text-seeded ANN:
   - Query vector from embedding model.
   - Same payload filters as customer-seeded flow.

3. Version-aware ANN:
   - Optional filter by `fs_version`, `emb_version`, and/or `policy_version` when operating parallel generations.

Target behavior:

- Filtered ANN reduces off-policy/off-product candidates before policy engine execution.
- Policy engine remains mandatory and authoritative, but query-time filtering reduces rejected candidate volume and improves latency predictability for 10M+ collections.

CREATE TABLE IF NOT EXISTS feature_mart_snapshot
(
    customer_id String,
    fs_version String,
    policy_version String,
    customer_age_years Int32,
    customer_tenure_months Int32,
    credit_score_band String,
    delinquency_12m_count Int32,
    utilization_ratio_avg_3m Float64,
    card_spend_total_3m Float64,
    digital_engagement_score Float64,
    is_employee_flag UInt8,
    do_not_contact_flag UInt8,
    opt_out_flag UInt8,
    legal_suppression_flag UInt8,
    region_code String,
    segment_id String,
    product_line String,
    event_ts DateTime('UTC') DEFAULT now('UTC')
)
ENGINE = MergeTree
ORDER BY customer_id;

-- Migration 007: allow explicit non-success status for delivery runs with no staged rows.
-- Aligns status constraints with delivery_contract.DELIVERY_STATUSES.

ALTER TABLE audience_delivery_job
DROP CONSTRAINT IF EXISTS audience_delivery_job_status_check;

ALTER TABLE audience_delivery_job
ADD CONSTRAINT audience_delivery_job_status_check CHECK (
    status IN (
        'pending',
        'materialized',
        'delivered',
        'failed',
        'skipped_conflict',
        'skipped_no_source_rows'
    )
);

ALTER TABLE audience_delivery_attempt
DROP CONSTRAINT IF EXISTS audience_delivery_attempt_attempt_status_check;

ALTER TABLE audience_delivery_attempt
ADD CONSTRAINT audience_delivery_attempt_attempt_status_check CHECK (
    attempt_status IN (
        'pending',
        'materialized',
        'delivered',
        'failed',
        'skipped_conflict',
        'skipped_no_source_rows'
    )
);

ALTER TABLE audience_delivery_record
DROP CONSTRAINT IF EXISTS audience_delivery_record_delivery_status_check;

ALTER TABLE audience_delivery_record
ADD CONSTRAINT audience_delivery_record_delivery_status_check CHECK (
    delivery_status IN (
        'pending',
        'materialized',
        'delivered',
        'failed',
        'skipped_conflict',
        'skipped_no_source_rows'
    )
);

ALTER TABLE audience_crm_postgres_outbox
DROP CONSTRAINT IF EXISTS audience_crm_postgres_outbox_outbox_status_check;

ALTER TABLE audience_crm_postgres_outbox
ADD CONSTRAINT audience_crm_postgres_outbox_outbox_status_check CHECK (
    outbox_status IN (
        'pending',
        'materialized',
        'delivered',
        'failed',
        'skipped_conflict',
        'skipped_no_source_rows'
    )
);

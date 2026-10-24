-- Unity Catalog OTLP target tables for Zerobus Ingest (otel.schemaVersion = v2)
-- Docs: https://docs.databricks.com/aws/en/ingestion/opentelemetry/configure
--
-- This demo uses:
--   catalog: ot_pdm_semi_catalog
--   schema:  agentforce_otel
--   prefix:  agentforce

CREATE SCHEMA IF NOT EXISTS ot_pdm_semi_catalog.agentforce_otel
COMMENT 'Suncorp demo: Salesforce Agentforce OTel -> Zerobus Ingest';

CREATE TABLE IF NOT EXISTS ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans (
  record_id STRING,
  time TIMESTAMP,
  date DATE,
  service_name STRING,
  trace_id STRING,
  span_id STRING,
  trace_state STRING,
  parent_span_id STRING,
  flags INT,
  name STRING,
  kind STRING,
  start_time_unix_nano LONG,
  end_time_unix_nano LONG,
  attributes VARIANT,
  dropped_attributes_count INT,
  events ARRAY<STRUCT<
    time_unix_nano: LONG,
    name: STRING,
    attributes: VARIANT,
    dropped_attributes_count: INT
  >>,
  dropped_events_count INT,
  links ARRAY<STRUCT<
    trace_id: STRING,
    span_id: STRING,
    trace_state: STRING,
    attributes: VARIANT,
    dropped_attributes_count: INT,
    flags: INT
  >>,
  dropped_links_count INT,
  status STRUCT<code: STRING, message: STRING>,
  resource STRUCT<
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  resource_schema_url STRING,
  instrumentation_scope STRUCT<
    name: STRING,
    version: STRING,
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  span_schema_url STRING
) USING DELTA
CLUSTER BY (time, service_name, trace_id)
TBLPROPERTIES (
  'otel.schemaVersion' = 'v2',
  'delta.checkpointPolicy' = 'classic',
  'delta.enableVariantShredding' = 'true',
  'delta.feature.variantShredding' = 'supported',
  'delta.feature.variantType' = 'supported'
);

CREATE TABLE IF NOT EXISTS ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_logs (
  record_id STRING,
  time TIMESTAMP,
  date DATE,
  service_name STRING,
  event_name STRING,
  severity_number STRING,
  severity_text STRING,
  body VARIANT,
  attributes VARIANT,
  dropped_attributes_count INT,
  flags INT,
  trace_id STRING,
  span_id STRING,
  time_unix_nano LONG,
  observed_time_unix_nano LONG,
  resource STRUCT<
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  resource_schema_url STRING,
  instrumentation_scope STRUCT<
    name: STRING,
    version: STRING,
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  log_schema_url STRING
) USING DELTA
CLUSTER BY (time, service_name)
TBLPROPERTIES (
  'otel.schemaVersion' = 'v2',
  'delta.checkpointPolicy' = 'classic',
  'delta.enableVariantShredding' = 'true',
  'delta.feature.variantShredding' = 'supported',
  'delta.feature.variantType' = 'supported'
);

CREATE TABLE IF NOT EXISTS ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_metrics (
  record_id STRING,
  time TIMESTAMP,
  date DATE,
  service_name STRING,
  start_time_unix_nano LONG,
  time_unix_nano LONG,
  name STRING,
  description STRING,
  unit STRING,
  metric_type STRING,
  gauge STRUCT<
    value: DOUBLE,
    exemplars: ARRAY<STRUCT<
      time_unix_nano: LONG,
      value: DOUBLE,
      span_id: STRING,
      trace_id: STRING,
      filtered_attributes: VARIANT
    >>,
    attributes: VARIANT,
    flags: INT
  >,
  sum STRUCT<
    value: DOUBLE,
    exemplars: ARRAY<STRUCT<
      time_unix_nano: LONG,
      value: DOUBLE,
      span_id: STRING,
      trace_id: STRING,
      filtered_attributes: VARIANT
    >>,
    attributes: VARIANT,
    flags: INT,
    aggregation_temporality: STRING,
    is_monotonic: BOOLEAN
  >,
  histogram STRUCT<
    count: LONG,
    sum: DOUBLE,
    bucket_counts: ARRAY<LONG>,
    explicit_bounds: ARRAY<DOUBLE>,
    exemplars: ARRAY<STRUCT<
      time_unix_nano: LONG,
      value: DOUBLE,
      span_id: STRING,
      trace_id: STRING,
      filtered_attributes: VARIANT
    >>,
    attributes: VARIANT,
    flags: INT,
    min: DOUBLE,
    max: DOUBLE,
    aggregation_temporality: STRING
  >,
  exponential_histogram STRUCT<
    attributes: VARIANT,
    count: LONG,
    sum: DOUBLE,
    scale: INT,
    zero_count: LONG,
    positive_bucket: STRUCT<
      offset: INT,
      bucket_counts: ARRAY<LONG>
    >,
    negative_bucket: STRUCT<
      offset: INT,
      bucket_counts: ARRAY<LONG>
    >,
    flags: INT,
    exemplars: ARRAY<STRUCT<
      time_unix_nano: LONG,
      value: DOUBLE,
      span_id: STRING,
      trace_id: STRING,
      filtered_attributes: VARIANT
    >>,
    min: DOUBLE,
    max: DOUBLE,
    zero_threshold: DOUBLE,
    aggregation_temporality: STRING
  >,
  summary STRUCT<
    count: LONG,
    sum: DOUBLE,
    quantile_values: ARRAY<STRUCT<
      quantile: DOUBLE,
      value: DOUBLE
    >>,
    attributes: VARIANT,
    flags: INT
  >,
  metadata VARIANT,
  resource STRUCT<
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  resource_schema_url STRING,
  instrumentation_scope STRUCT<
    name: STRING,
    version: STRING,
    attributes: VARIANT,
    dropped_attributes_count: INT
  >,
  metric_schema_url STRING
) USING DELTA
CLUSTER BY (time, service_name)
TBLPROPERTIES (
  'otel.schemaVersion' = 'v2',
  'delta.checkpointPolicy' = 'classic',
  'delta.enableVariantShredding' = 'true',
  'delta.feature.variantShredding' = 'supported',
  'delta.feature.variantType' = 'supported'
);

-- Replace <SP_APPLICATION_ID> with the service principal applicationId (UUID)
-- GRANT USE CATALOG ON CATALOG ot_pdm_semi_catalog TO `<SP_APPLICATION_ID>`;
-- GRANT USE SCHEMA ON SCHEMA ot_pdm_semi_catalog.agentforce_otel TO `<SP_APPLICATION_ID>`;
-- GRANT MODIFY, SELECT ON TABLE ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans TO `<SP_APPLICATION_ID>`;
-- GRANT MODIFY, SELECT ON TABLE ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_logs TO `<SP_APPLICATION_ID>`;
-- GRANT MODIFY, SELECT ON TABLE ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_metrics TO `<SP_APPLICATION_ID>`;

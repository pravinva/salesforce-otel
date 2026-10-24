-- Demo queries for Agentforce OTel spans in Unity Catalog

-- Recent Agentforce spans
SELECT
  time,
  service_name,
  name,
  status.code AS status_code,
  trace_id,
  span_id,
  parent_span_id,
  attributes,
  resource.attributes AS resource_attributes
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
ORDER BY time DESC
LIMIT 50;

-- Span tree for a single Agentforce session/trace
-- SET trace_id = '<trace_id from previous query>';
SELECT
  name,
  kind,
  status.code,
  parent_span_id,
  span_id,
  (end_time_unix_nano - start_time_unix_nano) / 1e6 AS duration_ms,
  attributes:['gen_ai.operation.name'] AS genai_op,
  attributes:['agent.topic'] AS agent_topic
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
WHERE trace_id = :trace_id
ORDER BY start_time_unix_nano;

-- Latency by span name (Agentforce topics / tools / LLM calls)
SELECT
  name,
  COUNT(*) AS spans,
  ROUND(AVG((end_time_unix_nano - start_time_unix_nano) / 1e6), 2) AS avg_ms,
  ROUND(PERCENTILE((end_time_unix_nano - start_time_unix_nano) / 1e6, 0.95), 2) AS p95_ms
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
WHERE time > current_timestamp() - INTERVAL 7 DAYS
GROUP BY name
ORDER BY spans DESC
LIMIT 30;

-- Error spans
SELECT time, name, status.message, trace_id, attributes
FROM ot_pdm_semi_catalog.agentforce_otel.agentforce_otel_spans
WHERE status.code = 'STATUS_CODE_ERROR'
ORDER BY time DESC
LIMIT 20;

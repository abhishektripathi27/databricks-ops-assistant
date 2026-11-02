# Day 3: Pipelines

## Telemetry pipeline (`ops_assistant_telemetry`, serverless, triggered)

| Table | Type | What it does |
|---|---|---|
| `curated.bronze_readings` | Streaming table | Auto Loader reads raw JSON from the Volume. Two warn-only expectations track missing status and the -999 sensor value. |
| `curated.silver_readings` | Streaming table | Parses timestamps, rebuilds missing status from the fault code, drops duplicates on (device_id, ts), drops rows that fail any rule. Clustered by device_id and event_date. |
| `curated.silver_readings_quarantine` | Streaming table | Rows that failed a silver rule, with a `failed_rules` array. |
| `curated.dim_device` | Materialized view | Device registry from `raw.devices`. |
| `curated.gold_device_hourly` | Materialized view | Hourly avg/min/max per sensor, alarm and warn counts. |
| `curated.gold_fault_events` | Materialized view | One row per fault episode: codes seen, latest code, peaks, duration, `is_transient`. |
| `curated.gold_device_status` | Materialized view | Latest reading per device, minutes since last reading, alarm counts in the last 24 hours of data. |

### Design choices

- **Quarantine instead of silent drop.** The silver expectations drop bad rows, and a parallel table keeps them with the rule names. I can show exactly what I rejected and why.
- **Repair what I can, reject what I can't.** A null status is rebuilt from the fault code. A -999 temperature can't be repaired, so the row goes to quarantine.
- **Fault episodes, not raw fault rows.** Sensors near a limit flap (V-02 on, off, on). Gaps and islands with a 3 hour gap merges flaps into one episode. Episodes under 3 readings are flagged `is_transient`. The agent on Day 6 reads this table instead of 576k raw rows.
- **"Last 24 hours" is relative to the latest reading,** stored as `as_of`, so the tables stay consistent if I run the pipeline days after generating data.
- **Logic lives in plain functions** (`clean_readings`, `failed_rules`, `fault_episodes`, `latest_status`) with pytest coverage in `tests/`. The pipeline decorators only wire them up.

### Expected results with the Day 2 data

- bronze about 576,400 rows, silver about 574,700, quarantine about 1,100 (all `temperature_in_range`)
- `gold_device_status`: only D-114 and D-037 have alarms in the last 24 hours
- `gold_fault_events`: sustained episodes for D-037, D-089, D-114, D-162 and the D-200 C-01 reconnect; a few transient blips before D-114 and D-037 cross their limits

### Re-running

Auto Loader only reads new files. If I re-run `generate_data`, it rewrites the files under new names, so bronze would ingest everything twice. After regenerating data, run a full refresh:
`databricks bundle run telemetry_pipeline --full-refresh-all`

## Document parsing (`src/ingest/04_parse_docs.py`)

- pypdf in layout mode, one row per page into `curated.parsed_docs`
- Removes the repeating footer, keeps table rows on one line with ` | ` between columns
- Adds `doc_type` (manual, sop, external) and `device_model` from the file name for metadata filters on Day 4
- Last cell tries `ai_parse_document` on one manual for a quality comparison. Wrapped table cells are where it should beat pypdf.

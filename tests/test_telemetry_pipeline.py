"""Unit tests for the telemetry pipeline logic. Run: pytest tests/"""
from pyspark.sql import Row


def readings(spark, rows):
    cols = ["device_id", "ts", "temperature_f", "vibration_mm_s", "power_kw", "pressure_psi", "status", "fault_code"]
    return spark.createDataFrame([Row(**dict(zip(cols, r))) for r in rows], schema=pipeline_schema())


def pipeline_schema():
    return ("device_id string, ts string, temperature_f double, vibration_mm_s double, power_kw double, "
            "pressure_psi double, status string, fault_code string")


def test_clean_readings_repairs_null_status(spark, pipeline):
    df = readings(spark, [
        ("D-1", "2026-10-01T00:00:00Z", 36.0, 1.0, 4.0, 250.0, None, None),
        ("D-1", "2026-10-01T00:15:00Z", 36.0, 1.0, 4.0, 250.0, None, "V-02"),
        ("D-1", "2026-10-01T00:30:00Z", 36.0, 1.0, 4.0, 250.0, None, "E-21"),
    ])
    out = pipeline.clean_readings(df).orderBy("ts").collect()
    assert [r.status for r in out] == ["OK", "WARN", "ALARM"]
    assert all(r.status_was_null for r in out)
    assert out[0].ts is not None


def test_failed_rules_flags_sentinel_and_missing_ids(spark, pipeline):
    df = pipeline.clean_readings(readings(spark, [
        ("D-1", "2026-10-01T00:00:00Z", -999.0, 1.0, 4.0, None, "OK", None),
        (None, "2026-10-01T00:00:00Z", 36.0, 1.0, 4.0, None, "OK", None),
        ("D-2", "2026-10-01T00:00:00Z", 36.0, 1.0, 4.0, None, "OK", None),
    ]))
    bad = {(r.device_id, tuple(r.failed_rules)) for r in pipeline.failed_rules(df).collect()}
    assert bad == {("D-1", ("temperature_in_range",)), (None, ("has_device_id",))}


def test_fault_episodes_merges_flapping_codes_and_splits_on_gap(spark, pipeline):
    df = pipeline.clean_readings(readings(spark, [
        ("D-1", "2026-10-01T00:00:00Z", 36.0, 5.0, 4.0, None, "WARN", "V-02"),
        ("D-1", "2026-10-01T00:15:00Z", 36.0, 7.5, 4.0, None, "ALARM", "V-03"),
        ("D-1", "2026-10-01T00:30:00Z", 36.0, 1.0, 4.0, None, "OK", None),       # short dip, same episode
        ("D-1", "2026-10-01T00:45:00Z", 36.0, 7.9, 4.0, None, "ALARM", "V-03"),
        ("D-1", "2026-10-01T05:00:00Z", 36.0, 5.0, 4.0, None, "WARN", "V-02"),   # over 3h later, new episode
    ]))
    eps = pipeline.fault_episodes(df).orderBy("first_seen").collect()
    assert len(eps) == 2
    assert eps[0].fault_codes == ["V-02", "V-03"]
    assert eps[0].latest_fault_code == "V-03"
    assert eps[0].reached_alarm is True
    assert eps[0].peak_vibration_mm_s == 7.9
    assert eps[0].duration_minutes == 45
    assert eps[0].is_transient is False
    assert eps[1].reached_alarm is False
    assert eps[1].is_transient is True


def test_latest_status_counts_last_24h(spark, pipeline):
    df = pipeline.clean_readings(readings(spark, [
        ("D-1", "2026-10-01T00:00:00Z", 36.0, 1.0, 4.0, None, "ALARM", "E-42"),  # older than 24h
        ("D-1", "2026-10-03T00:00:00Z", 44.0, 1.0, 4.0, None, "ALARM", "E-42"),
        ("D-2", "2026-10-02T12:00:00Z", 36.0, 1.0, 4.0, None, "OK", None),
    ]))
    out = {r.device_id: r for r in pipeline.latest_status(df).collect()}
    assert out["D-1"].alarm_readings_24h == 1
    assert out["D-1"].temperature_f == 44.0
    assert out["D-2"].minutes_since_last_reading == 720

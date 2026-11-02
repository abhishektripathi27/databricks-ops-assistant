import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def spark():
    from pyspark.sql import SparkSession
    s = (SparkSession.builder.master("local[2]").appName("tests")
         .config("spark.sql.shuffle.partitions", "4")
         .config("spark.sql.session.timeZone", "UTC").getOrCreate())
    s.sparkContext.setLogLevel("ERROR")
    yield s
    s.stop()


@pytest.fixture(scope="session")
def pipeline():
    return load_module("src/ingest/03_telemetry_pipeline.py", "telemetry_pipeline")

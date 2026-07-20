from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from dashboard import parquet_cache


class ParquetCacheTests(unittest.TestCase):
    def tearDown(self):
        parquet_cache.clear_parquet_memory_cache()

    def test_cache_hit_skips_loader_and_corruption_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            cache_dir = data_dir / "cache"
            source = data_dir / "source.csv"
            source.parent.mkdir(parents=True)
            source.write_text("value\n1\n", encoding="utf-8")
            calls = 0

            def loader():
                nonlocal calls
                calls += 1
                return pd.DataFrame({"value": [1], "mixed": ["10%"]})

            with patch.object(parquet_cache, "ROOT", root), patch.object(parquet_cache, "CACHE_DIR", cache_dir):
                first = parquet_cache.load_or_build_parquet("sample", [source], loader)
                second = parquet_cache.load_or_build_parquet("sample", [source], loader)
                self.assertEqual(calls, 1)
                pd.testing.assert_frame_equal(first, second)

                cache_file = next(cache_dir.glob("sample-*.parquet"))
                cache_file.write_bytes(b"not parquet")
                parquet_cache.clear_parquet_memory_cache()
                rebuilt = parquet_cache.load_or_build_parquet("sample", [source], loader)
                self.assertEqual(calls, 2)
                self.assertEqual(rebuilt.iloc[0]["value"], 1)

    def test_schema_version_change_builds_a_new_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            cache_dir = data_dir / "cache"
            source = data_dir / "source.csv"
            source.parent.mkdir(parents=True)
            source.write_text("value\n1\n", encoding="utf-8")
            calls = 0

            def loader():
                nonlocal calls
                calls += 1
                return pd.DataFrame({"value": [calls]})

            with patch.object(parquet_cache, "ROOT", root), patch.object(parquet_cache, "CACHE_DIR", cache_dir):
                with patch.object(parquet_cache, "CACHE_SCHEMA_VERSION", "test-a"):
                    parquet_cache.load_or_build_parquet("versioned", [source], loader)
                with patch.object(parquet_cache, "CACHE_SCHEMA_VERSION", "test-b"):
                    result = parquet_cache.load_or_build_parquet("versioned", [source], loader)
                self.assertEqual(calls, 2)
                self.assertEqual(result.iloc[0]["value"], 2)


if __name__ == "__main__":
    unittest.main()

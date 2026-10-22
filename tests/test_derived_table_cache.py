from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from unittest.mock import patch

import pandas as pd

import dashboard.derived_table_cache as cache


class DerivedTableCacheTests(unittest.TestCase):
    def test_corrupt_parquet_is_rebuilt_and_original_dtypes_are_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            calls = 0

            def loader():
                nonlocal calls
                calls += 1
                return {
                    "detail": pd.DataFrame(
                        {
                            "name": pd.Series(["one", pd.NA], dtype="object"),
                            "quantity": pd.Series([3, pd.NA], dtype="Int64"),
                        }
                    )
                }, {"available": True}

            with patch.object(cache, "DATA_DIR", data_dir):
                first, metadata = cache.load_or_build_frame_bundle("test-bundle", "v1", loader)
                manifest = next((data_dir / "cache" / "derived").glob("test-bundle-*.json"))
                parquet = next(manifest.parent.glob(f"{manifest.stem}-*.parquet"))
                parquet.write_bytes(b"corrupt parquet")
                rebuilt, rebuilt_metadata = cache.load_or_build_frame_bundle("test-bundle", "v1", loader)

            self.assertEqual(calls, 2)
            self.assertEqual(metadata, rebuilt_metadata)
            self.assertEqual(str(rebuilt["detail"]["quantity"].dtype), "Int64")
            self.assertEqual(first["detail"].loc[0, "name"], rebuilt["detail"].loc[0, "name"])

    def test_concurrent_requests_share_one_bundle_build(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = 0
            calls_lock = Lock()

            def loader():
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.05)
                return {"detail": pd.DataFrame({"asin": ["B001"]})}, {"ready": True}

            with patch.object(cache, "DATA_DIR", Path(directory)):
                with ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(
                        executor.map(
                            lambda _: cache.load_or_build_frame_bundle("single-flight", "v1", loader),
                            range(4),
                        )
                    )

            self.assertEqual(calls, 1)
            self.assertTrue(all(result[0]["detail"].loc[0, "asin"] == "B001" for result in results))


if __name__ == "__main__":
    unittest.main()

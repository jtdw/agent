from __future__ import annotations

import unittest
from pathlib import Path

from core.domestic_sources.gscloud_download_recovery import (
    is_gscloud_transient_download_error,
    normalize_refresh_attempts,
)
from core.domestic_sources.gscloud_stable_downloader import per_tile_download_timeout_ms


class GSCloudDownloadRecoveryTests(unittest.TestCase):
    def test_detects_bjdl_404_download_error_page(self) -> None:
        text = (
            "\u627e\u4e0d\u5230\u6b64 bjdl.gscloud.cn \u9875\n"
            "\u627e\u4e0d\u5230\u4ee5\u4e0b Web \u5730\u5740\u7684\u7f51\u9875:\n"
            "https://bjdl.gscloud.cn/sources/download/306/utm_srtm_57_07?sid=x&uid=1\n"
            "HTTP ERROR 404"
        )

        self.assertTrue(
            is_gscloud_transient_download_error(
                "https://bjdl.gscloud.cn/sources/download/306/utm_srtm_57_07?sid=x&uid=1",
                "\u627e\u4e0d\u5230\u6b64 bjdl.gscloud.cn \u9875",
                text,
            )
        )

    def test_does_not_flag_normal_access_table(self) -> None:
        self.assertFalse(
            is_gscloud_transient_download_error(
                "https://www.gscloud.cn/sources/accessdata/306?pid=302",
                "\u6570\u636e\u68c0\u7d22",
                "\u6570\u636e\u6807\u8bc6 utm_srtm_57_07 \u4e0b\u8f7d",
            )
        )

    def test_refresh_attempts_are_clamped_for_speed_and_safety(self) -> None:
        self.assertEqual(normalize_refresh_attempts("-1"), 0)
        self.assertEqual(normalize_refresh_attempts("3"), 3)
        self.assertEqual(normalize_refresh_attempts("99"), 8)

    def test_tile_download_event_timeout_is_capped_for_fast_recovery(self) -> None:
        self.assertEqual(per_tile_download_timeout_ms(1800), 45_000)
        self.assertEqual(per_tile_download_timeout_ms(10), 30_000)

    def test_download_entrypoints_use_refresh_recovery(self) -> None:
        files = [
            Path("core/domestic_sources/gscloud_stable_downloader.py"),
            Path("core/domestic_sources/gscloud_scene_table.py"),
            Path("core/domestic_sources/gscloud_modnd1d.py"),
            Path("core/domestic_sources/gscloud_landsat.py"),
            Path("core/domestic_sources/gscloud_adapter.py"),
            Path("core/domestic_sources/gscloud_indexer.py"),
        ]

        for path in files:
            with self.subTest(path=str(path)):
                source = path.read_text(encoding="utf-8")
                self.assertIn("recover_gscloud_download_from_error_page", source)


if __name__ == "__main__":
    unittest.main()

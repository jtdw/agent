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

    def test_detects_chrome_error_page_when_body_mentions_gscloud_download_url(self) -> None:
        text = (
            "\u627e\u4e0d\u5230\u4ee5\u4e0b Web \u5730\u5740\u7684\u7f51\u9875:\n"
            "https://bjdl.gscloud.cn/sources/download/306/utm_srtm_57_06?sid=x&uid=1\n"
            "HTTP ERROR 404"
        )

        self.assertTrue(
            is_gscloud_transient_download_error(
                "chrome-error://chromewebdata/",
                "\u627e\u4e0d\u5230\u6b64 bjdl.gscloud.cn \u9875",
                text,
            )
        )

    def test_detects_direct_gscloud_download_url_even_before_error_body_is_readable(self) -> None:
        self.assertTrue(
            is_gscloud_transient_download_error(
                "https://bjdl.gscloud.cn/sources/download/306/utm_srtm_57_06?sid=x&uid=1",
                "",
                "",
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

    def test_tile_download_event_timeout_allows_slow_gscloud_file_preparation(self) -> None:
        self.assertEqual(per_tile_download_timeout_ms(1800), 240_000)
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

    def test_stable_tile_downloader_restores_search_page_and_persists_failure_steps(self) -> None:
        source = Path("core/domestic_sources/gscloud_stable_downloader.py").read_text(encoding="utf-8")

        self.assertIn("def _restore_identifier_search_page", source)
        self.assertIn("def _click_and_wait_for_download", source)
        self.assertIn('page.on("download"', source)
        self.assertIn("_restore_identifier_search_page(page, start_url)", source)
        self.assertIn(".download-img", source)
        self.assertIn("td:last-child img", source)
        self.assertLess(
            source.index("_update_status(status_path, download_steps=step_records"),
            source.index("if not downloaded:"),
        )


if __name__ == "__main__":
    unittest.main()

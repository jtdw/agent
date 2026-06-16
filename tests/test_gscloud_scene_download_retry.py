from __future__ import annotations

import unittest

from core.domestic_sources.gscloud_modnd1d import _click_row_download as click_modis_row_download


class FakeDownloadInfo:
    def __init__(self, value: object):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FlakyPage:
    def __init__(self):
        self.calls = 0

    def expect_download(self, timeout: int):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("download event was not captured")
        return FakeDownloadInfo({"ok": True, "timeout": timeout})


class FakeLocator:
    def __init__(self, available: bool):
        self.available = available

    def count(self) -> int:
        return 1 if self.available else 0

    @property
    def first(self):
        return self

    def click(self, timeout: int) -> None:
        return None


class FakeRow:
    def __init__(self):
        self.calls = 0

    def locator(self, selector: str):
        self.calls += 1
        return FakeLocator(self.calls == 1)


class GSCloudSceneDownloadRetryTests(unittest.TestCase):
    def test_scene_row_download_retries_when_first_download_event_fails(self) -> None:
        page = FlakyPage()

        download = click_modis_row_download(page, FakeRow(), timeout_ms=1000)

        self.assertEqual(download, {"ok": True, "timeout": 1000})
        self.assertEqual(page.calls, 2)


if __name__ == "__main__":
    unittest.main()

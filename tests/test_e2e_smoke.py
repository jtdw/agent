from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import e2e_smoke


class E2ESmokeContractTests(unittest.TestCase):
    def test_frontend_check_waits_for_dom_content_loaded(self) -> None:
        calls: list[dict] = []

        class FakeLocator:
            def inner_text(self, timeout: int) -> str:
                return "GIS Agent frontend loaded"

        class FakePage:
            def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
                calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})

            def locator(self, selector: str) -> FakeLocator:
                assert selector == "body"
                return FakeLocator()

            def content(self) -> str:
                return "<html><body>GIS Agent frontend loaded</body></html>"

        class FakeBrowser:
            def new_page(self, viewport: dict) -> FakePage:
                return FakePage()

            def close(self) -> None:
                return None

        class FakePlaywright:
            chromium = type("Chromium", (), {"launch": staticmethod(lambda headless: FakeBrowser())})()

        class FakeSyncPlaywright:
            def __enter__(self) -> FakePlaywright:
                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        with patch.object(e2e_smoke, "sync_playwright", return_value=FakeSyncPlaywright()):
            e2e_smoke.check_frontend()

        self.assertEqual(calls[0]["wait_until"], "domcontentloaded")


if __name__ == "__main__":
    unittest.main()

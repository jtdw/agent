from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.domestic_sources.gscloud_adapter import _page_has_authenticated_gscloud_session


class GSCloudLoginDetectionTests(unittest.TestCase):
    def test_logout_control_marks_page_as_authenticated(self) -> None:
        page = MagicMock()

        def locator(selector: str):
            item = MagicMock()
            item.count.return_value = 1 if "退出" in selector else 0
            item.first = item
            item.is_visible.return_value = True
            return item

        page.locator.side_effect = locator

        self.assertTrue(_page_has_authenticated_gscloud_session(page))

    def test_login_only_page_is_not_authenticated(self) -> None:
        page = MagicMock()
        item = MagicMock()
        item.count.return_value = 0
        item.first = item
        page.locator.return_value = item

        self.assertFalse(_page_has_authenticated_gscloud_session(page))


if __name__ == "__main__":
    unittest.main()

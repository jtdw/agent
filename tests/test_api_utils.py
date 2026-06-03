from __future__ import annotations

import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path


@unittest.skipIf(find_spec("fastapi") is None, "fastapi is not installed in this Python environment")
class ApiUtilsTest(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import HTTPException
        from core.api_utils import api_guard, resolve_child_path

        self.HTTPException = HTTPException
        self.api_guard = api_guard
        self.resolve_child_path = resolve_child_path

    def test_resolve_child_path_allows_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "exports" / "result.txt"
            target.parent.mkdir()
            target.write_text("ok", encoding="utf-8")

            self.assertEqual(self.resolve_child_path(root, "exports/result.txt"), target.resolve())

    def test_resolve_child_path_blocks_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root.parent / "outside.txt"
            outside.write_text("no", encoding="utf-8")
            try:
                with self.assertRaises(PermissionError):
                    self.resolve_child_path(root, "../outside.txt")
            finally:
                outside.unlink(missing_ok=True)

    def test_api_guard_maps_unhandled_error_to_error_id(self) -> None:
        def fail() -> None:
            raise RuntimeError("boom")

        with self.assertRaises(self.HTTPException) as caught:
            self.api_guard(fail, context="test")

        self.assertEqual(caught.exception.status_code, 500)
        self.assertIsInstance(caught.exception.detail, dict)
        self.assertIn("error_id", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()

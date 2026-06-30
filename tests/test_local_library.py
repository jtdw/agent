from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.local_library import LocalFileLibrary, is_user_visible_library_item, resolve_local_library_root


class LocalLibraryFilteringTest(unittest.TestCase):
    def test_source_docs_are_hidden_by_default(self) -> None:
        self.assertFalse(is_user_visible_library_item({"name": "README_from_source", "path": "data/x/README_from_source.md", "data_type": "document"}))
        self.assertFalse(is_user_visible_library_item({"name": "LICENSE_from_source", "path": "data/x/LICENSE_from_source.txt", "data_type": "document"}))
        self.assertTrue(is_user_visible_library_item({"name": "field_notes", "path": "data/x/field_notes.md", "data_type": "document"}))
        self.assertTrue(is_user_visible_library_item({"name": "README", "path": "data/x/README.zip", "data_type": "archive"}))

    def test_list_items_can_include_source_docs_for_admin_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data" / "administrative"
            data_dir.mkdir(parents=True)
            (data_dir / "README_from_source.md").write_text("source", encoding="utf-8")
            (data_dir / "china_admin_boundary.zip").write_bytes(b"zip")

            library = LocalFileLibrary(root)
            library.rescan()

            public_items = library.list_items()["items"]
            admin_items = library.list_items(include_source_docs=True)["items"]

            self.assertEqual([item["name"] for item in public_items], ["china_admin_boundary"])
            self.assertEqual({item["name"] for item in admin_items}, {"README_from_source", "china_admin_boundary"})

    def test_default_root_prefers_project_library_when_workspace_library_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workdir = base / "workspace"
            project_root = base / "project"
            (workdir / "local_library" / "data").mkdir(parents=True)
            (project_root / "local_library" / "data" / "administrative").mkdir(parents=True)
            (project_root / "local_library" / "library_manifest.json").write_text(
                '{"version": 1, "items": [{"item_id": "lib_admin", "path": "data/administrative/admin.zip"}]}',
                encoding="utf-8",
            )
            (project_root / "local_library" / "data" / "administrative" / "admin.zip").write_bytes(b"zip")

            self.assertEqual(
                resolve_local_library_root(workdir, env_value="", project_root=project_root),
                project_root / "local_library",
            )

    def test_explicit_local_library_env_still_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            configured = base / "configured_library"

            self.assertEqual(
                resolve_local_library_root(base / "workspace", env_value=str(configured), project_root=base / "project"),
                configured,
            )

    def test_empty_workspace_env_does_not_hide_project_library_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            workdir = base / "workspace"
            project_root = base / "project"
            workspace_library = workdir / "local_library"
            workspace_library.mkdir(parents=True)
            (workspace_library / "library_manifest.json").write_text('{"version": 1, "items": []}', encoding="utf-8")
            (project_root / "local_library" / "data").mkdir(parents=True)
            (project_root / "local_library" / "data" / "admin.zip").write_bytes(b"zip")

            self.assertEqual(
                resolve_local_library_root(workdir, env_value=str(workspace_library), project_root=project_root),
                project_root / "local_library",
            )


if __name__ == "__main__":
    unittest.main()

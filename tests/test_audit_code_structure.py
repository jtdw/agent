from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.audit_code_structure import build_audit, write_audit


class AuditCodeStructureTests(unittest.TestCase):
    def test_build_audit_reports_backend_frontend_and_runtime_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core").mkdir()
            (root / "core" / "sample.py").write_text(
                "from pathlib import Path\n\ndef active():\n    return Path('.')\n\n"
                "def active():\n    return None  # deprecated\n",
                encoding="utf-8",
            )
            (root / "api_server.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n"
                "@app.get('/api/example')\ndef example():\n    return {}\n",
                encoding="utf-8",
            )
            frontend = root / "ui_next" / "src"
            frontend.mkdir(parents=True)
            (frontend / "App.tsx").write_text("import './feature';\nexport const App = () => null;\n", encoding="utf-8")
            (root / "workspace").mkdir()
            (root / "workspace" / "workspace.db").write_bytes(b"db")

            report = build_audit(root)

        self.assertEqual(report["api_routes"][0]["path"], "/api/example")
        self.assertIn("active", report["duplicate_python_functions"])
        self.assertEqual(report["frontend_imports"][0]["source"], "ui_next/src/App.tsx")
        self.assertEqual(report["runtime"]["workspace"]["files"], 1)
        self.assertTrue(report["markers"])

    def test_write_audit_writes_only_to_requested_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            (root / "api_server.py").write_text("value = 1\n", encoding="utf-8")
            output = Path(temp_dir) / "audit" / "report.json"

            written = write_audit(root, output)

            self.assertEqual(written, output.resolve())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["project_root"], str(root.resolve()))
            self.assertEqual((root / "api_server.py").read_text(encoding="utf-8"), "value = 1\n")


if __name__ == "__main__":
    unittest.main()

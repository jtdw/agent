from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class ApiHelpersLightweightTests(unittest.TestCase):
    def test_api_helpers_import_does_not_load_agent(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import core.api_helpers; print('core.agent' in sys.modules)",
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(proc.stdout.strip(), "False")

    def test_relative_artifact_url_uses_explicit_workspace_root(self) -> None:
        from core.api_helpers import relative_artifact_url

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            target = root / "exports" / "result.txt"
            target.parent.mkdir(parents=True)
            target.write_text("ok", encoding="utf-8")

            url = relative_artifact_url(root, target, user_id="u_alice")
            query = parse_qs(urlparse(url).query)

            self.assertEqual(query.get("path"), ["exports/result.txt"])
            self.assertEqual(query.get("user_id"), ["u_alice"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.api_helpers import relative_artifact_url


class WorkspaceArtifactContractTests(unittest.TestCase):
    def test_anonymous_workspace_artifact_url_does_not_invent_user_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            target = workdir / "exports" / "result.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("ok", encoding="utf-8")

            url = relative_artifact_url(workdir, str(target))
            query = parse_qs(urlparse(url).query)

            self.assertEqual(query.get("path"), ["exports/result.txt"])
            self.assertNotIn("user_id", query)

    def test_authenticated_workspace_artifact_url_uses_explicit_user_id(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            workdir = Path(tmp) / "workspace"
            target = workdir / "exports" / "result.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("ok", encoding="utf-8")

            url = relative_artifact_url(workdir, str(target), user_id="u_alice")
            query = parse_qs(urlparse(url).query)

            self.assertEqual(query.get("user_id"), ["u_alice"])
            self.assertEqual(query.get("path"), ["exports/result.txt"])


if __name__ == "__main__":
    unittest.main()

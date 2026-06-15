from __future__ import annotations

import unittest

from core.api_helpers import relative_artifact_url


class WorkspaceArtifactContractTests(unittest.TestCase):
    def test_anonymous_workspace_artifact_url_uses_artifact_id(self) -> None:
        url = relative_artifact_url("artifact_result")

        self.assertEqual(url, "/api/artifacts/artifact_result/download")
        self.assertNotIn("path=", url)

    def test_authenticated_workspace_artifact_url_uses_explicit_user_id(self) -> None:
        url = relative_artifact_url("artifact_result", user_id="u_alice")

        self.assertEqual(url, "/api/artifacts/artifact_result/download?user_id=u_alice")


if __name__ == "__main__":
    unittest.main()

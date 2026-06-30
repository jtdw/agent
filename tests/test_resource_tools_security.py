from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.data_manager import DataManager
from core.resource_tools import build_resource_tools, validate_public_http_url


class ResourceToolsSecurityTests(unittest.TestCase):
    def test_rejects_localhost_and_private_network_urls(self):
        for url in (
            "http://localhost/admin",
            "http://127.0.0.1:8000/private",
            "http://10.0.0.5/file.zip",
            "http://172.16.1.2/file.zip",
            "http://192.168.1.2/file.zip",
            "http://169.254.169.254/latest/meta-data",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_public_http_url(url)

    def test_allows_public_http_url_shape(self):
        self.assertEqual(validate_public_http_url("https://example.com/data.zip"), "https://example.com/data.zip")

    def test_download_backend_status_does_not_expose_workspace_paths(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp) / "workspace")
            tools = {tool.name: tool for tool in build_resource_tools(manager)}

            payload = json.loads(tools["download_backend_status"].invoke({}))
            rendered = json.dumps(payload, ensure_ascii=False)

            self.assertNotIn("workdir", payload)
            self.assertNotIn("temp_dir", payload)
            self.assertNotIn("root", payload.get("local_library", {}))
            self.assertNotIn(str(manager.workdir), rendered)
            self.assertNotIn(str(manager.temp_dir), rendered)


if __name__ == "__main__":
    unittest.main()

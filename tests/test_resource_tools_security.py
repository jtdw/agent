from __future__ import annotations

import unittest

from core.resource_tools import validate_public_http_url


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


if __name__ == "__main__":
    unittest.main()

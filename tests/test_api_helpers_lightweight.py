from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()

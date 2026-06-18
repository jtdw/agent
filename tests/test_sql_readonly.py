from pathlib import Path
import tempfile
import unittest

import pandas as pd

from core.data_manager import DataManager


class SqlReadonlyTests(unittest.TestCase):
    def test_workspace_query_rejects_mutating_sql(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope(user_id="u_1", session_id="s_1")
            manager.put_table("sample", pd.DataFrame({"x": [1, 2]}))

            with self.assertRaises(PermissionError):
                manager.query_database("DROP TABLE tbl_sample")

            result = manager.query_database("SELECT x FROM tbl_sample ORDER BY x")
            self.assertEqual(result["x"].tolist(), [1, 2])

    def test_workspace_query_rejects_multiple_statements(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope(user_id="u_1", session_id="s_1")
            manager.put_table("sample", pd.DataFrame({"x": [1]}))

            with self.assertRaises(PermissionError):
                manager.query_database("SELECT * FROM tbl_sample; SELECT * FROM tbl_sample")


if __name__ == "__main__":
    unittest.main()

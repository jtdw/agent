from pathlib import Path
import tempfile
import unittest

from core.data_manager import DataManager


class UploadSecurityTests(unittest.TestCase):
    def test_same_filename_uploads_do_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            manager.set_runtime_scope(user_id="u_1", session_id="s_1")

            first = manager.save_uploaded_bytes("../same.csv", b"a,b\n1,2\n")
            second = manager.save_uploaded_bytes("../same.csv", b"a,b\n3,4\n")

            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(first.read_bytes(), b"a,b\n1,2\n")
            self.assertEqual(second.read_bytes(), b"a,b\n3,4\n")
            self.assertEqual(first.parent, manager.upload_dir)
            self.assertEqual(second.parent, manager.upload_dir)


if __name__ == "__main__":
    unittest.main()

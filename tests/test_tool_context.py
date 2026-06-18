from pathlib import Path
import tempfile
import unittest

from core.tool_context import ToolRuntimeContext
from core.data_manager import DataManager
from core.tool_executor import execute_validated_tool_plan


class ToolContextTests(unittest.TestCase):
    def test_tool_executor_applies_runtime_context_to_manager(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            manager = DataManager(Path(tmp))
            context = ToolRuntimeContext(
                current_user_id="u_ctx",
                current_session_id="s_ctx",
                workspace_dir=Path(tmp),
                permission_scope={"database:read"},
            )
            plan = {"tool_plan": [{"tool_name": "workspace_status", "args": {"user_id": "attacker", "session_id": "other"}}]}

            result = execute_validated_tool_plan(manager, plan, allow_tools={"workspace_status"}, context=context)

            self.assertTrue(result["executed"])
            self.assertEqual(manager.current_user_id, "u_ctx")
            self.assertEqual(manager.current_session_id, "s_ctx")


if __name__ == "__main__":
    unittest.main()

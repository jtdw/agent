from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.config import Settings
from core.context_builder import build_conversation_context, format_context_for_agent
from core.conversation_state import ConversationState
from core.service import GISWorkspaceService


class LLMFirstLayerTests(unittest.TestCase):
    def make_service(self, root: Path) -> GISWorkspaceService:
        settings = Settings(api_key="", workdir=root / "workspace")
        settings.ensure_dirs()
        return GISWorkspaceService(settings)

    def test_global_agent_policy_contains_required_operating_rules(self) -> None:
        from core.agent_policy import load_global_agent_policy

        policy = load_global_agent_policy()

        self.assertIn("先理解完整用户目标", policy)
        self.assertIn("关键词不能直接触发工具", policy)
        self.assertIn("不得伪造文件、指标、下载状态或处理结果", policy)
        self.assertIn("真实操作必须由工具执行", policy)

    def test_langchain_agent_system_prompt_uses_global_policy(self) -> None:
        from core.agent import SYSTEM_PROMPT
        from core.agent_policy import load_global_agent_policy

        self.assertIn(load_global_agent_policy(), SYSTEM_PROMPT)

    def test_tool_cards_have_required_schema_and_cover_core_tools(self) -> None:
        from core.tool_cards import REQUIRED_TOOL_CARD_FIELDS, list_tool_cards

        cards = list_tool_cards()
        by_name = {card["tool_name"]: card for card in cards}

        for required_name in (
            "download_backend_status",
            "vector_clip_by_vector",
            "raster_basic_stats",
            "table_to_points",
            "plot_dataset",
            "generic_xgboost_workflow",
            "geographical_conformal_prediction",
        ):
            self.assertIn(required_name, by_name)

        for card in cards:
            with self.subTest(tool=card.get("tool_name")):
                self.assertTrue(REQUIRED_TOOL_CARD_FIELDS.issubset(card))
                self.assertIsInstance(card["required_inputs"], list)
                self.assertIsInstance(card["confirmation_required"], bool)
                self.assertIsInstance(card["forbidden_uses"], list)

    def test_knowledge_base_retrieves_versioned_scoped_snippets(self) -> None:
        from core.knowledge_base import retrieve_knowledge_snippets

        snippets = retrieve_knowledge_snippets("站点 栅格 特征 提取 XGBoost 空间交叉验证", limit=4)

        self.assertGreaterEqual(len(snippets), 2)
        joined = "\n".join(item["title"] + " " + item["content"] for item in snippets)
        self.assertIn("XGBoost", joined)
        self.assertIn("栅格", joined)
        for item in snippets:
            self.assertIn("source", item)
            self.assertIn("version", item)
            self.assertIn("scope", item)
            self.assertIn("trust_level", item)

    def test_asset_profiler_extracts_table_metadata_without_guessing_role_from_name(self) -> None:
        from core.asset_profiler import profile_dataset

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "soil_named_file",
                pd.DataFrame(
                    {
                        "station_id": ["S1", "S2", "S3"],
                        "date": ["2024-01-01", "2024-01-02", "2024-01-03"],
                        "longitude": [115.1, 115.2, 115.3],
                        "latitude": [41.1, 41.2, 41.3],
                        "soil_moisture": [0.12, 0.15, 0.18],
                    }
                ),
            )

            profile = profile_dataset(service.manager, "soil_named_file")

            self.assertEqual(profile["name"], "soil_named_file")
            self.assertEqual(profile["data_type"], "table")
            self.assertEqual(profile["row_count"], 3)
            self.assertIn("soil_moisture", profile["fields"])
            self.assertEqual(profile["time_range"]["start"], "2024-01-01")
            self.assertEqual(profile["time_range"]["end"], "2024-01-03")
            self.assertEqual(profile["role_inference"]["basis"], "metadata_only")
            self.assertNotIn("soil_named_file", profile["role_inference"]["evidence"])

    def test_context_builder_adds_relevant_policy_cards_knowledge_and_profiles(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            service.manager.put_table(
                "stations",
                pd.DataFrame(
                    {
                        "lon": [100.0, 101.0],
                        "lat": [30.0, 31.0],
                        "soil_moisture": [0.2, 0.3],
                        "ndvi": [0.6, 0.7],
                    }
                ),
            )
            state = ConversationState(active_dataset="stations")
            intent = {"intent": "modeling", "confidence": 0.9}

            context = build_conversation_context(
                "用站点土壤水分和 NDVI 做 XGBoost 建模",
                intent,
                state.to_dict(),
                service.manager,
                service.dashboard(),
            )
            formatted = format_context_for_agent(context)

            self.assertIn("agent_policy", context)
            self.assertIn("candidate_tool_cards", context)
            self.assertIn("knowledge_snippets", context)
            self.assertIn("asset_profile", context["active_dataset"])
            self.assertIn("generic_xgboost_workflow", formatted)
            self.assertIn("XGBoost", formatted)
            self.assertLess(len(formatted), 20000)

    def test_context_builder_adds_download_candidates_for_download_requests(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            service = self.make_service(Path(tmp))
            context = build_conversation_context(
                "准备下载 Sentinel-2 和 DEM 数据",
                {"intent": "data_download", "confidence": 0.9},
                ConversationState().to_dict(),
                service.manager,
                service.dashboard(),
            )
            formatted = format_context_for_agent(context)

            self.assertIn("download_candidates", context)
            self.assertIn("area_candidates", context)
            product_ids = {item["product_id"] for item in context["download_candidates"] if item.get("product_id")}
            self.assertIn("gscloud_sentinel2_msi", product_ids)
            self.assertIn("gscloud_dem_30m", product_ids)
            for item in context["download_candidates"]:
                self.assertEqual(item["source_key"], "gscloud")
                self.assertTrue(item["confirmation_required"])
                self.assertNotIn("submit", item)
            self.assertIn("download_candidates", formatted)
            self.assertIn("area_candidates", formatted)
            self.assertIn("confirmation_required", formatted)


if __name__ == "__main__":
    unittest.main()

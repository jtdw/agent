from __future__ import annotations

import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from core.config import Settings
from core.service import GISWorkspaceService
from core.tool_cards import candidate_tool_cards, list_tool_cards
from core.tool_contracts import parse_tool_result
from core.tools.registry import build_tools


def _write_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("readme.txt", "official ismn archive fixture")


def test_ismn_tools_are_registered_and_list_archives_safely() -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
        archive_path = service.manager.upload_dir / "official_ismn.zip"
        _write_zip(archive_path)
        tools = {tool.name: tool for tool in build_tools(service.manager)}

        assert "list_ismn_archives" in tools
        assert "profile_ismn_archive" in tools
        assert "import_ismn_soil_moisture_archive" in tools

        result = parse_tool_result(tools["list_ismn_archives"].invoke({}))
        encoded = json.dumps(result, ensure_ascii=False)

        assert result is not None
        assert result["ok"] is True, json.dumps(result, ensure_ascii=False, indent=2)
        assert result["outputs"]["archives"][0]["filename"] == "official_ismn.zip"
        assert str(service.manager.workdir) not in encoded


def test_ismn_profile_tool_returns_structured_missing_dependency(monkeypatch) -> None:
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        service = GISWorkspaceService(Settings(api_key="", workdir=Path(tmp) / "workspace"))
        archive_path = service.manager.upload_dir / "official_ismn.zip"
        _write_zip(archive_path)
        monkeypatch.setattr("core.ismn_adapter.load_ismn_interface_class", lambda: None)
        tools = {tool.name: tool for tool in build_tools(service.manager)}

        result = parse_tool_result(tools["profile_ismn_archive"].invoke({"archive": str(archive_path)}))

        assert result is not None
        assert result["ok"] is False
        assert result["error_code"] == "ISMN_DEPENDENCY_MISSING"


def test_ismn_tool_cards_are_retrievable() -> None:
    names = {card["tool_name"] for card in list_tool_cards()}
    candidates = {card["tool_name"] for card in candidate_tool_cards("import ISMN soil moisture archive", task_type="modeling", limit=12)}

    assert {"list_ismn_archives", "profile_ismn_archive", "import_ismn_soil_moisture_archive"}.issubset(names)
    assert "import_ismn_soil_moisture_archive" in candidates

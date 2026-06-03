from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DomesticSource:
    """国内数据源元信息。

    注意：这里不存储账号密码。账号密码应放在 .env / 系统环境变量 / Windows 凭据管理器中。
    """

    key: str
    name: str
    home_url: str
    login_url: str = ""
    categories: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    username_env: str = ""
    password_env: str = ""
    storage_state_name: str = ""

    @property
    def storage_file_name(self) -> str:
        return self.storage_state_name or f"{self.key}_storage_state.json"


@dataclass
class DomesticDownloadResult:
    source_key: str
    downloaded_path: Path
    dataset_name: str | None = None
    auto_loaded: bool = False
    extracted_dir: Path | None = None
    zip_path: Path | None = None
    message: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "downloaded_path": str(self.downloaded_path),
            "dataset_name": self.dataset_name,
            "auto_loaded": self.auto_loaded,
            "extracted_dir": str(self.extracted_dir) if self.extracted_dir else None,
            "zip_path": str(self.zip_path) if self.zip_path else None,
            "message": self.message,
            "meta": self.meta,
        }

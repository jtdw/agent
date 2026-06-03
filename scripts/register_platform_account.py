from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import load_settings
from core.commercial.service import CommercialService


def main() -> None:
    settings = load_settings()
    commercial = CommercialService(settings.workdir)
    username = os.getenv("GSCLOUD_PLATFORM_USERNAME", "").strip()
    password = os.getenv("GSCLOUD_PLATFORM_PASSWORD", "").strip()
    storage_state = os.getenv("GSCLOUD_PLATFORM_STORAGE_STATE", "").strip()
    if not username and not storage_state:
        raise SystemExit("请先设置 GSCLOUD_PLATFORM_USERNAME 或 GSCLOUD_PLATFORM_STORAGE_STATE。")
    account = commercial.upsert_platform_account(
        source_key="gscloud",
        username=username,
        password=password,
        label=os.getenv("GSCLOUD_PLATFORM_LABEL", "后台地理空间数据云账号"),
        daily_limit=int(os.getenv("GSCLOUD_PLATFORM_DAILY_LIMIT", "50") or 50),
        monthly_limit=int(os.getenv("GSCLOUD_PLATFORM_MONTHLY_LIMIT", "1000") or 1000),
        storage_state_path=storage_state,
    )
    print("平台账号已写入后台账号池：")
    print({k: account.get(k) for k in ["account_id", "source_key", "label", "username_preview", "daily_limit", "monthly_limit", "status"]})


if __name__ == "__main__":
    main()

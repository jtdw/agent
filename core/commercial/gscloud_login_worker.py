from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .service import CommercialService
from ..domestic_sources.gscloud_adapter import open_login_and_save_state


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="GSCloud login worker")
    parser.add_argument("--status-path", required=True)
    args = parser.parse_args()

    status_path = Path(args.status_path)
    manifest: dict[str, Any] = json.loads(status_path.read_text(encoding="utf-8"))
    current = dict(manifest)
    workdir = Path(status_path).parents[2]  # .../workdir/domestic_auth/login_jobs/<id>.json

    try:
        current.update({
            "state": "BROWSER_OPEN",
            "message": "浏览器已启动。请完成登录；系统会周期性保存 Cookie，等待时间结束后自动关闭窗口。",
            "updated_at": _now(),
        })
        _safe_write_json(status_path, current)

        result = open_login_and_save_state(
            workdir,
            current["state_path"],
            timeout_seconds=int(current.get("timeout_seconds") or 300),
            headless=bool(current.get("headless", False)),
            status_path=status_path,
        )

        service = CommercialService(workdir)
        subject_type = current.get("subject_type")
        subject_id = current.get("subject_id")
        saved_record: Any = None
        if subject_type == "platform_account":
            saved_record = service.set_platform_account_storage_state(subject_id, current["state_path"])
        elif subject_type == "customer":
            saved_record = service.set_user_credential_storage_state(subject_id, "gscloud", current["state_path"])

        current.update({
            "state": "COMPLETED",
            "message": "登录等待结束，Cookie/登录态已保存。",
            "result": result,
            "saved_record": saved_record,
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 0
    except Exception as exc:
        current.update({
            "state": "FAILED",
            "message": "登录窗口任务失败。",
            "error": str(exc),
            "updated_at": _now(),
            "finished_at": _now(),
        })
        _safe_write_json(status_path, current)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

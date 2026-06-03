from __future__ import annotations

import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any


HTML_ERROR_MARKERS = (
    "<html",
    "<!doctype html",
    "internal server error",
    "login",
    "登录",
    "error",
)


def inspect_storage_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {"ok": False, "reason": "missing_storage_state", "action": "relogin", "path": str(state_path)}
    if state_path.stat().st_size <= 0:
        return {"ok": False, "reason": "empty_storage_state", "action": "relogin", "path": str(state_path)}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": "invalid_storage_state_json", "action": "relogin", "path": str(state_path), "detail": str(exc)}

    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list) or not cookies:
        return {"ok": False, "reason": "no_cookies", "action": "relogin", "path": str(state_path)}

    gscloud = [c for c in cookies if "gscloud.cn" in str(c.get("domain") or "")]
    if not gscloud:
        return {"ok": False, "reason": "no_gscloud_cookie", "action": "relogin", "path": str(state_path), "cookie_count": len(cookies)}

    now = time.time()
    expiring = []
    valid = []
    for cookie in gscloud:
        expires = cookie.get("expires", -1)
        try:
            expires_f = float(expires)
        except Exception:
            expires_f = -1
        if expires_f <= 0 or expires_f > now:
            valid.append(cookie)
        else:
            expiring.append(cookie)
    if not valid:
        return {
            "ok": False,
            "reason": "expired_gscloud_cookies",
            "action": "relogin",
            "path": str(state_path),
            "gscloud_cookie_count": len(gscloud),
            "expired_cookie_count": len(expiring),
        }
    return {
        "ok": True,
        "reason": "storage_state_ready",
        "action": "continue",
        "path": str(state_path),
        "cookie_count": len(cookies),
        "gscloud_cookie_count": len(gscloud),
        "valid_gscloud_cookie_count": len(valid),
    }


def classify_gscloud_failure(error: str | Exception) -> dict[str, str]:
    text = str(error or "")
    lower = text.lower()
    if any(term in text for term in ("登录态", "Cookie", "storage_state", "重新登录")) or "login required" in lower:
        return {
            "code": "login_required",
            "title": "需要重新登录 GSCloud",
            "user_message": "当前地理空间数据云登录态不可用，请先重新登录或更新平台账号 Cookie。",
            "next_action": "relogin",
        }
    if "internal server error" in lower or "500" in lower:
        return {
            "code": "source_server_error",
            "title": "GSCloud 服务端返回错误",
            "user_message": "地理空间数据云当前页面返回服务端错误，建议稍后重试或换一个产品/时间条件。",
            "next_action": "retry_later",
        }
    if "timeout" in lower or "超时" in text or "未捕获到文件" in text:
        return {
            "code": "download_timeout",
            "title": "下载等待超时",
            "user_message": "已找到记录但下载没有在限定时间内开始，可能需要二次确认、权限不足或网站响应慢。",
            "next_action": "retry_or_manual",
        }
    if "未找到满足条件" in text or "未找到可用于验证" in text:
        return {
            "code": "no_matching_scene",
            "title": "没有匹配的可下载记录",
            "user_message": "当前时间、区域、云量或产品筛选条件过严，没有找到可下载记录。",
            "next_action": "relax_filters",
        }
    if "未找到可点击下载入口" in text or "下载按钮" in text:
        return {
            "code": "download_button_missing",
            "title": "没有定位到下载按钮",
            "user_message": "页面已加载记录，但下载按钮结构和当前识别规则不一致，需要更新选择器或人工确认页面。",
            "next_action": "inspect_page",
        }
    if "不存在" in text or "为空" in text or "html" in lower:
        return {
            "code": "invalid_download_file",
            "title": "下载文件无效",
            "user_message": "下载结果不是可用数据文件，可能是空文件、错误页或损坏压缩包。",
            "next_action": "retry",
        }
    return {
        "code": "unknown_error",
        "title": "下载失败",
        "user_message": text[:300] or "任务失败，但没有返回明确错误信息。",
        "next_action": "inspect_logs",
    }


def _looks_like_html_error(path: Path) -> bool:
    try:
        head = path.read_bytes()[:512].decode("utf-8", errors="ignore").lower()
    except Exception:
        return False
    return any(marker.lower() in head for marker in HTML_ERROR_MARKERS)


def validate_download_artifact(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise RuntimeError(f"下载文件不存在: {file_path}")
    size = file_path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"下载文件为空: {file_path}")
    if _looks_like_html_error(file_path):
        raise RuntimeError(f"下载文件疑似 HTML 错误页，不是有效数据文件: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix == ".zip":
        if not zipfile.is_zipfile(file_path):
            raise RuntimeError(f"下载压缩包损坏或不是 ZIP 文件: {file_path}")
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"下载压缩包中存在损坏文件: {bad}")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"下载压缩包无法打开: {file_path}: {exc}") from exc
    return {
        "ok": True,
        "path": str(file_path),
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 3),
        "suffix": suffix,
    }


def find_existing_scene_download(target_dir: str | Path, scene_id: str) -> Path | None:
    root = Path(target_dir)
    scene = str(scene_id or "").strip()
    if not root.exists() or not scene:
        return None
    safe_scene = re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+", "_", scene)
    patterns = [f"*{scene}*", f"*{safe_scene}*"]
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                validate_download_artifact(path)
                return path
            except Exception:
                continue
    return None


def resolve_download_region(prompt: str, region: str = "") -> dict[str, Any]:
    value = str(region or "").strip()
    text = str(prompt or "")
    if not value:
        for candidate in ("成都市", "成都", "四川省", "四川", "重庆市", "重庆", "云南省", "云南", "贵州省", "贵州", "闪电河流域", "闪电河"):
            if candidate in text:
                value = candidate
                break
    if not value or value in {"当前研究区", "研究区", "区域"}:
        return {
            "ok": False,
            "region": value,
            "reason": "missing_region",
            "message": "请补充下载区域，例如“成都”“四川省”或上传/选择工作区边界。",
            "next_action": "ask_region",
        }
    return {
        "ok": True,
        "region": value,
        "reason": "region_resolved",
        "message": f"已识别下载区域：{value}",
        "next_action": "continue",
    }

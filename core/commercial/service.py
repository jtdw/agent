from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import CommercialDB, future_days, json_dumps, json_loads, now_str
from core.download_status import DownloadJobStatus, decorate_job_record, failure_diagnostic
from .security import SecretBox, mask_secret, public_record


PLAN_PRESETS = {
    "free": {"own_daily_quota": 3, "platform_monthly_quota": 0, "days": 365},
    "basic": {"own_daily_quota": 20, "platform_monthly_quota": 0, "days": 365},
    "pro": {"own_daily_quota": 100, "platform_monthly_quota": 50, "days": 30},
    "team": {"own_daily_quota": 500, "platform_monthly_quota": 300, "days": 30},
}


@dataclass
class QuotaCheck:
    ok: bool
    reason: str = ""
    account_id: str = ""




PASSWORD_PBKDF2_ITERATIONS = 220_000


def _hash_password(password: str) -> str:
    password = str(password or "")
    if len(password) < 6:
        raise ValueError("密码至少需要 6 位。")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or not stored_hash.startswith("pbkdf2_sha256$"):
        return False
    try:
        _algo, iterations, salt, expected_hex = stored_hash.split("$", 3)
        digest = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected_hex)
    except Exception:
        return False


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except Exception:
            continue
    return None


def _future_minutes(minutes: int) -> str:
    return (datetime.now() + timedelta(minutes=max(1, int(minutes)))).strftime("%Y-%m-%d %H:%M:%S")


class CommercialService:
    def __init__(self, workdir: Path):
        self.workdir = self._shared_workdir(Path(workdir))
        self.db = CommercialDB(self.workdir)
        self.secret = SecretBox(self.workdir)

    @staticmethod
    def _shared_workdir(workdir: Path) -> Path:
        """Use one commercial database for all per-user workspaces."""
        path = Path(workdir)
        if path.parent.name == "users":
            return path.parent.parent
        if path.name == "anonymous":
            return path.parent
        return path

    def status(self) -> dict[str, Any]:
        users = self.db.fetch_one("SELECT COUNT(*) AS n FROM commercial_users") or {"n": 0}
        jobs = self.db.fetch_one("SELECT COUNT(*) AS n FROM download_jobs") or {"n": 0}
        active_platform = self.db.fetch_one("SELECT COUNT(*) AS n FROM platform_accounts WHERE status='active'") or {"n": 0}
        return {
            "db_path": str(self.db.db_path),
            "secret_key_source": self.secret.key_source,
            "users": users["n"],
            "jobs": jobs["n"],
            "active_platform_accounts": active_platform["n"],
            "plan_presets": PLAN_PRESETS,
        }

    def create_user(self, email: str, plan: str = "free", user_id: str = "") -> dict[str, Any]:
        email = str(email or "").strip().lower()
        if not email or "@" not in email:
            raise ValueError("请提供有效 email。")
        plan = plan if plan in PLAN_PRESETS else "free"
        preset = PLAN_PRESETS[plan]
        user_id = user_id.strip() or f"u_{uuid4().hex[:12]}"
        existing = self.db.fetch_one("SELECT * FROM commercial_users WHERE email=?", [email])
        ts = now_str()
        data = {
            "user_id": user_id,
            "email": email,
            "plan": plan,
            "plan_expires_at": future_days(int(preset["days"])),
            "own_daily_quota": int(preset["own_daily_quota"]),
            "platform_monthly_quota": int(preset["platform_monthly_quota"]),
            "platform_monthly_used": 0,
            "status": "active",
            "created_at": ts,
            "updated_at": ts,
        }
        if existing:
            self.db.update_dict(
                "commercial_users",
                {k: v for k, v in data.items() if k not in {"user_id", "email", "created_at"}},
                "email=?",
                [email],
            )
            return public_record(self.db.fetch_one("SELECT * FROM commercial_users WHERE email=?", [email]) or {})
        self.db.insert_dict("commercial_users", data)
        return public_record(data)

    def register_user(self, email: str, password: str, plan: str = "free", user_id: str = "") -> dict[str, Any]:
        """注册前端登录用户，并同步创建商业用户档案。

        注册用户默认是 BASIC 状态，只能使用“自己的地理空间数据云账号”模式；只有升级 PRO/TEAM 后
        获得 platform_monthly_quota，才允许调用平台账号池。
        """
        existing = self.db.fetch_one("SELECT * FROM commercial_users WHERE email=?", [str(email or "").strip().lower()])
        if existing:
            # 避免用户重新注册时把已付费套餐误降级为 free。
            return self.set_user_password(existing["user_id"], password)
        user = self.create_user(email=email, plan=plan, user_id=user_id)
        return self.set_user_password(user["user_id"], password)

    def set_user_password(self, user_id_or_email: str, password: str) -> dict[str, Any]:
        user = self.get_user(user_id_or_email)
        self.db.update_dict(
            "commercial_users",
            {
                "password_hash": _hash_password(password),
                "login_failed_count": 0,
                "locked_until": "",
                "updated_at": now_str(),
            },
            "user_id=?",
            [user["user_id"]],
        )
        return public_record(self.get_user(user["user_id"]))

    def authenticate_user(self, email: str, password: str, remember_days: int = 7) -> dict[str, Any]:
        key = str(email or "").strip().lower()
        row = self.db.fetch_one("SELECT * FROM commercial_users WHERE email=?", [key])
        if not row:
            raise ValueError("账号不存在，请先注册。")
        if row.get("status") != "active":
            raise ValueError(f"账号状态不可用: {row.get('status')}")
        locked_until = _parse_dt(row.get("locked_until"))
        if locked_until and locked_until > datetime.now():
            raise PermissionError(f"账号暂时锁定，请在 {row.get('locked_until')} 后再试。")
        stored_hash = str(row.get("password_hash") or "")
        if not stored_hash:
            raise ValueError("该账号尚未设置登录密码，请使用重置密码或重新注册。")
        if not _verify_password(password, stored_hash):
            failed = int(row.get("login_failed_count") or 0) + 1
            update = {"login_failed_count": failed, "updated_at": now_str()}
            if failed >= 5:
                update["locked_until"] = _future_minutes(15)
            self.db.update_dict("commercial_users", update, "user_id=?", [row["user_id"]])
            raise PermissionError("密码错误。连续错误 5 次会锁定 15 分钟。")
        token = secrets.token_urlsafe(32)
        session = {
            "session_id": f"sess_{uuid4().hex[:12]}",
            "user_id": row["user_id"],
            "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "expires_at": future_days(remember_days),
            "status": "active",
            "created_at": now_str(),
            "last_seen_at": now_str(),
        }
        self.db.insert_dict("login_sessions", session)
        self.db.update_dict(
            "commercial_users",
            {"last_login_at": now_str(), "login_failed_count": 0, "locked_until": "", "updated_at": now_str()},
            "user_id=?",
            [row["user_id"]],
        )
        user = public_record(self.get_user(row["user_id"]))
        return {"user": user, "session_id": session["session_id"], "session_token": token, "expires_at": session["expires_at"]}

    def validate_session(self, session_id: str, session_token: str) -> dict[str, Any]:
        """Validate a saved login session token and return the public user record.

        Web and desktop clients share the same commercial.db, so a session created
        by either frontend can be validated against the same user table. The raw
        token is never stored; only its SHA-256 hash is persisted.
        """
        session_id = str(session_id or "").strip()
        session_token = str(session_token or "").strip()
        if not session_id or not session_token:
            raise PermissionError("登录状态无效，请重新登录。")
        row = self.db.fetch_one("SELECT * FROM login_sessions WHERE session_id=?", [session_id])
        if not row or row.get("status") != "active":
            raise PermissionError("登录状态已失效，请重新登录。")
        expires_at = _parse_dt(row.get("expires_at"))
        if expires_at and expires_at < datetime.now():
            self.db.update_dict("login_sessions", {"status": "expired", "last_seen_at": now_str()}, "session_id=?", [session_id])
            raise PermissionError("登录状态已过期，请重新登录。")
        expected = str(row.get("token_hash") or "")
        actual = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise PermissionError("登录令牌校验失败，请重新登录。")
        self.db.update_dict("login_sessions", {"last_seen_at": now_str()}, "session_id=?", [session_id])
        return {"user": public_record(self.get_user(row["user_id"])), "session_id": session_id, "expires_at": row.get("expires_at")}

    def logout_session(self, session_id: str) -> dict[str, Any]:
        """Revoke a frontend login session."""
        session_id = str(session_id or "").strip()
        if session_id:
            self.db.update_dict("login_sessions", {"status": "revoked", "last_seen_at": now_str()}, "session_id=?", [session_id])
        return {"ok": True}

    def permission_summary(self, user_id_or_email: str) -> dict[str, Any]:
        user = self.get_user(user_id_or_email)
        platform_quota = int(user.get("platform_monthly_quota") or 0)
        platform_used = int(user.get("platform_monthly_used") or 0)
        return {
            "user": public_record(user),
            "own_account_enabled": True,
            "platform_account_enabled": platform_quota > platform_used,
            "platform_quota_remaining": max(0, platform_quota - platform_used),
            "rules": {
                "free": "普通用户可保存自己的地理空间数据云账号或登录态，由智能体代为下载；不消耗平台账号池。",
                "paid": "付费用户获得平台账号下载额度，可在任务中选择 account_mode=platform；平台账号明文不返回给用户。",
            },
        }

    def create_payment_order(
        self,
        user_id: str,
        plan: str = "pro",
        amount_cents: int = 2000,
        platform_quota: int | None = None,
        days: int = 30,
        provider: str = "mock",
        note: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        plan = plan if plan in PLAN_PRESETS else "pro"
        quota = int(platform_quota if platform_quota is not None else PLAN_PRESETS[plan]["platform_monthly_quota"])
        order = {
            "order_id": f"ord_{uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "plan": plan,
            "amount_cents": int(amount_cents),
            "currency": "CNY",
            "platform_quota": quota,
            "days": int(days),
            "provider": provider or "mock",
            "status": "pending",
            "external_order_id": "",
            "note": note,
            "created_at": now_str(),
            "paid_at": "",
        }
        self.db.insert_dict("payment_orders", order)
        return public_record(order)

    def complete_payment_order(self, order_id: str, external_order_id: str = "") -> dict[str, Any]:
        order = self.db.fetch_one("SELECT * FROM payment_orders WHERE order_id=?", [order_id])
        if not order:
            raise ValueError(f"支付订单不存在: {order_id}")
        if order.get("status") == "paid":
            return {"order": public_record(order), "user": public_record(self.get_user(order["user_id"]))}
        user = self.get_user(order["user_id"])
        plan = order.get("plan") if order.get("plan") in PLAN_PRESETS else "pro"
        preset = PLAN_PRESETS[plan]
        self.db.update_dict(
            "commercial_users",
            {
                "plan": plan,
                "plan_expires_at": future_days(int(order.get("days") or preset["days"])),
                "own_daily_quota": int(preset["own_daily_quota"]),
                "platform_monthly_quota": int(order.get("platform_quota") or preset["platform_monthly_quota"]),
                "platform_monthly_used": 0,
                "updated_at": now_str(),
            },
            "user_id=?",
            [user["user_id"]],
        )
        paid_at = now_str()
        ext = external_order_id or f"mock_{uuid4().hex[:10]}"
        self.db.update_dict(
            "payment_orders",
            {"status": "paid", "external_order_id": ext, "paid_at": paid_at},
            "order_id=?",
            [order_id],
        )
        payment = {
            "payment_id": f"pay_{uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "provider": order.get("provider") or "mock",
            "amount_cents": int(order.get("amount_cents") or 0),
            "currency": order.get("currency") or "CNY",
            "plan": plan,
            "platform_quota": int(order.get("platform_quota") or preset["platform_monthly_quota"]),
            "status": "paid",
            "external_order_id": ext,
            "note": order.get("note") or "",
            "created_at": paid_at,
        }
        self.db.insert_dict("payment_records", payment)
        return {
            "order": public_record(self.db.fetch_one("SELECT * FROM payment_orders WHERE order_id=?", [order_id]) or {}),
            "payment": public_record(payment),
            "user": public_record(self.get_user(user["user_id"])),
        }

    def simulate_payment(
        self,
        user_id: str,
        plan: str = "pro",
        amount_cents: int = 2000,
        platform_quota: int | None = None,
        days: int = 30,
        note: str = "模拟支付开通",
    ) -> dict[str, Any]:
        order = self.create_payment_order(
            user_id=user_id,
            plan=plan,
            amount_cents=amount_cents,
            platform_quota=platform_quota,
            days=days,
            provider="mock",
            note=note,
        )
        return self.complete_payment_order(order["order_id"])

    def list_payment_orders(self, user_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if user_id:
            user = self.get_user(user_id)
            rows = self.db.fetch_all("SELECT * FROM payment_orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?", [user["user_id"], int(limit)])
        else:
            rows = self.db.fetch_all("SELECT * FROM payment_orders ORDER BY created_at DESC LIMIT ?", [int(limit)])
        return [public_record(r) for r in rows]

    def list_payment_records(self, user_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if user_id:
            user = self.get_user(user_id)
            rows = self.db.fetch_all("SELECT * FROM payment_records WHERE user_id=? ORDER BY created_at DESC LIMIT ?", [user["user_id"], int(limit)])
        else:
            rows = self.db.fetch_all("SELECT * FROM payment_records ORDER BY created_at DESC LIMIT ?", [int(limit)])
        return [public_record(r) for r in rows]

    def grant_plan(self, user_id: str, plan: str = "pro", platform_quota: int | None = None, days: int = 30, amount_cents: int = 0, note: str = "") -> dict[str, Any]:
        user = self.get_user(user_id)
        plan = plan if plan in PLAN_PRESETS else "pro"
        preset = PLAN_PRESETS[plan]
        quota = int(platform_quota if platform_quota is not None else preset["platform_monthly_quota"])
        self.db.update_dict(
            "commercial_users",
            {
                "plan": plan,
                "plan_expires_at": future_days(days),
                "own_daily_quota": int(preset["own_daily_quota"]),
                "platform_monthly_quota": quota,
                "platform_monthly_used": 0,
                "updated_at": now_str(),
            },
            "user_id=?",
            [user["user_id"]],
        )
        payment = {
            "payment_id": f"pay_{uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "provider": "manual",
            "amount_cents": int(amount_cents),
            "currency": "CNY",
            "plan": plan,
            "platform_quota": quota,
            "status": "paid",
            "external_order_id": "",
            "note": note,
            "created_at": now_str(),
        }
        self.db.insert_dict("payment_records", payment)
        return {"user": self.get_user(user_id), "payment": payment}

    def get_user(self, user_id_or_email: str) -> dict[str, Any]:
        key = str(user_id_or_email or "").strip()
        row = self.db.fetch_one("SELECT * FROM commercial_users WHERE user_id=? OR email=?", [key, key.lower()])
        if not row:
            raise ValueError(f"用户不存在: {user_id_or_email}")
        if row.get("status") != "active":
            raise ValueError(f"用户状态不可用: {row.get('status')}")
        return row

    def list_users(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.fetch_all("SELECT * FROM commercial_users ORDER BY created_at DESC LIMIT ?", [int(limit)])
        return [public_record(r) for r in rows]

    def save_user_credential(self, user_id: str, source_key: str, username: str = "", password: str = "", storage_state_path: str = "") -> dict[str, Any]:
        user = self.get_user(user_id)
        cid = f"cred_{uuid4().hex[:12]}"
        ts = now_str()
        data = {
            "credential_id": cid,
            "user_id": user["user_id"],
            "source_key": str(source_key).strip().lower(),
            "credential_type": "username_password" if username or password else "storage_state",
            "encrypted_username": self.secret.encrypt(username),
            "encrypted_password": self.secret.encrypt(password),
            "storage_state_path": storage_state_path,
            "status": "active",
            "created_at": ts,
            "updated_at": ts,
        }
        existing = self.db.fetch_one(
            "SELECT * FROM source_credentials WHERE user_id=? AND source_key=? AND credential_type=?",
            [data["user_id"], data["source_key"], data["credential_type"]],
        )
        if existing:
            self.db.update_dict(
                "source_credentials",
                {k: v for k, v in data.items() if k not in {"credential_id", "user_id", "source_key", "credential_type", "created_at"}},
                "credential_id=?",
                [existing["credential_id"]],
            )
            data["credential_id"] = existing["credential_id"]
        else:
            self.db.insert_dict("source_credentials", data)
        return self._credential_public(data)

    def _credential_public(self, row: dict[str, Any]) -> dict[str, Any]:
        pub = public_record(row)
        username = self.secret.decrypt(row.get("encrypted_username")) if row.get("encrypted_username") else ""
        pub["username_preview"] = mask_secret(username)
        pub["has_password"] = bool(row.get("encrypted_password"))
        return pub

    def list_user_credentials(self, user_id: str) -> list[dict[str, Any]]:
        user = self.get_user(user_id)
        rows = self.db.fetch_all("SELECT * FROM source_credentials WHERE user_id=? ORDER BY updated_at DESC", [user["user_id"]])
        return [self._credential_public(r) for r in rows]

    def set_user_credential_storage_state(self, user_id: str, source_key: str, storage_state_path: str) -> dict[str, Any]:
        """保存或更新某个用户在某数据源的浏览器登录态路径。"""
        return self.save_user_credential(
            user_id=user_id,
            source_key=source_key,
            username="",
            password="",
            storage_state_path=str(storage_state_path),
        )

    def get_user_storage_state_path(self, user_id: str, source_key: str) -> str:
        user = self.get_user(user_id)
        row = self.db.fetch_one(
            """
            SELECT * FROM source_credentials
            WHERE user_id=? AND source_key=? AND status='active'
              AND storage_state_path IS NOT NULL AND storage_state_path!=''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [user["user_id"], source_key.strip().lower()],
        )
        return str(row.get("storage_state_path") or "") if row else ""

    def clear_user_storage_state(self, user_id: str, source_key: str) -> None:
        user = self.get_user(user_id)
        row = self.db.fetch_one(
            """
            SELECT * FROM source_credentials
            WHERE user_id=? AND source_key=? AND status='active'
              AND storage_state_path IS NOT NULL AND storage_state_path!=''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            [user["user_id"], source_key.strip().lower()],
        )
        if row and row.get("storage_state_path"):
            path = Path(str(row.get("storage_state_path")))
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        self.db.execute(
            """
            UPDATE source_credentials
            SET storage_state_path='', updated_at=?
            WHERE user_id=? AND source_key=?
            """,
            [now_str(), user["user_id"], source_key.strip().lower()],
        )

    def set_platform_account_storage_state(self, account_id: str, storage_state_path: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM platform_accounts WHERE account_id=?", [account_id])
        if not row:
            raise ValueError(f"平台账号不存在: {account_id}")
        self.db.update_dict(
            "platform_accounts",
            {"storage_state_path": str(storage_state_path), "updated_at": now_str()},
            "account_id=?",
            [account_id],
        )
        return self._platform_public(self.db.fetch_one("SELECT * FROM platform_accounts WHERE account_id=?", [account_id]) or {})

    def get_platform_account_private(self, account_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM platform_accounts WHERE account_id=?", [account_id])
        if not row:
            raise ValueError(f"平台账号不存在: {account_id}")
        row["username"] = self.secret.decrypt(row.get("encrypted_username")) if row.get("encrypted_username") else ""
        row["password"] = self.secret.decrypt(row.get("encrypted_password")) if row.get("encrypted_password") else ""
        return row

    def resolve_job_storage_state_path(self, job_id: str) -> str:
        """根据任务账号模式解析应使用的浏览器 storage_state。"""
        job = self.get_job(job_id)
        mode = str(job.get("account_mode") or "").lower()
        if mode in {"platform", "platform_account"}:
            account_id = job.get("account_id") or ""
            if not account_id:
                return ""
            account = self.db.fetch_one("SELECT * FROM platform_accounts WHERE account_id=?", [account_id])
            return str(account.get("storage_state_path") or "") if account else ""
        if mode in {"own", "user", "user_account", "manual_cookie"}:
            return self.get_user_storage_state_path(job.get("user_id", ""), job.get("source_key", ""))
        return ""

    def upsert_platform_account(self, source_key: str, username: str = "", password: str = "", label: str = "", daily_limit: int = 50, monthly_limit: int = 1000, storage_state_path: str = "") -> dict[str, Any]:
        """Create or update a backend platform account by (source_key, label).

        This is intended for server-side configuration via .env or an admin-only
        panel. It returns only masked/public fields and never exposes the stored
        password to normal users.
        """
        source_key = str(source_key or "").strip().lower()
        label = (label or f"{source_key}_account").strip()
        existing = self.db.fetch_one("SELECT * FROM platform_accounts WHERE source_key=? AND label=?", [source_key, label])
        if existing:
            update = {
                "daily_limit": int(daily_limit),
                "monthly_limit": int(monthly_limit),
                "status": "active",
                "updated_at": now_str(),
            }
            if username:
                update["encrypted_username"] = self.secret.encrypt(username)
            if password:
                update["encrypted_password"] = self.secret.encrypt(password)
            if storage_state_path:
                update["storage_state_path"] = str(storage_state_path)
            self.db.update_dict("platform_accounts", update, "account_id=?", [existing["account_id"]])
            return self._platform_public(self.db.fetch_one("SELECT * FROM platform_accounts WHERE account_id=?", [existing["account_id"]]) or {})
        return self.add_platform_account(
            source_key=source_key,
            username=username,
            password=password,
            label=label,
            daily_limit=daily_limit,
            monthly_limit=monthly_limit,
            storage_state_path=storage_state_path,
        )

    def add_platform_account(self, source_key: str, username: str = "", password: str = "", label: str = "", daily_limit: int = 50, monthly_limit: int = 1000, storage_state_path: str = "") -> dict[str, Any]:
        account_id = f"pa_{uuid4().hex[:12]}"
        ts = now_str()
        data = {
            "account_id": account_id,
            "source_key": str(source_key).strip().lower(),
            "label": label.strip() or f"{source_key}_account",
            "encrypted_username": self.secret.encrypt(username),
            "encrypted_password": self.secret.encrypt(password),
            "storage_state_path": storage_state_path,
            "daily_limit": int(daily_limit),
            "used_today": 0,
            "monthly_limit": int(monthly_limit),
            "used_month": 0,
            "status": "active",
            "last_used_at": "",
            "created_at": ts,
            "updated_at": ts,
        }
        self.db.insert_dict("platform_accounts", data)
        return self._platform_public(data)

    def _platform_public(self, row: dict[str, Any]) -> dict[str, Any]:
        pub = public_record(row)
        username = self.secret.decrypt(row.get("encrypted_username")) if row.get("encrypted_username") else ""
        pub["username_preview"] = mask_secret(username)
        pub["has_password"] = bool(row.get("encrypted_password"))
        return pub

    def list_platform_accounts(self, source_key: str = "", include_inactive: bool = False) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = []
        if source_key:
            where.append("source_key=?")
            params.append(source_key.strip().lower())
        if not include_inactive:
            where.append("status='active'")
        sql = "SELECT * FROM platform_accounts"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC"
        return [self._platform_public(r) for r in self.db.fetch_all(sql, params)]

    def _select_platform_account(self, source_key: str) -> QuotaCheck:
        row = self.db.fetch_one(
            """
            SELECT * FROM platform_accounts
            WHERE source_key=? AND status='active'
              AND used_today < daily_limit AND used_month < monthly_limit
            ORDER BY used_today ASC, used_month ASC, updated_at ASC
            LIMIT 1
            """,
            [source_key.strip().lower()],
        )
        if not row:
            return QuotaCheck(False, "没有可用的平台账号，或平台账号已达到限额。")
        return QuotaCheck(True, account_id=row["account_id"])

    def _check_user_quota(self, user: dict[str, Any], account_mode: str, source_key: str) -> QuotaCheck:
        if account_mode in {"own", "user", "user_account", "manual_cookie"}:
            return QuotaCheck(True)
        if account_mode in {"platform", "platform_account"}:
            if int(user.get("platform_monthly_quota") or 0) <= int(user.get("platform_monthly_used") or 0):
                return QuotaCheck(False, "用户平台账号下载额度不足，请先付费或提升套餐。")
            return self._select_platform_account(source_key)
        if account_mode in {"direct_url", "local_file"}:
            return QuotaCheck(True)
        return QuotaCheck(False, f"不支持的账号模式: {account_mode}")

    def submit_job(
        self,
        user_id: str,
        source_key: str,
        resource_type: str,
        region: str = "",
        start_date: str = "",
        end_date: str = "",
        account_mode: str = "own",
        request_text: str = "",
        direct_url: str = "",
        local_file_path: str = "",
        output_name: str = "",
    ) -> dict[str, Any]:
        user = self.get_user(user_id)
        source_key = source_key.strip().lower()
        account_mode = account_mode.strip().lower()
        check = self._check_user_quota(user, account_mode, source_key)
        if not check.ok:
            raise PermissionError(check.reason)
        ts = now_str()
        job_id = f"job_{uuid4().hex[:12]}"
        data = {
            "job_id": job_id,
            "user_id": user["user_id"],
            "source_key": source_key,
            "resource_type": resource_type.strip().lower() or "unknown",
            "region": region,
            "start_date": start_date,
            "end_date": end_date,
            "account_mode": account_mode,
            "account_id": check.account_id,
            "request_text": request_text,
            "direct_url": direct_url,
            "local_file_path": local_file_path,
            "output_name": output_name or f"{resource_type}_{region}".strip("_"),
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "result_json": "",
            "failure_diagnostic_json": "",
            "artifact_quality_json": "",
            "output_path": "",
            "zip_path": "",
            "error_message": "",
            "charged": 0,
            "quota_reserved": 0,
            "retried_from_job_id": "",
            "canceled_at": "",
            "created_at": ts,
            "updated_at": ts,
            "finished_at": "",
        }
        self.db.insert_dict("download_jobs", data)
        if account_mode in {"platform", "platform_account"}:
            self._reserve_platform_quota(job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM download_jobs WHERE job_id=?", [job_id])
        if not row:
            raise ValueError(f"任务不存在: {job_id}")
        return public_record(decorate_job_record(row, json_loads))

    def list_jobs(self, user_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        if user_id:
            user = self.get_user(user_id)
            rows = self.db.fetch_all("SELECT * FROM download_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", [user["user_id"], int(limit)])
        else:
            rows = self.db.fetch_all("SELECT * FROM download_jobs ORDER BY created_at DESC LIMIT ?", [int(limit)])
        out = []
        for r in rows:
            out.append(public_record(decorate_job_record(r, json_loads)))
        return out

    def write_audit_event(
        self,
        *,
        user_id: str = "",
        action: str,
        status: str = "ok",
        resource_type: str = "",
        resource_id: str = "",
        ip_address: str = "",
        user_agent: str = "",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": f"evt_{uuid4().hex[:12]}",
            "user_id": str(user_id or ""),
            "action": str(action or "").strip(),
            "status": str(status or "ok").strip(),
            "resource_type": str(resource_type or "").strip(),
            "resource_id": str(resource_id or "").strip(),
            "ip_address": str(ip_address or "").strip(),
            "user_agent": str(user_agent or "").strip()[:300],
            "detail_json": json_dumps(detail or {}),
            "created_at": now_str(),
        }
        if not event["action"]:
            raise ValueError("audit action is required")
        self.db.insert_dict("audit_events", event)
        return {**event, "detail": json_loads(event["detail_json"])}

    def list_audit_events(self, user_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if user_id:
            rows = self.db.fetch_all("SELECT * FROM audit_events WHERE user_id=? ORDER BY created_at DESC LIMIT ?", [user_id, int(limit)])
        else:
            rows = self.db.fetch_all("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", [int(limit)])
        for row in rows:
            row["detail"] = json_loads(row.get("detail_json")) or {}
        return rows

    def recover_interrupted_jobs(self) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT * FROM download_jobs WHERE status IN ('queued', 'running') ORDER BY updated_at ASC",
        )
        recovered: list[str] = []
        for job in rows:
            self._release_platform_reservation(job["job_id"], "release_interrupted_platform_download")
            self._update_job(
                job["job_id"],
                status="waiting_manual",
                progress=max(0, min(99, int(job.get("progress") or 0))),
                stage="service_restart_needs_retry",
                error_message="服务重启后检测到未完成任务，请点击重试继续。",
            )
            recovered.append(job["job_id"])
        if recovered:
            self.write_audit_event(
                action="download.recover_interrupted",
                status="ok",
                resource_type="download_job",
                detail={"job_ids": recovered, "count": len(recovered)},
            )
        return {"count": len(recovered), "job_ids": recovered}

    def delete_job(self, job_id: str, user_id: str = "") -> dict[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id:
            raise ValueError("请提供下载任务编号。")
        row = self.db.fetch_one("SELECT * FROM download_jobs WHERE job_id=?", [job_id])
        if not row:
            raise ValueError(f"任务不存在: {job_id}")
        if user_id:
            user = self.get_user(user_id)
            if row.get("user_id") != user["user_id"]:
                raise PermissionError("只能删除自己的下载任务记录。")
        if row.get("status") in {"queued", "running", "waiting_login", "waiting_manual"}:
            raise ValueError("任务仍在进行或等待处理，请先取消任务后再删除记录。")
        self.db.execute("DELETE FROM download_jobs WHERE job_id=?", [job_id])
        return {"ok": True, "deleted_job_id": job_id}

    def _update_job(self, job_id: str, **fields: Any) -> None:
        fields["updated_at"] = now_str()
        self.db.update_dict("download_jobs", fields, "job_id=?", [job_id])

    def _write_quota_ledger(self, user_id: str, job_id: str, change_value: int, quota_type: str, reason: str) -> None:
        self.db.insert_dict(
            "quota_ledger",
            {
                "ledger_id": f"ql_{uuid4().hex[:12]}",
                "user_id": user_id,
                "job_id": job_id,
                "change_value": int(change_value),
                "quota_type": quota_type,
                "reason": reason,
                "created_at": now_str(),
            },
        )

    def _reserve_platform_quota(self, job_id: str) -> None:
        job = self.db.fetch_one("SELECT * FROM download_jobs WHERE job_id=?", [job_id]) or {}
        if not job or job.get("quota_reserved") or job.get("charged"):
            return
        if job.get("account_mode") not in {"platform", "platform_account"}:
            return
        user = self.get_user(job["user_id"])
        if int(user.get("platform_monthly_quota") or 0) <= int(user.get("platform_monthly_used") or 0):
            raise PermissionError("用户平台账号下载额度不足，请先付费或提升套餐。")
        self.db.execute(
            "UPDATE commercial_users SET platform_monthly_used = platform_monthly_used + 1, updated_at=? WHERE user_id=?",
            [now_str(), job["user_id"]],
        )
        if job.get("account_id"):
            self.db.execute(
                "UPDATE platform_accounts SET used_today=used_today+1, used_month=used_month+1, last_used_at=?, updated_at=? WHERE account_id=?",
                [now_str(), now_str(), job["account_id"]],
            )
        self._update_job(job_id, quota_reserved=1)
        self._write_quota_ledger(job["user_id"], job_id, 1, "platform_monthly", "reserve_platform_download")

    def _release_platform_reservation(self, job_id: str, reason: str) -> None:
        job = self.db.fetch_one("SELECT * FROM download_jobs WHERE job_id=?", [job_id]) or {}
        if not job or not int(job.get("quota_reserved") or 0):
            return
        self.db.execute(
            """
            UPDATE commercial_users
            SET platform_monthly_used = CASE WHEN platform_monthly_used > 0 THEN platform_monthly_used - 1 ELSE 0 END,
                updated_at=?
            WHERE user_id=?
            """,
            [now_str(), job["user_id"]],
        )
        if job.get("account_id"):
            self.db.execute(
                """
                UPDATE platform_accounts
                SET used_today = CASE WHEN used_today > 0 THEN used_today - 1 ELSE 0 END,
                    used_month = CASE WHEN used_month > 0 THEN used_month - 1 ELSE 0 END,
                    updated_at=?
                WHERE account_id=?
                """,
                [now_str(), job["account_id"]],
            )
        self._update_job(job_id, quota_reserved=0)
        self._write_quota_ledger(job["user_id"], job_id, -1, "platform_monthly", reason)

    def _charge_success(self, job: dict[str, Any]) -> None:
        if job.get("charged"):
            return
        if job.get("account_mode") in {"platform", "platform_account"}:
            if not int(job.get("quota_reserved") or 0):
                self._reserve_platform_quota(job["job_id"])
            self._update_job(job["job_id"], charged=1, quota_reserved=0)
            self._write_quota_ledger(job["user_id"], job["job_id"], 0, "platform_monthly", "complete_reserved_platform_download")

    def _artifact_quality_for_result(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        from core.domestic_sources.gscloud_reliability import validate_map_ready_artifact

        keys = ("zip_path", "package_path", "downloaded_path", "output_path", "path")
        candidates: list[str] = []
        for key in keys:
            value = result.get(key)
            if isinstance(value, str) and value.strip() and value.strip() not in candidates:
                candidates.append(value.strip())
        quality: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                quality.append(validate_map_ready_artifact(candidate))
            except Exception as exc:
                quality.append({"ok": False, "path": str(candidate), "reason": "artifact_validation_failed", "detail": str(exc)})
        return quality

    def run_job_with_result(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        zip_path = result.get("zip_path") or result.get("package_path") or ""
        output_path = (
            result.get("final_output_path")
            or result.get("output_path")
            or result.get("path")
            or result.get("dataset_name")
            or result.get("downloaded_path")
            or ""
        )
        artifact_quality = result.get("artifact_quality") if isinstance(result.get("artifact_quality"), list) else self._artifact_quality_for_result(result)
        result["artifact_quality"] = artifact_quality
        if artifact_quality and any(item.get("ok") is False for item in artifact_quality if isinstance(item, dict)):
            message = next((str(item.get("detail") or item.get("reason") or "") for item in artifact_quality if isinstance(item, dict) and item.get("ok") is False), "Downloaded artifact validation failed")
            diagnostic = failure_diagnostic(message)
            self._release_platform_reservation(job_id, "release_invalid_artifact_platform_download")
            self._update_job(
                job_id,
                status="failed",
                progress=100,
                stage="artifact_validation_failed",
                result_json=json_dumps(result),
                artifact_quality_json=json_dumps(artifact_quality),
                failure_diagnostic_json=json_dumps(diagnostic),
                output_path=str(output_path or ""),
                zip_path=str(zip_path or ""),
                error_message=diagnostic["user_message"],
                finished_at=now_str(),
            )
            return self.get_job(job_id)
        self._update_job(
            job_id,
            status="completed",
            progress=100,
            stage="completed",
            result_json=json_dumps(result),
            artifact_quality_json=json_dumps(artifact_quality),
            failure_diagnostic_json="",
            output_path=str(output_path or ""),
            zip_path=str(zip_path or ""),
            error_message="",
            finished_at=now_str(),
        )
        self._charge_success(self.db.fetch_one("SELECT * FROM download_jobs WHERE job_id=?", [job_id]) or {})
        return self.get_job(job_id)

    def fail_job(self, job_id: str, error: str) -> dict[str, Any]:
        diagnostic = failure_diagnostic(error)
        self._release_platform_reservation(job_id, "release_failed_platform_download")
        self._update_job(
            job_id,
            status="failed",
            progress=100,
            stage="failed",
            error_message=str(error),
            failure_diagnostic_json=json_dumps(diagnostic),
            finished_at=now_str(),
        )
        return self.get_job(job_id)

    def cancel_job(self, job_id: str, user_id: str = "", reason: str = "") -> dict[str, Any]:
        job = self.get_job(job_id)
        if user_id:
            user = self.get_user(user_id)
            if job.get("user_id") != user["user_id"]:
                raise PermissionError("只能取消自己的下载任务。")
        if job.get("status") in {"completed", "failed", "canceled"}:
            raise ValueError(f"任务已结束，不能取消: {job.get('status')}")
        self._release_platform_reservation(job_id, "release_canceled_platform_download")
        self._update_job(
            job_id,
            status="canceled",
            progress=100,
            stage="canceled",
            error_message=reason or "用户取消任务。",
            canceled_at=now_str(),
            finished_at=now_str(),
        )
        return self.get_job(job_id)

    def retry_job(self, job_id: str, user_id: str = "") -> dict[str, Any]:
        job = self.get_job(job_id)
        if user_id:
            user = self.get_user(user_id)
            if job.get("user_id") != user["user_id"]:
                raise PermissionError("只能重试自己的下载任务。")
        if job.get("status") not in {"failed", "canceled", "waiting_login", "waiting_manual"}:
            raise ValueError(f"当前状态不能重试: {job.get('status')}")
        retry = self.submit_job(
            user_id=job.get("user_id", ""),
            source_key=job.get("source_key", ""),
            resource_type=job.get("resource_type", ""),
            region=job.get("region", "") or "",
            start_date=job.get("start_date", "") or "",
            end_date=job.get("end_date", "") or "",
            account_mode=job.get("account_mode", "") or "own",
            request_text=job.get("request_text", "") or "",
            direct_url=job.get("direct_url", "") or "",
            local_file_path=job.get("local_file_path", "") or "",
            output_name=job.get("output_name", "") or "",
        )
        self._update_job(retry["job_id"], retried_from_job_id=job_id)
        return self.get_job(retry["job_id"])

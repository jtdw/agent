from pathlib import Path
import json
import time

import core.config  # loads .env
from core.commercial.service import CommercialService
from core.commercial.login_jobs import start_gscloud_login_process

WORKDIR = Path("workspace")
ACCOUNT_ID = "pa_9932048a3afc"

service = CommercialService(WORKDIR)
account = service.get_platform_account_private(ACCOUNT_ID)

state_path = Path(account["storage_state_path"])
if not state_path.exists():
    raise FileNotFoundError(f"storage_state 不存在: {state_path}")

login_job = start_gscloud_login_process(
    workdir=WORKDIR,
    subject_type="platform_account",
    subject_id=ACCOUNT_ID,
    state_path=state_path,
    timeout_seconds=300,
    headless=False,
)

print(json.dumps(login_job, ensure_ascii=False, indent=2))

# 可选：简单轮询 5 次，看看状态有没有变化
status_path = Path(login_job["status_path"])
for _ in range(5):
    time.sleep(5)
    if status_path.exists():
        data = json.loads(status_path.read_text(encoding="utf-8"))
        print(json.dumps({
            "state": data.get("state"),
            "message": data.get("message"),
            "updated_at": data.get("updated_at"),
            "finished_at": data.get("finished_at"),
        }, ensure_ascii=False, indent=2))
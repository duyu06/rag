"""SEC-A 部署面探针之一：容器内「全新安装 + 冷启动」——空 data 卷、没跑过任何 CLI，只看登录腿的脸。

**为什么这两个脚本进仓库**（终审 D1：证据可复现性）。矩阵里有 6 行（SECA-01 / 03 / 04b / 14 /
18-deployment / 19）的部署面证据取自 Task 10e 的两份转录
（`.superpowers/sdd/SECURITY_A_PLAN/task-10e-fresh-boot.txt`、`task-10e-smoke-final.txt`），
而当时那两枚探针住在仓库外（`C:/tmp/seca10e/…`）、旧镜像随后被回收 ⇒ 转录无法从仓库复现。
本文件与 `sec_a_smoke_http.py` 是那两枚脚本的**受版本控制副本**，判据、打印的形状、字段名一字
未动，只改了一处：口令材料一律按 env 取，脚本里不留任何明文口令（口径同 `backend/app/cli.py`
的 `CREDENTIALS_PASSWORD`——变量名进脚本，明文由调用方一次性注入）。原地那两份是本次转录的
原始现场，**保留不删**。

怎么复现（终态镜像 3f14b3de77a4 当时的那一发；换镜像 id 即可对当前镜像复跑）：

    docker volume rm rag-seca-fresh
    docker compose run --rm --no-deps -T -i \\
        -v rag-seca-fresh:/app/data \\
        -e SEC_A_PROBE_PASSWORD "$SEC_A_PROBE_PASSWORD" \\
        backend python - < scripts/sec_a_fresh_boot_probe.py

这一枚要证的三格（§8.5 企业列那句「无行 ⇒ 任何登录统一失败，fail-closed、非 500」）：
已知用户名与未知用户名在**零凭据行**的库上拿到同一张脸、且都不是 500；`POST` 那一次表清单里
`user_credentials` 是 lifespan 建出来的（§20.6 的裁定），表在场而**行**不在场。

`SEC_A_PROBE_PASSWORD` 在这枚探针里**永远不会被拿去比对**——库里根本没有可校验的行，认证腿在
身份/凭据查找那一步就恒成本返回（§7.3）。它仍然按 env 取，是因为脚本面不该出现 `password="…"`
这种形状（SECA-20 那道门对 `scripts/` 收字面量 + env + 材料三枚面）。
"""
import json
import os
import sqlite3
import sys

DB = "/app/data/conversations.db"
KNOWN_USER = os.environ.get("SEC_A_PROBE_USER", "admin")
UNKNOWN_USER = "nosuchaccount"


def probe_password() -> str:
    """口令只从环境取，脚本里一个字都不留；缺席就当场退出，不静默换成任何默认值。"""
    value = os.environ.get("SEC_A_PROBE_PASSWORD")
    if not value:
        sys.exit("缺少 SEC_A_PROBE_PASSWORD：本脚本不写死口令（口径同 backend/app/cli.py）。"
                 "请用 `docker compose run -e SEC_A_PROBE_PASSWORD \"$SEC_A_PROBE_PASSWORD\"` 注入。")
    return value


def face():
    if not os.path.exists(DB):
        return {"db_file_present": False}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    tables = sorted(r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"))
    rows = None
    if "user_credentials" in tables:
        rows = con.execute("SELECT COUNT(*) FROM user_credentials").fetchone()[0]
    con.close()
    return {"db_file_present": True, "tables": tables, "credential_rows": rows}


print("cwd=%s" % os.getcwd())
print("CONVERSATION_DB_PATH=%r SECURITY_ENTERPRISE_MODE=%r"
      % (os.environ.get("CONVERSATION_DB_PATH"), os.environ.get("SECURITY_ENTERPRISE_MODE")))
print("PRE  " + json.dumps(face(), ensure_ascii=False))

from fastapi.testclient import TestClient
from app.main_agent import app  # 部署形态的那个 app 实例（Dockerfile CMD）

with TestClient(app, raise_server_exceptions=False) as client:
    body_a = {"username": KNOWN_USER, "password": probe_password()}
    body_b = {"username": UNKNOWN_USER, "password": probe_password()}
    r1 = client.post("/api/auth/login", json=body_a)
    r2 = client.post("/api/auth/login", json=body_b)
    print("STATUS_KNOWN_USER_WITHOUT_ROW=%d" % r1.status_code)
    print("STATUS_UNKNOWN_USER=%d" % r2.status_code)
    print("NOT_500=%s" % (r1.status_code != 500 and r2.status_code != 500))
    print("BODIES_IDENTICAL=%s" % (r1.content == r2.content))
    print("BODY=%s" % json.dumps(r1.json(), ensure_ascii=False))

print("POST " + json.dumps(face(), ensure_ascii=False))

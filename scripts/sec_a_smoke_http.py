"""SEC-A 部署面探针之二：四场景 compose smoke（终态镜像）——HTTP 面 + 结构事实。

进仓库的理由与出处见 `sec_a_fresh_boot_probe.py` 的模块 docstring（终审 D1：部署面证据必须能
从版本控制里复现）。本文件是 Task 10e 那一发的受版本控制副本，判据与打印形状一字未动，只改了
**凭据来源**：原脚本把口令写成字面量（它们本来就是规格 §2 那批已泄露的弱口令与测试诱饵），
副本里一律按 env 取，脚本不留明文（口径同 `backend/app/cli.py` 的 `CREDENTIALS_PASSWORD`）。

怎么复现（backend 起在 `http://localhost:8001` 的形态下）：

    $env:SEC_A_SMOKE_ADMIN_PASSWORD = "<admin 账号当前的口令：即规格 §2 盘点过的那枚已泄露弱口令>"
    $env:SEC_A_SMOKE_VIEWER_PASSWORD = "<viewer 账号的当前值>"
    $env:SEC_A_SMOKE_WRONG_PASSWORD = "<一枚够长的错口令>"
    $env:SEC_A_SMOKE_LOCK_PASSWORD = "<另一枚够长的错口令>"
    python scripts/sec_a_smoke_http.py

四格各证什么：S1 有身份且 `must_change=1` 的账号**能**登录并拿到 `password_change_required`
（§9.1 的登录面键集，也是"泄露明文在此之前仍能登录"这一格的事实来源）；S2 错口令与未知账号
是同一张脸（§8.5 / §9.1 冻结字面值）；S3 `must_change` 只挡数据面 403、不挡白名单腿；
S4 连错五次之后**正确口令也被同一张脸挡下**——四格落盘的都是状态码、键集合、字节数、sha1 与
布尔判定，没有任何响应体进仓库。
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("SEC_A_SMOKE_API", "http://localhost:8001")
ADMIN_USER = os.environ.get("SEC_A_SMOKE_ADMIN_USER", "admin")
VIEWER_USER = os.environ.get("SEC_A_SMOKE_VIEWER_USER", "viewer")


def required(env_var: str) -> str:
    """口令只从环境取，缺席就当场退出——脚本里不写死任何一枚，也不给默认值。"""
    value = os.environ.get(env_var)
    if not value:
        sys.exit("缺少 %s：本脚本不写死口令（口径同 backend/app/cli.py），请先按环境变量注入。"
                 % env_var)
    return value


ADMIN_LOGIN = {"username": ADMIN_USER, "password": required("SEC_A_SMOKE_ADMIN_PASSWORD")}
VIEWER_LOGIN = {"username": VIEWER_USER, "password": required("SEC_A_SMOKE_VIEWER_PASSWORD")}
WRONG = required("SEC_A_SMOKE_WRONG_PASSWORD")
LOCK_PROBE = required("SEC_A_SMOKE_LOCK_PASSWORD")


def post(path, payload, token=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def get(path, token):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def show(label, status, body):
    try:
        d = json.loads(body.decode("utf-8"))
    except Exception:
        d = {}
    print("%-34s http=%s bytes=%s sha1=%s" %
          (label, status, len(body), hashlib.sha1(body).hexdigest()[:12]))
    return d


print("== S1 登录（有身份、must_change=1 的账号）==")
s1, b1 = post("/api/auth/login", ADMIN_LOGIN)
d1 = show("POST /api/auth/login %s" % ADMIN_USER, s1, b1)
print("   top_keys =", sorted(d1.keys()))
print("   user_keys =", sorted(d1.get("user", {}).keys()))
print("   password_change_required =", d1.get("password_change_required"))
token = d1.get("access_token") or (sys.exit("S1 没有拿到 token，后面两格无从做起") or "")

print()
print("== S2 错口令 vs 未知账号（必须是同一张脸）==")
s2a, b2a = post("/api/auth/login", {"username": ADMIN_USER, "password": WRONG})
s2b, b2b = post("/api/auth/login", {"username": "nosuchaccount", "password": WRONG})
da = show("wrong password on %s" % ADMIN_USER, s2a, b2a)
show("unknown account", s2b, b2b)
print("   status_equal =", s2a == s2b)
print("   BODIES_IDENTICAL =", b2a == b2b)
print("   detail == §9.1 冻结字面值 =", da.get("detail") == "用户名或密码错误")

print()
print("== S3 must_change 的数据面阻断（S1 那枚 token）==")
s3a, b3a = get("/api/knowledge-bases", token)
d3a = show("GET /api/knowledge-bases", s3a, b3a)
print("   detail == 「当前账号需先修改口令」 =", d3a.get("detail") == "当前账号需先修改口令")
s3b, b3b = get("/api/auth/me", token)
d3b = show("GET /api/auth/me（白名单腿）", s3b, b3b)
print("   me_keys =", sorted(d3b.keys()))
print("   password_change_required =", d3b.get("password_change_required"))

print()
print("== S4 锁定：viewer 连错五次，再用正确口令 ==")
seq = []
for _ in range(5):
    code, _body = post("/api/auth/login", {"username": VIEWER_USER, "password": LOCK_PROBE})
    seq.append(code)
print("   five wrong =", seq)
s4, b4 = post("/api/auth/login", VIEWER_LOGIN)
d4 = show("   correct password while locked", s4, b4)
print("   locked face identical to the unified failure face =", b4 == b2a)
print("   detail == §9.1 冻结字面值 =", d4.get("detail") == "用户名或密码错误")
print("   响应体里没有「锁定」字样 =", "锁定" not in d4.get("detail", ""))

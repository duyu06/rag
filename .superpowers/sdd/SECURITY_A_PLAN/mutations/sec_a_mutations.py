"""SECA 变异台（Task 10 Step 4）：每一发都必须杀至少一条测试，否则那条测试是死代码。

跑法（仓库任意 cwd，路径按本文件位置解析）：

    python .superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py
    python .superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py M1 M6
    python .superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py --check

字节安全纪律（与 V2.3 同一条）：读字节 → `bytes.replace(old, new, 1)` → 写字节 → 跑定向
pytest → **`finally` 里写回原字节** → 核对 sha1 与注入前一致。核对不过就立刻中止整轮，
不把第二发行挂在自己树上的变异里。还原永远用读到的那份字节，**不从 git 取**。

比计划骨架多三条：
1. `L(...)` 逐行拼 needle（避免"隐式相邻字符串 + NL"写歪，那种写法会静默改语义）。
2. **anchor 必须恰好命中一次**（计划骨架只要求 ≥1）。一条有多解的 needle 就是"我以为在改 A，
   其实改到了 B"——那一行的红或绿都不能归因，所以命中 0 次报 `TARGET-NOT-FOUND`、命中多次
   报 `ANCHOR-NOT-UNIQUE`，两者都不动树。计划里 M4/M5/M7/M9/M16/M19 六枚 needle 有歧义，
   已按当时代码原文补上下文（逐条记在 `task-10b-report.md`），判据一字未改。
3. 支持**一发多处编辑**（M10/M16）：单点替换表达不出"bump 被拆进另一个事务"这种两行结构，
   而它正是 §13 那一行的原意。

needle 按**磁盘字节形态**写：`app/main.py` 整份 CRLF（实测 987 行 LF / 987 行 CRLF），
SEC-A 模块与测试文件是 LF。M5 那枚 needle 里的 `\r\n` 不是笔误。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"

# 宿主控制台默认 cp936，失败信息里的中文会先把打印炸掉（`finally` 已还原文件，但一份跑不完
# 的证据表等于没有证据）。这里只改本脚本自己的输出编码。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def L(*lines: str) -> str:
    """按 LF 拼一段多行 needle（每行末尾都带换行，所以末行也带）。"""
    return "".join(line + "\n" for line in lines)


CRLF = "\r\n"

# ---------------------------------------------------------------------------
# 19 发。每发：代号 / 规格判据 / 目标文件 / 编辑对 / 定向节点。
# 漂移理由写在紧邻的注释里，报告 §2 逐条抄录。
# ---------------------------------------------------------------------------

MUTATIONS: list[dict] = [
    # §13 M1「Argon2 换成 hashlib.sha256」⇒ SECA-01。
    # 计划 needle `    return _HASHER.hash(plain)`（4 空格）是磁盘上 8 空格那行的**后缀**：
    # 命中侥幸唯一，但那是巧合不是设计，按原文写全。`argon2_slot()` 那层留着——M1 攻的是
    # 原语，不是闸门；顺手把闸门拆了会把这一发和 Task 8 的容量那几发搅在一起。
    {
        "code": "M1",
        "seca": "SECA-01",
        "rel": "app/credentials.py",
        "edits": [(
            L("        return _HASHER.hash(plain)"),
            L("        return hashlib.sha256(plain.encode('utf-8')).hexdigest()"),
        )],
        "node": "tests/test_credentials_contract.py::Argon2ProfileTests",
    },
    # §13 M2「去掉 must_change 门」⇒ SECA-10。计划 needle 原文命中。
    {
        "code": "M2",
        "seca": "SECA-10",
        "rel": "app/auth.py",
        "edits": [(
            L("    if _password_change_required(user.username):"),
            L("    if False:"),
        )],
        "node": "tests/test_password_lifecycle_contract.py::SelfServiceChangeTests",
    },
    # §13 M3「require_user 不再比对 cv」⇒ SECA-09。
    # 计划 needle 是 Task 5 之前的**单条**合并条件；今天 `_user_from_token` 已拆成"类型闸 +
    # 版本闸"两条（bool/None 各自一臂，见 auth.py:435 与 :437）。M3 攻的是版本比对那一臂，
    # 于是重锚在版本闸上；类型闸留着，M17 才有它自己要压的那一臂。
    {
        "code": "M3",
        "seca": "SECA-09",
        "rel": "app/auth.py",
        "edits": [(
            L("    if claimed != record.credentials_version:"),
            L("    if False and claimed != record.credentials_version:"),
        )],
        "node": "tests/test_password_lifecycle_contract.py::TokenRevocationTests",
    },
    # §13 M4「未知账号早退（删哑校验）」⇒ SECA-13。
    # 计划 needle `credentials.verify_dummy(password)` 在 auth.py 命中**两次**（哑校验腿
    # :305 / legacy 口令错腿 :322），`replace(...,1)` 等于靠源码行序赌中哪一条。补上文钉死。
    {
        "code": "M4",
        "seca": "SECA-13",
        "rel": "app/auth.py",
        "edits": [(
            L("    if identity is None or not identity.enabled or record is None:",
              "        credentials.verify_dummy(password)"),
            L("    if identity is None or not identity.enabled or record is None:",
              "        pass"),
        )],
        "node": "tests/test_authentication_leg_contract.py::UnifiedFailureTests",
    },
    # §13 M5「锁定响应体带锁定字样」⇒ SECA-14。
    # 两处漂移：(a) 计划 needle 在 main.py 命中两次（登录腿 :342 / 改密腿 :407），补下一行
    # 做上下文钉到登录腿；(b) 替换体里的 `auth.AUDIT_LOGIN_LOCKED` 在 main.py **不可达**
    # （它只 `from app.auth import (...)`，没有 `import ... as auth`），照抄会 NameError→500，
    # 红是红了、红的是另一件事。token 改用字面量，值与常量逐字相同。
    {
        "code": "M5",
        "seca": "SECA-14",
        "rel": "app/main.py",
        "edits": [(
            '        raise HTTPException(status_code=401, detail="用户名或密码错误")' + CRLF
            + '    if result.audit_detail:' + CRLF,
            '        raise HTTPException(status_code=401, detail="用户名或密码错误"'
            ' if result.audit_detail != "AUTH_LOGIN_LOCKED" else "账号已锁定，请稍后再试")'
            + CRLF + '    if result.audit_detail:' + CRLF,
        )],
        "node": "tests/test_authentication_leg_contract.py::LockedHttpFaceTests",
    },
    # §13 M6「throttle 键去掉 client_ip」⇒ SECA-16a。计划 needle 原文命中。
    {
        "code": "M6",
        "seca": "SECA-16a",
        "rel": "app/login_throttle.py",
        "edits": [(
            L('    return f"{str(username).casefold()}|{client_ip}"'),
            L("    return str(username).casefold()"),
        )],
        "node": "tests/test_authentication_leg_contract.py::ThrottleLayerTests",
    },
    # §13 M7「lockout 计数键改按 ip」⇒ SECA-16b。
    # 计划的 needle（user_store `WHERE username = ?` 加 `locked_until IS NULL`）有两处漂移，
    # 第二处是要紧的那一条：
    #   (a) 那条 needle 在 user_store.py 命中 8 次 ⇒ 唯一性门直接 ANCHOR-NOT-UNIQUE；
    #   (b) 它攻的**不是** §13 那一行。给 `get_record` 加 `locked_until IS NULL` 是把"锁着的
    #       行"读成"没有行"，打在 SECA-14 的统一失败脸上；§13 的 M7 写的是"lockout **计数键**
    #       改按 ip"（SECA-16b），`ThrottleLayerTests` 自己的 docstring 也把这发指在同一格
    #       （"账号锁只看 username（M7 唯一可杀处）"）。按 §13 原文重锚到计数写入点：把
    #       `record_login_failure` 的键换成 (username, ip) 复合串 ⇒ 每个来源地址各一份计数、
    #       锁永不触发。SECA 行与被攻的性质一字未动。
    {
        "code": "M7",
        "seca": "SECA-16b",
        "rel": "app/auth.py",
        "edits": [(
            L("        user_store.record_login_failure(", "            username,"),
            L("        user_store.record_login_failure(",
              '            f"{username}|{client_ip}",'),
        )],
        "node": "tests/test_authentication_leg_contract.py::ThrottleLayerTests",
    },
    # §13 M8「redact 子串匹配 token」⇒ SECA-17（反误伤）。计划 needle 原文命中。
    {
        "code": "M8",
        "seca": "SECA-17",
        "rel": "app/security.py",
        "edits": [(
            L("                REDACTED if str(key).lower() in PERSISTENCE_SENSITIVE_KEYS"),
            L('                REDACTED if "token" in str(key).lower()'),
        )],
        "node": "tests/test_secret_hygiene_contract.py",
    },
    # §13 M9「redactor 作用域扩到 user_store」⇒ SECA-17 + SECA-03。
    # 计划 needle `    encoded = credentials.hash_password(plain_password)` 在 user_store.py
    # 命中 3 次（create_argon2 / set_password_argon2 / apply_rehash），计划注释自己写了
    # "只改第一处"——那是靠 replace 的次数参数赌行序。补函数首行 docstring 钉死 create_argon2。
    {
        "code": "M9",
        "seca": "SECA-17 + SECA-03",
        "rel": "app/user_store.py",
        "edits": [(
            L('    """唯一的新建口令入口。没有 algorithm 参数——legacy 因此不可达（SECA-01）。"""',
              "    encoded = credentials.hash_password(plain_password)"),
            L('    """唯一的新建口令入口。没有 algorithm 参数——legacy 因此不可达（SECA-01）。"""',
              '    encoded = "[REDACTED]"  # 模拟授权凭据库被通用 redactor 罩过'),
        )],
        "node": "tests/test_credentials_contract.py::UserStoreSchemaTests",
    },
    # §13 M10「cv bump 拆到 hash 之后的独立事务」⇒ SECA-11。两处编辑：A 把 bump 从
    # `_bump_and_clear` 那条 UPDATE 里摘出去；B 在 set_password 腿里以**第二个连接/事务**补上。
    # 计划的 needle（把 `def _bump_and_clear(` 改名）不是 §13 那一行：改名之后调用点抛
    # NameError、整条改密失败，恰恰**测不出**"新 hash 已提交而 cv 还是旧的"那一格窗口；
    # §13 的判据要的正是"这条窗口不许存在"。本发让提交序列真长成
    # [新 hash + 旧 cv 已提交] → [bump]，调用方交回的纪元与行里的纪元劈叉。
    {
        "code": "M10",
        "seca": "SECA-11",
        "rel": "app/user_store.py",
        "edits": [
            (
                L('        " credentials_version = credentials_version + 1, must_change = ?,"'),
                L('        " must_change = ?,"'),
            ),
            (
                L("        row = connection.execute(",
                  '            f"SELECT credentials_version FROM {TABLE_NAME} WHERE username = ?",',
                  "            (str(username),),",
                  "        ).fetchone()"),
                L("        row = connection.execute(",
                  '            f"SELECT credentials_version FROM {TABLE_NAME} WHERE username = ?",',
                  "            (str(username),),",
                  "        ).fetchone()",
                  "    with closing(_connect()) as connection, connection:",
                  "        connection.execute(",
                  '            f"UPDATE {TABLE_NAME} SET credentials_version'
                  ' = credentials_version + 1"',
                  '            " WHERE username = ?",',
                  "            (str(username),),",
                  "        )"),
            ),
        ],
        "node": "tests/test_credentials_contract.py::UserStoreTransactionTests",
    },
    # §13 M11「重置不清 lock 状态」⇒ SECA-12。计划 needle 原文命中。
    {
        "code": "M11",
        "seca": "SECA-12",
        "rel": "app/user_store.py",
        "edits": [(
            L('        " failed_attempts = 0, locked_until = NULL, updated_at = ?"'),
            L('        " updated_at = ?"'),
        )],
        "node": "tests/test_password_lifecycle_contract.py::AdminResetTests",
    },
    # §13 M12「身份文件 schema 放开 extra」⇒ SECA-07。计划 needle 原文命中。
    {
        "code": "M12",
        "seca": "SECA-07",
        "rel": "app/directory.py",
        "edits": [(
            L('    model_config = ConfigDict(extra="forbid")'),
            L('    model_config = ConfigDict(extra="ignore")'),
        )],
        "node": "tests/test_user_directory_contract.py",
    },
    # §13 M13「业务代码新增一处口令 hashlib」⇒ SECA-05。
    # 计划 needle `from app import credentials, directory, user_store` 在 Task 5 之后多了
    # `login_throttle` 一枚成员 ⇒ TARGET-NOT-FOUND。按现原文重锚，注入体与计划逐字同形。
    {
        "code": "M13",
        "seca": "SECA-05",
        "rel": "app/auth.py",
        "edits": [(
            L("from app import credentials, directory, login_throttle, user_store"),
            L("import hashlib",
              "from app import credentials, directory, login_throttle, user_store",
              "",
              "",
              "def _m13_probe(password: str) -> str:",
              '    return hashlib.sha256(password.encode("utf-8")).hexdigest()'),
        )],
        "node": "tests/test_credentials_contract.py::CentralisationScanTests",
    },
    # §13 M14「反向：重哈希写盘失败改为拒绝登录」⇒ SECA-21。
    # 计划 needle 只写了 `if forced and not wrote:` 与 `detail = AUDIT_REHASH_DEGRADED` 两行，
    # 中间今天夹了两行注释 ⇒ TARGET-NOT-FOUND。按原文补上注释行，替换体与计划一致。
    {
        "code": "M14",
        "seca": "SECA-21",
        "rel": "app/auth.py",
        "edits": [(
            L("        if forced and not wrote:",
              "            # 写盘失败 = 收敛延迟，不是安全放行：人已经进来了，legacy 行留着等下一次登录，",
              "            # 但这条事实必须以 token 出现（SECA-21）。",
              "            detail = AUDIT_REHASH_DEGRADED"),
            L("        if forced and not wrote:",
              "            return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)"),
        )],
        "node": "tests/test_authentication_leg_contract.py::LegacyUpgradeTests",
    },
    # §13 M15「把凭据材料写进 config/」⇒ SECA-07 + SECA-04 的三处扫描。计划 needle 原文命中。
    {
        "code": "M15",
        "seca": "SECA-07 / SECA-04 扫描面",
        "rel": "config/users.demo.json",
        "edits": [(
            '"username": "admin"',
            '"username": "admin", "password_hash": "a"',
        )],
        "node": "tests/test_user_directory_contract.py",
    },
    # §13 M16「m/t/p 改从 env 读取」⇒ SECA-19 / SEC-A-008。
    # 计划 needle 命中，但 credentials.py **没有 import os**（口令运算收拢后 hashlib/hmac/re
    # 三枚够用），照抄会在 import 期 NameError ⇒ 整个文件收集失败，红得不属于这一发。
    # 补第二处编辑把 import 装上，让这一发只多出一条 env 通道。
    {
        "code": "M16",
        "seca": "SECA-19 / SEC-A-008",
        "rel": "app/credentials.py",
        "edits": [
            (L("import hashlib", "import hmac"),
             L("import hashlib", "import hmac", "import os")),
            (L("ARGON2_MEMORY_COST = 19456"),
             L("ARGON2_MEMORY_COST = int(os.environ.get('ARGON2_MEMORY_COST', 19456))")),
        ],
        "node": "tests/test_credentials_contract.py::Argon2ProfileTests",
    },
    # §13 M17「cv 缺失即放行」⇒ SECA-09b。计划 needle 与 M3 同源（今天已拆成两条），而它的
    # 替换体 `if claimed is not None and claimed != ...` 是**写在单条旧条件上**的形状；按现
    # 结构重锚到取 claim 那一行之后：缺 claim ⇒ 借表里的当前版本，等价于 §13 那句
    # `if cv is None: allow()`（Task 6 台里那一发用的就是这个形状，逐字同源）。
    {
        "code": "M17",
        "seca": "SECA-09b",
        "rel": "app/auth.py",
        "edits": [(
            L("    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)"),
            L("    claimed = payload.get(CREDENTIAL_VERSION_CLAIM)",
              "    if claimed is None:",
              "        claimed = record.credentials_version"),
        )],
        "node": "tests/test_password_lifecycle_contract.py::TokenRevocationTests",
    },
    # §13 M18「身份合并改成 demo 静默覆盖」⇒ SECA-23。计划 needle 原文命中。
    {
        "code": "M18",
        "seca": "SECA-23",
        "rel": "app/directory.py",
        "edits": [(
            L("            if identity.username in merged:"),
            L("            if False:"),
        )],
        "node": "tests/test_user_directory_contract.py",
    },
    # §13 M19「全新安装缺凭据行时自动导入 legacy」⇒ SECA-04b。
    # 计划 needle 在 auth.py 命中**两次**（登录腿 :304 与令牌腿 :425 逐字相同），
    # `replace(...,1)` 又是在赌行序。补一行上下文钉到登录腿——M19 说的是登录腿上的
    # "缺行就顺手把升级工件读进来"，令牌腿那一格与 §8.2 无关。注入体与计划同形。
    {
        "code": "M19",
        "seca": "SECA-04b",
        "rel": "app/auth.py",
        "edits": [(
            L("    if identity is None or not identity.enabled or record is None:",
              "        credentials.verify_dummy(password)"),
            L("    if identity is None or not identity.enabled:",
              "        if record is None:",
              '            user_store.import_legacy_digest(username, "a" * 64, must_change=True)',
              "            record = user_store.get_record(username)",
              "        credentials.verify_dummy(password)"),
        )],
        "node": "tests/test_authentication_leg_contract.py::SourceRemovalTests",
    },
]


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def check_anchors() -> int:
    """只核 needle 命中次数、不动树、不跑测试——先把 19 发的锚点确认一遍。"""
    bad = 0
    for spec in MUTATIONS:
        path = BACKEND / spec["rel"]
        text = path.read_bytes().decode("utf-8")
        counts = [text.count(old) for old, _ in spec["edits"]]
        status = "OK" if all(c == 1 for c in counts) else "BAD"
        if status == "BAD":
            bad += 1
        print(f"{status}\t{spec['code']}\t{counts}\t{spec['rel']}")
    print(f"\n{len(MUTATIONS) - bad}/{len(MUTATIONS)} 锚点唯一")
    return 1 if bad else 0


def run_node(node: str) -> tuple[int, str]:
    """定向跑一发：只跑这一个节点。**不带 `-x`**（计划骨架带了）——那是取证精度的取舍：
    `-x` 首红即停，而"首红"取决于 unittest 的字母序，不是"哪条判据真的杀得掉这一发"。
    M6 第一次跑就死在 `_sweep_stale` 那条时钟用例上（桶键塌成一枚 ⇒ 表里只剩一格），
    SECA-16a 那条真判据反而没被读到。跑完整枚节点的成本只多几秒（固定开销在模块收集与
    会话级夹具上），换回来的是每条红判据各自留名。全文落在系统临时目录（不进仓库）。
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--tb=line", "-p", "no:cacheprovider"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    raw = (proc.stdout or "") + (proc.stderr or "")
    slug = node.replace("/", "_").replace("::", "_").replace(".py", "")
    Path(tempfile.gettempdir(), f"sec_a_mutation_{slug}.txt").write_text(raw, encoding="utf-8")
    return proc.returncode, raw


def failed_nodes(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            out.append(line.split(" - ")[0].split(" ", 1)[1])
    return out


def summarize(raw: str) -> str:
    for line in reversed(raw.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            return line.strip()
    return "(无摘要)"


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--check":
        return check_anchors()
    wanted = {a.upper() for a in argv}
    selected = [m for m in MUTATIONS if not wanted or m["code"] in wanted]
    if not selected:
        print(f"未选中任何变异：{argv}")
        return 2
    rows = []
    for spec in selected:
        code = spec["code"]
        path = BACKEND / spec["rel"]
        original = path.read_bytes()
        before = sha1(path)
        text = original.decode("utf-8")
        counts = [text.count(old) for old, _ in spec["edits"]]
        if any(c == 0 for c in counts):
            print(f"{code}\tTARGET-NOT-FOUND\tcounts={counts}\t树未动")
            rows.append((code, spec["seca"], "TARGET-NOT-FOUND", "", spec["node"], "n/a"))
            continue
        if any(c != 1 for c in counts):
            print(f"{code}\tANCHOR-NOT-UNIQUE\tcounts={counts}\t树未动")
            rows.append((code, spec["seca"], "ANCHOR-NOT-UNIQUE", "", spec["node"], "n/a"))
            continue
        mutated = text
        for old, new in spec["edits"]:
            mutated = mutated.replace(old, new, 1)
        assert mutated != text, f"{code} 注入是空操作"
        try:
            path.write_bytes(mutated.encode("utf-8"))
            print(f"[{code}] 注入 {spec['rel']} {before[:12]} -> {sha1(path)[:12]}", flush=True)
            rc, raw = run_node(spec["node"])
            print(f"[{code}] pytest: {summarize(raw)}", flush=True)
            red = failed_nodes(raw)
            for name in red[:8]:
                print(f"[{code}]   RED {name}")
            rows.append((code, spec["seca"], "KILLED" if rc != 0 else "SURVIVED",
                         ",".join(red[:3]) or "-", spec["node"], "OK"))
        finally:
            path.write_bytes(original)
            after = sha1(path)
            if after != before:
                # 还原不了就停下：把变异留在树上，比少一行证据严重得多。
                print(f"{code}\tRESTORE-FAILED\t{before} != {after}\t中止整轮", flush=True)
                raise SystemExit(3)
        print(f"[{code}] 还原后 sha1 相同 = True", flush=True)
    print()
    print("| 变异 | 判据 | 结果 | 红掉的节点 | 定向节点 | sha1 还原 |")
    print("| --- | --- | --- | --- | --- | --- |")
    for code, seca, verdict, red, node, restore in rows:
        print(f"| {code} | {seca} | {verdict} | {red} | {node} | {restore} |")
    bad = [r for r in rows if r[2] != "KILLED"]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} KILLED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

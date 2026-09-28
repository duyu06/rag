"""B0 变异台（Task 6 / B0-11）：每一发都必须杀至少一条门，否则那枚门是纸门。

跑法（仓库任意 cwd，路径按本文件位置解析）：

    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py
    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py N1 N4
    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py --check

字节安全（与 SEC-A 19 发、V2.3 同一规矩，四条都不许省）：读字节 → `bytes.replace(old, new, 1)`
→ 写字节 → 跑定向 pytest → **`finally` 里写回读到的那份原字节**（不从 git 取）→ 核对 sha1 与
注入前一致，不过就立刻中止整轮。锚点必须**恰好命中一次**：0 次报 `TARGET-NOT-FOUND`、>1 次报
`ANCHOR-NOT-UNIQUE`，两者都不动树——一条有多解的 needle 就是"我以为在改 A，其实改到了 B"，
那一行的红或绿都不能归因。

比 SEC-A 的骨架多六处（都是本台的宾语决定的，不是口味）：

1. **目标不止 `backend/`**：B0 的门钉在 CI 交付面上，所以四枚目标里两枚在仓库根
   （`.github/workflows/ci.yml` / `.gitattributes`）。路径一律 `REPO / rel`。
2. **needle 按磁盘字节形态写**：实测 ci.yml 是 147 枚 CRLF / 0 枚裸 LF ⇒ 三枚 ci.yml 的
   needle 用 `LC(...)` 拼 `\r\n`；conftest.py、门模块、`.gitattributes` 全是 LF ⇒ 用 `L(...)`。
   拿 `\n` 拼 ci.yml 的 needle 我第一次就撞过，结果是 `TARGET-NOT-FOUND`（0 命中），不是错改。
3. **还原除 sha1 外另核一次 `cmp`**：sha1 相同是"我算的两次一致"，`cmp` 是"外部工具逐字节
   比对读到的原件"。SEC-A Task 4 那一轮登记过 `git diff` 对未跟踪文件恒返 0 的假绿（D5），
   本台的 `.gitattributes` 与门模块**正是未跟踪件**，所以还原证明不沾 git。
4. **定向节点跑整枚门模块而不是单枚函数**：台的职责是"哪几枚门杀掉了这一发"，单枚节点答不了
   这个问题（一发杀两枚时第二枚不会被读到）。代价是每发约 32s（16 枚里有两枚要起收集子进程），
   八发共约 4 分钟——仍然**串行**跑，绝不并行：这一台同时只能有一枚变异在树上。
5. **判决归到"计划点名的那枚门"上**（Task 6 修复轮 2 的 I-2）。`rc != 0` 只对"整枚 16 门模块"
   说话，不对"这一发该由哪枚门杀掉"说话，所以它不是归因：修复轮 1 里 N6 报 `KILLED`，而它那枚
   计划钉住的门当时正**空判绿**——读数没错，含义是错的。现在每发都核 `nodes` 是否**全部**落在实测
   红面里：全落 ⇒ `KILLED-ASSIGNED`；有别的门红而计划门绿 ⇒ `KILLED-INCIDENTAL`（这是**这一发的
   失败**，整轮 rc 非 0）；rc 非 0 却一枚 `FAILED/ERROR` 都读不到 ⇒ `COLLECTION-BROKEN`（命令根本没
   跑到断言层，绝不能读成 KILLED）。计划门、实测红面、判决三样都进表格。
6. **逐发落盘按变异代号取key**（M-3）：pytest 全文落 `ent_b0_mutation_<代号>.txt`。修复轮 1 按
   节点名取 key，而八发的宾语都是同一枚门模块 ⇒ 八份读数盖进同一份文件，那轮为了找回 N1 的
   全文把它**重跑了一遍**。重跑不是取证：落盘的必须是当场的读数。

stdout/stderr 在 import 期就重钉成 UTF-8：宿主控制台是 cp936，失败信息里的中文断言会先把
**打印**炸掉，而那时 `finally` 已经还原了文件 ⇒ 留下的是一份跑不完的证据表，价值等于零。

N1 攻的是 conftest 的 `collect_ignore`——不是改名，而是"日常最容易发生的那种藏"。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def L(*lines: str) -> str:
    """按 LF 拼一段多行 needle（每行末尾都带换行，所以末行也带）。"""
    return "".join(line + "\n" for line in lines)


CRLF = "\r\n"


def LC(*lines: str) -> str:
    """按 **CRLF** 拼 needle：ci.yml 磁盘上是 147 枚 CRLF、0 枚裸 LF，只能用这一形。"""
    return "".join(line + CRLF for line in lines)


#: 门册所在节点。八发的判据全部落在这一枚模块里（规格 §6.1—§6.4），所以定向跑整模块。
GATE_MODULE = "tests/test_ci_gate_contract.py"

#: 四枚目标在**未变异**状态的 sha1，`--check` 拿它做"字节还原一致"的比对基准：不是"我记得没改"，
#: 是"树和开工那天同一份字节"。
#: 门模块那一枚在修复轮 2 重锚过（I-1）：`450484c09592…`（修复轮 1 之前的旧值，被 R20 的地板改动
#: 作废）→ `a0b9f37f32bb…`。重锚**不是**照抄磁盘现值，而是从
#: `snap-task6-fix1-post/test_ci_gate_contract.py` 取的，并与树上那份 `cmp` rc=0、sha1 逐字符相同
#: （`sha1 a0b9f37f32bbab9580023b230a79a206ad1e0cbf` / `sha256[:12] 699b0dfa8d9e` / 50994 字节 / CR 0）。
#: 为什么不锚"磁盘当前"：锚磁盘等于让"还原"这道证明跟着树一起漂，而 `--check` 长期 rc=1 又会被
#: 读成"预期的噪音"——那一族（假红→忽略）本仓库已经写过两张卡。地板本身是 R20 有罪判决的改动，
#: 新常数把"这轮之后树该长什么样"钉死，下一次合法改动仍会红、仍要重新标定。
BASELINE_SHA1 = {
    "backend/tests/conftest.py": "b0c5eee33ccdb49824405a10b8e282b4d52ab36d",
    ".github/workflows/ci.yml": "931846cba8575e2e994633abc39a48492c1ea029",
    ".gitattributes": "5738e2743ea768943e083cb1ff85fd9793ee7f57",
    "backend/tests/test_ci_gate_contract.py": "4bba148e804dcb81fe97ce7a632f649e9414e3e6",
}

# ---------------------------------------------------------------------------
# 八发。每发：代号 / 规格判据 / 目标 / 编辑对 / 计划点名的判据门（`nodes`，可以是两枚）。
# needle 的歧义消解逐条记在紧邻的注释里，报告 §2 抄录。
# ---------------------------------------------------------------------------

MUTATIONS: list[dict] = [
    # §6.1 收集数钉。**最容易发生的那种藏**：不改名、不加 skip/xfail，只在 conftest 里顺手
    # 加一行 `collect_ignore` —— 那枚模块从此不被收集，而 16 枚门里只有总数看得见。
    # 歧义消解：计划 needle `_GUARDED = False` 在 conftest.py 命中**两次**（模块级 :157 与会话
    # 夹具 finally 里那枚缩进的 :774），`replace(...,1)` 等于靠行序赌。补下一行 `_SESSION_GUARD`
    # 的原文 ⇒ 只剩模块级那一枚（:774 那枚缩进 8 空格且下一行是 `_CREDENTIAL_GUARD = None`）。
    {
        "code": "N1",
        "spec": "§6.1 收集数钉",
        "rel": "backend/tests/conftest.py",
        "edits": [(
            L("_GUARDED = False",
              '_SESSION_GUARD: "LedgerGuard | None" = None'),
            L("_GUARDED = False",
              'collect_ignore = ["test_web_security.py"]  # 变异台 N1：一行藏掉整枚模块',
              '_SESSION_GUARD: "LedgerGuard | None" = None'),
        )],
        "nodes": ["test_collected_count_matches_the_pinned_number"],
    },
    # §6.2 单 runner 钉。必须是**真的 step**，不能是注释：`_step_script()` 会把整行 `#` 注释
    # 剥掉，所以树上原本那句"原既有步 unittest discover 已删除"的注释杀不掉这枚门（这正是
    # I-1 那颗地雷的另一面）。ci.yml 是 CRLF ⇒ 用 LC。
    # 歧义消解：主门那两枚 step 行里，`run: python -m pytest backend/tests -q` 只出现一次，
    # 但计划要的是"插在 step 之前"，所以锚在 `- name:` 那一行上（含步名的整枚 step 抬头，
    # 唯一）；新 step 落在主门之前不影响顺序钉的四枚锚点相对次序。
    {
        "code": "N2",
        "spec": "§6.2 单 runner 钉",
        "rel": ".github/workflows/ci.yml",
        "edits": [(
            LC('      - name: "Run backend contract suite (single runner: pytest)"'),
            LC("      - run: python -m unittest discover -s backend/tests -p 'test_*.py' -v",
               '      - name: "Run backend contract suite (single runner: pytest)"'),
        )],
        "nodes": ["test_backend_contracts_has_no_unittest_discover_step"],
    },
    # §6.3 依赖同源钉：把"同源"换回 f6c67b5 那版的手写清单（远端当场 ModuleNotFoundError 的
    # 原形）。锚 `-r backend/requirements.txt` 在 ci.yml 命中 1 次（`hashFiles('backend/
    # requirements.txt')` 里那枚前面是引号不是 `-r `，不构成第二次命中）；为免读成人手抄的
    # 半行，needle 取整行 + CRLF。
    {
        "code": "N3",
        "spec": "§6.3 依赖同源钉",
        "rel": ".github/workflows/ci.yml",
        "edits": [(
            LC("          python -m pip install --disable-pip-version-check"
               " -r backend/requirements.txt"),
            LC("          python -m pip install --disable-pip-version-check"
               ' "fastapi>=0.115,<1" "pydantic>=2.8,<3" "python-multipart>=0.0.9"'
               ' "qdrant-client>=1.12,<2" "httpx>=0.27,<1" "PyJWT>=2.9,<3"'),
        )],
        "nodes": ["test_install_face_uses_requirements_txt_as_the_source"],
    },
    # §6.3 豁免表形状钉：多装一枚没豁免过的包（`bandit`）。锚取安装步最后一整行，
    # `--disable-pip-version-check pytest` 全文件唯一（SECA-20 那步是 `python -m pytest`，
    # 不含 `pip install`）。
    {
        "code": "N4",
        "spec": "§6.3 豁免表形状钉",
        "rel": ".github/workflows/ci.yml",
        "edits": [(
            LC("          python -m pip install --disable-pip-version-check pytest"),
            LC("          python -m pip install --disable-pip-version-check pytest",
               "          python -m pip install --disable-pip-version-check bandit"),
        )],
        "nodes": ["test_extra_pip_arguments_are_exactly_the_exemption_table"],
    },
    # §6.4 行尾钉：删 `*.sh text eol=lf` 整行（含其换行 ⇒ 行整体消失，不是留一枚空规则）。
    # `.gitattributes` 磁盘上是 LF、CR 字节 0（Task 4 §1 实测），所以用 L。锚在文件里唯一。
    {
        "code": "N5",
        "spec": "§6.4 行尾规则钉",
        "rel": ".gitattributes",
        "edits": [(
            L("*.sh text eol=lf"),
            "",
        )],
        "nodes": ["test_gitattributes_carries_the_required_rules"],
    },
    # §6.4 覆盖度钉的**空判角落**（Task 4 评审登记：这条钉原本没有非空地板）。两枚编辑一起才
    # 表达得出那一形——只收 tracked 一侧会得到 `313 == 0`，那是响亮地红，不是评审说的那一格；
    # 两侧同时收空才是 `0 == 0`、missing/extra 皆空、rows={} ⇒ 覆盖度钉放行。
    # 修复轮 1（R20）给地板补了 `assert tracked` / `assert parsed` 之后，这一发的**计划门就是两枚
    # 消费门本身**：两侧都红在地板上，兜底的 `i/-text` 枚举集合钉跟着一起红。改前那一份读数
    # （只红兜底、`i/crlf` 空判绿）留在报告 §3.6 与 F2 的对照表里，不抹。
    # 锚各命中 1 次（`_tracked_paths()` 的另一个调用点在门 16 里，那里是 `tracked = subprocess.
    # run(...)` 形状，不是同一串）。
    {
        "code": "N6",
        "spec": "§6.4 覆盖度钉的空判地板",
        "rel": "backend/tests/test_ci_gate_contract.py",
        "edits": [
            (
                L("    records = _index_eol_records()"),
                L('    records: "list[str]" = []  # 变异台 N6：index 面收空'),
            ),
            (
                L("    tracked = _tracked_paths()"),
                L('    tracked: "list[str]" = []  # 变异台 N6：跟踪面收空 ⇒ 覆盖度钉 0 == 0'),
            ),
        ],
        "nodes": ["test_index_has_no_crlf_entries",
                  "test_non_text_index_entries_are_exactly_the_enumerated_set"],
    },
    # §6.1 + 卡 H：改名一枚**门自己的** `def test_`（改函数名，不改文件名）。这一发补的是
    # M-1 指出的那一格：16 枚里有 4 枚从来没有被观测到红过，其中
    # `test_the_gate_module_itself_is_collected` 是自我存续钉、也就是 B0 整篇的论点本身，
    # 而它此前从未被真红过一次。Task 2 的注入 skip 实验已经证过"总数钉单独抓不到哑门"
    # （`--collect-only` 照打 node id），所以"改名会不会两枚一起红"必须由这一发来回答：
    # 总数钉应当从 1332 掉到 1331，自我存续钉应当从 16 枚实收变成 15 枚。
    # 宾语选 `test_backend_contracts_runs_the_pytest_suite`（门 6）——它不被任何别的门引用，
    # 改名不会牵连第二枚判据；`def test_…():` 整行在文件里唯一（`_OWN_TEST_NAMES` 里那枚是
    # 带引号的字符串、没有 `def ` 前缀）。改名后的函数必须以非 `test` 开头才真的脱离收集
    # （仓库无 pytest 配置文件 ⇒ `python_functions` 取默认 `test*`，前缀匹配）。
    {
        "code": "N7",
        "spec": "§6.1 总数钉 + 卡 H 自我存续钉（改名门自己）",
        "rel": "backend/tests/test_ci_gate_contract.py",
        "edits": [(
            L("def test_backend_contracts_runs_the_pytest_suite():"),
            L("def n7_renamed_away_from_test_prefix():"),
        )],
        "nodes": ["test_collected_count_matches_the_pinned_number",
                  "test_the_gate_module_itself_is_collected"],
    },
    # §6.3 豁免表的"为什么"地板（门 11）：把 `pytest` 那行的理由砍到 12 字符以下。
    # 这一枚门此前也没被观测到红过（M-1 的另一格）。它咬的是"豁免行写成占位符"那一形——
    # 豁免表是安装面唯一允许出现裸包名的地方，一条没有理由的豁免就等于一条没人负责的口子。
    # 宾语选 `pytest` 行的 why 字符串（整行在文件里唯一，`torch` 行的理由更长且跨两行，不选它）；
    # `count` 一字未动 ⇒ `test_extra_pip_arguments_are_exactly_the_exemption_table` 保持绿
    # （它是"N4 红而门 8 绿"的反向对照：形状没漂、理由漂了）。
    {
        "code": "N8",
        "spec": "§6.3 豁免行的『为什么』地板",
        "rel": "backend/tests/test_ci_gate_contract.py",
        "edits": [(
            L('    "pytest": (1, "测试运行器，不是应用运行时依赖。塞进 requirements.txt '
              '会让镜像为跑测试多背一包"),'),
            L('    "pytest": (1, "占位"),  # 变异台 N8：理由砍到地板以下'),
        )],
        "nodes": ["test_every_exemption_row_states_why"],
    },
]


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def anchor_counts(spec: dict) -> "list[int]":
    text = (REPO / spec["rel"]).read_bytes().decode("utf-8")
    return [text.count(old) for old, _ in spec["edits"]]


def compare_with_cmp(path: Path, original: bytes) -> "tuple[str, int]":
    """外部 `cmp` 逐字节比对（原件按**读到的字节**写到系统临时目录，不进仓库）。

    cmp 不在 PATH 上（纯 PowerShell 宿主）时退化成 Python 逐字节比，并在结果里写明用的是哪种，
    不把"没核"混进"核过"。
    """
    exe = shutil.which("cmp")
    if exe is None:
        return ("bytes-eq", 0 if path.read_bytes() == original else 1)
    tmp = Path(tempfile.mkdtemp(prefix="ent_b0_restore_")) / path.name
    tmp.write_bytes(original)
    try:
        proc = subprocess.run([exe, str(tmp), str(path)], capture_output=True)
        return ("cmp", proc.returncode)
    finally:
        tmp.unlink(missing_ok=True)
        os.rmdir(tmp.parent)


def check() -> int:
    """`--check`：什么都不跑、什么都不改，只核两件事——锚点仍各命中一次、四枚目标字节未残留。"""
    bad = 0
    print("== --check（不注入、不跑测试）==")
    for spec in MUTATIONS:
        counts = anchor_counts(spec)
        status = "ANCHOR-OK" if all(c == 1 for c in counts) else (
            "TARGET-NOT-FOUND" if 0 in counts else "ANCHOR-NOT-UNIQUE")
        if status != "ANCHOR-OK":
            bad += 1
        print(f"{status}\t{spec['code']}\tcounts={counts}\t{spec['rel']}")
    print()
    for rel, expected in sorted(BASELINE_SHA1.items()):
        path = REPO / rel
        actual = sha1(path) if path.is_file() else "MISSING"
        ok = actual == expected
        bad += 0 if ok else 1
        print(f"{'RESTORED-OK' if ok else 'RESTORED-MISMATCH'}\t{rel}\t{actual[:12]}"
              f"{' == ' + expected[:12] if ok else ' != ' + expected[:12]}")
    total = len(MUTATIONS) + len(BASELINE_SHA1)
    print(f"\n{total - bad}/{total} 项通过（锚点 {len(MUTATIONS)} 发 + 字节 {len(BASELINE_SHA1)} 枚）")
    return 1 if bad else 0


def run_node(node: str, code: str = "") -> "tuple[int, str]":
    """定向跑一枚节点：**不带 `-x`**（首红即停会把"哪几枚门真杀得掉这一发"读成"哪枚先红"，
    而 unittest/pytest 的序都不是判据）。全文落系统临时目录，不进仓库。

    落盘文件名按**变异代号**取 key（M-3）。修复轮 1 按节点名取 key，而八发的宾语都是同一枚门模块
    ⇒ 八份读数盖进同一份文件、只剩最后一份，那轮只能把 N1 重跑一遍才找回它的全文。
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
    slug = code or node.replace("/", "_").replace("::", "_").replace(".py", "")
    Path(tempfile.gettempdir(), f"ent_b0_mutation_{slug}.txt").write_text(raw, encoding="utf-8")
    return proc.returncode, raw


def failed_nodes(raw: str) -> "list[str]":
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


def gate_name(node_id: str) -> str:
    return node_id.split("::", 1)[1] if "::" in node_id else node_id


def decide(rc: int, red: "list[str]", assigned: "list[str]") -> "tuple[str, list[str]]":
    """把这一发的读数**归因**到计划钉住的那枚门上（I-2）。返回 `(判决, 没红的计划门)`。

    `rc != 0` 说的是"整枚 16 门模块红了"，不是"这发该杀的门红了"。这两个含义在修复轮 1 之前被
    当成同一个用，于是 N6 报 `KILLED` 而它计划钉住的那枚门当时正空判绿——仪表读错了自己的宾语。
    三种非理想态各有独立含义，不许混：

    * `SURVIVED`：rc=0，这发在树上什么门都没杀掉 ⇒ 那枚门是纸门。
    * `COLLECTION-BROKEN`：rc≠0 但一条 `FAILED/ERROR` 都读不到 ⇒ 命令没跑到断言层
      （解释器起不来、参数炸、收集期崩）。它连"哪枚门红"都没回答，因此**不是** KILLED。
    * `KILLED-INCIDENTAL`：别的门红了、计划钉住的那枚绿 ⇒ **这一发失败**（要么针打偏了，
      要么那枚门对这一形真的无感），整轮 rc 非 0，绝不许"顺手把期望改成红的那枚"。
    """
    hit = {gate_name(n) for n in red}
    missing = [name for name in assigned if name not in hit]
    if rc == 0:
        return "SURVIVED", missing
    if not red:
        return "COLLECTION-BROKEN", assigned
    return ("KILLED-ASSIGNED" if not missing else "KILLED-INCIDENTAL"), missing


#: 只有 KILLED-ASSIGNED 算这一发做成了；其余每一态都要把整轮的 rc 顶成非 0。
SUCCESS_VERDICT = "KILLED-ASSIGNED"


def explain(verdict: str, missing: "list[str]", rc: int) -> str:
    """判决不是 KILLED-ASSIGNED 时，把"到底哪儿没对上"写进表格——读数不该只剩一个词。"""
    if verdict == SUCCESS_VERDICT:
        return "-"
    if verdict == "KILLED-INCIDENTAL":
        return f"计划门未红：{missing} ⇒ 红的是别的门，这一发的归因不成立"
    if verdict == "COLLECTION-BROKEN":
        return f"rc={rc} 而红面为空 ⇒ 命令没跑到断言层（收集/启动炸了），不是 KILLED"
    return "rc=0 ⇒ 这一发在树上没杀掉任何门，那枚门是纸门"


def gate_roster() -> "list[str]":
    """门册：从门模块源码现读 `def test_…`，不另抄一份清单（抄的那份会漂，正是本台要抓的病）。

    用正则而不是"去掉行首 `def ` 再去掉行尾 `():`"——后者会把括号留在名字里，
    于是溯源表整列对不上号（修复轮 2 首跑就撞上：八发全 KILLED-ASSIGNED，表却全列 NEVER）。
    """
    text = (BACKEND / GATE_MODULE).read_bytes().decode("utf-8")
    return re.findall(r"^def (test_\w+)", text, re.MULTILINE)


def print_provenance(rows: "list[dict]", all_runs: bool) -> None:
    """门 × 本轮击杀者的溯源表（M-1 要的那张表的机器侧；跨任务的补量在报告里手工并表）。"""
    killed_by: "dict[str, list[str]]" = {}
    for row in rows:
        for name in row["red"]:
            killed_by.setdefault(name, []).append(row["code"])
    roster = gate_roster()
    print("== 门 × 本轮实测红面（击杀者溯源）==")
    for name in roster:
        codes = killed_by.get(name)
        print(f"{'RED  ' if codes else 'NEVER'}\t{name}\t"
              f"{','.join(codes) if codes else '（本轮未观测到红）'}")
    # 分母现算、不写死 16：写死的那枚数字会在门数变化时指着真读数说假话
    # （"16 枚里红了 9 枚"），而"常数落后于事实"正是本台八发要抓的病。
    tail = (f"{len(MUTATIONS)} 发全跑，NEVER 是真读数" if all_runs
            else "⚠ 本轮只跑了部分发，NEVER 不能读成那枚门没牙")
    print(f"\n{len(roster)} 枚门里本轮观测到红 "
          f"{len([n for n in roster if n in killed_by])} 枚；{tail}")


def main(argv: "list[str]") -> int:
    if argv and argv[0] == "--check":
        return check()
    wanted = {a.upper() for a in argv}
    selected = [m for m in MUTATIONS if not wanted or m["code"] in wanted]
    if not selected:
        print(f"未选中任何变异：{argv}")
        return 2
    rows = []
    for spec in selected:
        code = spec["code"]
        assigned = list(spec["nodes"])
        row = {"code": code, "spec": spec["spec"], "rel": spec["rel"],
               "anchors": "1 次/编辑", "assigned": ",".join(assigned) or "-",
               "red": [], "verdict": "-", "note": "-", "restore": "n/a"}
        path = REPO / spec["rel"]
        original = path.read_bytes()
        before = sha1(path)
        text = original.decode("utf-8")
        counts = [text.count(old) for old, _ in spec["edits"]]
        if any(c == 0 for c in counts):
            print(f"{code}\tTARGET-NOT-FOUND\tcounts={counts}\t树未动", flush=True)
            row.update(verdict="TARGET-NOT-FOUND", anchors=f"counts={counts}", note="树未动")
            rows.append(row)
            continue
        if any(c != 1 for c in counts):
            print(f"{code}\tANCHOR-NOT-UNIQUE\tcounts={counts}\t树未动", flush=True)
            row.update(verdict="ANCHOR-NOT-UNIQUE", anchors=f"counts={counts}", note="树未动")
            rows.append(row)
            continue
        mutated = text
        for old, new in spec["edits"]:
            mutated = mutated.replace(old, new, 1)
        assert mutated != text, f"{code} 注入是空操作"
        # 先入表再注入：`finally` 里的还原回填靠 rows[-1] 认"这一发那一行"，
        # 注入中途抛异常（比如磁盘写失败）时这一行还在，读到的就是半截证据而不是没有证据。
        rows.append(row)
        try:
            path.write_bytes(mutated.encode("utf-8"))
            print(f"[{code}] 注入 {spec['rel']} {before[:12]} -> {sha1(path)[:12]}"
                  f"（锚点唯一 {counts}）", flush=True)
            rc, raw = run_node(GATE_MODULE, code)
            print(f"[{code}] pytest（{GATE_MODULE} 全 16 枚）: {summarize(raw)}", flush=True)
            red = [gate_name(n) for n in failed_nodes(raw)]
            verdict, missing = decide(rc, red, assigned)
            for name in red:
                print(f"[{code}]   RED {name}")
            print(f"[{code}]   计划钉住 {assigned}")
            print(f"[{code}]   实测红面 {red if red else '（空）'}")
            print(f"[{code}]   判决 {verdict}"
                  + (f"（计划门里没红的：{missing}）" if missing and verdict != SUCCESS_VERDICT else ""),
                  flush=True)
            row.update(red=red, verdict=verdict, note=explain(verdict, missing, rc))
        finally:
            path.write_bytes(original)
            after = sha1(path)
            method, cmp_rc = compare_with_cmp(path, original)
            if after != before or cmp_rc != 0:
                # 还原不了就停下：把变异留在树上，比少一行证据严重得多。
                print(f"{code}\tRESTORE-FAILED\tsha1 {before} != {after}\t"
                      f"{method} rc={cmp_rc}\t中止整轮", flush=True)
                raise SystemExit(3)
            if rows and rows[-1]["code"] == code:
                # 只回填**这一发**那行（run_node 抛异常时判决还没写进表，不能错填到上一发上）。
                rows[-1]["restore"] = f"OK（sha1 同 + {method} rc=0）"
        print(f"[{code}] 还原：sha1 与注入前相同、{method} rc={cmp_rc}", flush=True)
    print()
    print("| 变异 | 规格判据 | 目标文件 | 锚点命中 | 计划钉住的门 | 实测红面 | 判决（归因） | 备注 | 还原 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['code']} | {row['spec']} | {row['rel']} | {row['anchors']} | {row['assigned']} "
              f"| {','.join(row['red']) or '-'} | **{row['verdict']}** | {row['note']} "
              f"| {row['restore']} |")
    bad = [r for r in rows if r["verdict"] != SUCCESS_VERDICT]
    print(f"\n{len(rows) - len(bad)}/{len(rows)} {SUCCESS_VERDICT}"
          + (f"；不成的一发：{[r['code'] for r in bad]}" if bad else ""))
    print()
    print_provenance(rows, len(rows) == len(MUTATIONS))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

## Task 2: 四枚门（红相：此时它们必须红）

**Files:**
- Create: `backend/tests/test_ci_gate_contract.py`
- Modify: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: Task 1 的量法（`NODE_ID` 正则与 `cwd=仓库根`/剥离 `REAL_LLM_ACCEPTANCE` 的子进程形态）；`.superpowers/sdd/ENTERPRISE_B0/baseline/collected-node-ids.txt`。
- Produces: `_job_steps(text, job) -> list[str]`、`_step_script(step) -> str`、`_index_eol_rows() -> dict[str, str]`、`EXPECTED_COLLECTED`、`PIP_INSTALL_EXEMPTIONS`、`REQUIRED_GITATTRIBUTES_RULES`、`ALLOWED_NON_TEXT_INDEX_ENTRIES`（Task 3/4 要让这些名字成立）。

- [ ] **Step 1: 写模块头与 helper（照 SEC-A 的门文件形态：docstring 先说清每枚门对哪次事故）**

```python
"""ENTERPRISE-B0 的门禁地基契约（规格 §6）。

这个文件守的四枚门，每一枚都对应 B0 事实基线里一次已经发生过的真实形状：

1. **收集数钉（§6.1 / F1）**——SEC-A 六枚门文件里的 40 枚裸 `pytest` 函数，CI 今天只用 pytest
   跑 5 枚，其余走一枚从原理上收不到裸函数的 `unittest` 步。"有测试步"和"测试被收集"是两件
   事，本枚门把后者变成可判定的：收集数必须等于钉住的常数。
2. **单 runner 钉（§6.2 / F1、F3）**——把 `unittest discover` 加回来是最"省事"的修法，而那
   正好让本文件自己变成纸门。所以禁第二 runner 必须是机器判据，不是口头约定。
3. **依赖同源钉（§6.3 / F2）**——`f6c67b5` 把扫描步接进 CI 时远端当场 `ModuleNotFoundError:
   httpx`，因为写进 YAML 的手写清单不等于本地实测那一包集合。本枚门要求安装面引用
   `backend/requirements.txt` 本身，并把豁免收窄成一张"表 + 处数 + 为什么"的形状（沿用
   SECA-20 扫描门的 EXEMPTIONS 设计，不另起一套）。
4. **行尾钉（§6.4 / F5）**——`core.autocrlf=true` 是**每台机器**的设置，不是仓库属性：index 侧
   实测 100% LF，工作树却 LF/CRLF/MIXED 三态并存。没有 `.gitattributes` 时，下一台
   `autocrlf=false` 的机器（Linux 默认）可以把 CRLF 字节写进 index。

自我存续子钉 `test_the_gate_module_itself_is_collected` 抓的是"门还在场但哑了"（被 skip、被
marker 摘空、常数被人凑）；它**抓不到**门自己被改名或删除，那是规格 §14 L6 登记的不可消除
自指盲区，别把它当已解决。
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TESTS_DIR = BACKEND_DIR / "tests"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITATTRIBUTES_FILE = REPO_ROOT / ".gitattributes"
BASELINE_NODE_IDS = (REPO_ROOT / ".superpowers" / "sdd" / "ENTERPRISE_B0_PLAN"
                     / "baseline" / "collected-node-ids.txt")

BACKEND = "backend-contracts"
```

- [ ] **Step 2: 写收集面 helper 与三枚收集钉**

```python
_NODE_ID = re.compile(r"^backend/tests/[^:]+::")
OWN_MODULE = "backend/tests/test_ci_gate_contract.py"


@functools.lru_cache(maxsize=1)
def _collected() -> tuple[str, ...]:
    """与 `scripts/b0_collection_probe.py` 同一量法：子进程、固定 cwd、剥掉验收开关。

    不在进程内用 unittest loader —— 那枚 loader 看不到裸函数（本规格 §2 的 45 枚差就是这么
    来的），用它当量法等于让门继承它要消灭的缺陷。
    """
    env = dict(os.environ)
    env.pop("REAL_LLM_ACCEPTANCE", None)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q", "--collect-only"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False)
    assert child.returncode == 0, (
        f"收集子进程 rc={child.returncode}；门的判据不建立在"
        f"『收不动就算过』上\n{child.stdout[-2000:]}\n{child.stderr[-2000:]}")
    return tuple(line.strip() for line in child.stdout.splitlines() if _NODE_ID.match(line.strip()))


def _per_module(ids: list[str]) -> "dict[str, int]":
    out: "dict[str, int]" = {}
    for node_id in ids:
        module = node_id.split("::", 1)[0]
        out[module] = out.get(module, 0) + 1
    return out


# 常数在 Step 5 按实测回写：1316 是 Task 1 的基线，本文件自己还要贡献 13 枚。
EXPECTED_COLLECTED = 1329


def test_collected_count_matches_the_pinned_number():
    ids = list(_collected())
    if len(ids) == EXPECTED_COLLECTED:
        return
    baseline = ([line.strip() for line in BASELINE_NODE_IDS.read_text(encoding="utf-8").splitlines()
                 if line.strip()] if BASELINE_NODE_IDS.is_file() else [])
    # `.superpowers/` 是 gitignored ⇒ **CI 里这枚明细基线根本不存在**。所以它只能用来把失败信息
    # 写得能看，绝不能进判据：判据只有"实收 == 常数"这一条，基线缺席时红照样红、只是少一份差集。
    lost = sorted(set(baseline) - set(ids))
    gained = sorted(set(ids) - set(baseline))
    raise AssertionError(
        f"收集数 {len(ids)} ≠ 钉住的 {EXPECTED_COLLECTED}。\n"
        f"消失 {len(lost)} 枚：{lost[:15]}\n新增 {len(gained)} 枚：{gained[:15]}\n"
        f"逐模块计数：{_per_module(ids)}")


def test_the_gate_module_itself_is_collected():
    """自我存续：不依赖总数，只盯"本文件贡献了几枚"。凑总数、加 skip 都会在这里红。"""
    mine = [node_id for node_id in _collected() if node_id.startswith(f"{OWN_MODULE}::")]
    assert sorted(mine) == sorted(
        f"{OWN_MODULE}::{name}" for name in _OWN_TEST_NAMES), (
        f"门自己被摘了或哑了：本文件应有 {len(_OWN_TEST_NAMES)} 枚，实收 {len(mine)} 枚")


def test_collection_measurement_counts_node_ids_not_the_summary_line():
    """解析器自己是判据的一部分：它必须能认出「尾行文句不算一枚」。

    真实形状来自 §2：`Ran N tests` 里那 20 枚差是 subTest 中断，不是收集差异。
    """
    sample = "\n".join([
        "backend/tests/test_ci_gate_contract.py::test_a",
        "backend/tests/test_ci_gate_contract.py::TestB::test_c",
        "",
        "2 tests collected in 0.01s",
    ])
    assert sum(1 for line in sample.splitlines() if _NODE_ID.match(line.strip())) == 2
```

- [ ] **Step 3: 写 ci.yml 解析 helper 与三枚 runner 钉**

```python
def _ci_text() -> str:
    return CI_FILE.read_text(encoding="utf-8")


_JOB_HEAD = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def _job_block(text: str, job: str) -> str:
    """按两空格缩进的 job 头切块。认名字，不认行号（§2 的"行号不可信"教训）。"""
    keep: "list[str]" = []
    inside = False
    for line in text.splitlines(keepends=True):
        head = _JOB_HEAD.match(line)
        if head:
            inside = head.group(1) == job
            continue
        if inside:
            keep.append(line)
    return "".join(keep)


_STEP_HEAD = re.compile(r"^      - ", re.MULTILINE)


def _job_steps(text: str, job: str) -> "list[str]":
    """每个 step 一段原文。step 内多行/折叠标量都归进同一段 ⇒ 判据只看正文里出现/没出现什么。"""
    block = _job_block(text, job)
    if not block:
        raise AssertionError(f"ci.yml 里没有 job `{job}`：门不能对『找不到』保持沉默")
    cuts = [m.start() for m in _STEP_HEAD.finditer(block)]
    if not cuts:
        raise AssertionError(f"job `{job}` 里没有 step")
    cuts.append(len(block))
    return [block[a:b] for a, b in zip(cuts, cuts[1:])]


def _test_runs(text: str, job: str) -> "list[str]":
    return [step for step in _job_steps(text, job) if "run:" in step]


def test_backend_contracts_has_no_unittest_discover_step():
    runs = _test_runs(_ci_text(), BACKEND)
    offenders = [step for step in runs if "unittest discover" in step]
    assert not offenders, (
        f"F1 复活：`backend-contracts` 里又出现 unittest 收集（{len(offenders)} 处）。"
        f"裸 pytest 函数枚枚不收，而 job 可以是绿的")


def test_backend_contracts_runs_the_pytest_suite():
    """必须是"跑整个目录"的那一步，不是 SECA-20 那种跑单文件的子集。

    `(?!/)` 是这枚门的实质：只写 `"python -m pytest backend/tests" in step` 的话，
    SECA-20 那步（`backend/tests/test_secret_hygiene_contract.py`）子串命中 ⇒ 门在改造前就绿，
    而它要防的"主门被删掉"永远抓不到。
    """
    runs = _test_runs(_ci_text(), BACKEND)
    suite_wide = [step for step in runs
                  if re.search(r"python -m pytest backend/tests(?!/)", step)]
    assert suite_wide, (
        "主门不跑全量套件：B0-01 的收集数钉必须由这一步实际执行，而不是只写在文档里。"
        "注意 SECA-20 那枚单文件子集不算——它只跑 5 枚")


def test_step_ordering_still_explains_itself():
    """顺序的两条理由（§5.2）要用文字留在树上：它俩是"为什么不顺手挪一步"的唯一长期答案。"""
    block = _job_block(_ci_text(), BACKEND)
    assert "SECA-20" in block and "unittest" in block, (
        "ci.yml 里解释扫描步为何排在主门之前的注释被删了：那正是 f6c67b5 那轮踩过的地方")
```

- [ ] **Step 4: 写依赖同源钉（含豁免表）**

```python
#: 除 requirements.txt 之外允许出现的 pip 参数 → (处数, 为什么它是豁免而不是偷懒)。
#: 形状沿用 SECA-20 扫描门的 `EXEMPTIONS`：键不含行号，处数是计数，多一处少一处都红。
PIP_INSTALL_EXEMPTIONS: "dict[str, tuple[int, str]]" = {
    "pytest": (1, "测试运行器，不是应用运行时依赖。塞进 requirements.txt 会让镜像为跑测试多背一包"),
    "torch": (1, "不是新增依赖：sentence-transformers 的传递依赖就在 requirements.txt 里。"
                "这一行只选 CPU 发行源（~200MB 而不是默认那个带 CUDA 的 ~2.5GB）"),
}


def _install_steps(text: str, job: str) -> "list[str]":
    return [step for step in _test_runs(text, job) if "pip install" in step]


def test_install_face_uses_requirements_txt_as_the_source():
    steps = _install_steps(_ci_text(), BACKEND)
    assert steps, "`backend-contracts` 没有任何安装步"
    assert any("-r backend/requirements.txt" in step for step in steps), (
        "依赖又变成 YAML 里的手写清单：`f6c67b5` 的远端 ModuleNotFoundError 就是这么来的")


def _pip_package_tokens(step_texts: "list[str]") -> "list[str]":
    """只取 `pip install` 之后的**包名** token。

    绝不拿整段 step 文本去 tokenize：那会把 YAML 注释里的中文词、`sentence-transformers`、
    `-r backend/requirements.txt` 里的 `requirements.txt` 全算成"未豁免参数"，门一落地就假红。
    带值选项（`-r` / `--index-url`）连值一起跳；含 `/` 的是路径不是包名。
    """
    takes_value = {"-r", "--requirement", "--index-url", "--extra-index-url", "-i", "-f", "--find-links"}
    out: "list[str]" = []
    for text in step_texts:
        for line in text.splitlines():
            body = line.split("#", 1)[0]          # 注释先整段丢掉
            if "pip install" not in body:
                continue
            skip_next = False
            for raw in body.split("pip install", 1)[1].split():
                token = raw.strip("\"'")
                if skip_next:
                    skip_next = False
                    continue
                if token.startswith("-"):
                    skip_next = token in takes_value and "=" not in token
                    continue
                if "/" in token or token.endswith(".txt"):
                    continue
                out.append(token)
    return out


def test_extra_pip_arguments_are_exactly_the_exemption_table():
    """三个方向都算违规（与 SECA-20 的 `_gate_offenders` 同判据）：多出来的、处数不等、死行。"""
    seen: "dict[str, int]" = {}
    for token in _pip_package_tokens(_install_steps(_ci_text(), BACKEND)):
        seen[token] = seen.get(token, 0) + 1
    offenders: "list[str]" = []
    for token, count in sorted(seen.items()):
        row = PIP_INSTALL_EXEMPTIONS.get(token)
        if row is None:
            offenders.append(f"未豁免的包 `{token}` ×{count}")
        elif count != row[0]:
            offenders.append(f"`{token}` ×{count} ≠ 豁免表 {row[0]} 处")
    offenders += [f"豁免表死行：`{token}` 当前 0 处"
                  for token in sorted(set(PIP_INSTALL_EXEMPTIONS) - set(seen))]
    assert not offenders, "安装面漂移：" + "；".join(offenders)


def test_every_exemption_row_states_why():
    for token, (count, why) in PIP_INSTALL_EXEMPTIONS.items():
        assert count >= 1, token
        assert len(why) >= 12, f"豁免行 `{token}` 的『为什么』短到不像是理由，像是占位"
```

- [ ] **Step 5: 写行尾四枚钉，并把 `EXPECTED_COLLECTED` 按实测回写**

```python
REQUIRED_GITATTRIBUTES_RULES = (
    "* text=auto",
    "*.sh text eol=lf",
    "*.ps1 text eol=crlf",
)
REQUIRED_BINARY_RULES = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.ico",
                         "*.gif", "*.woff", "*.woff2")
#: `i/-text` 的合法集合。两枚 markdown 是被 git 判成非文本的**已知状态**（含 140 / 1 个游离 CR），
#: 规格 §7 明确不在 B0 强转它们；把它写成"恰好这三枚"，才既不会静默扩多、也不会静默消失。
ALLOWED_NON_TEXT_INDEX_ENTRIES = frozenset({
    ".superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md",
    "docs/MODEL_ROUTER_V23_DESIGN.md",
    "frontend/public/yaoke-logo.webp",
})
_EOL_LINE = re.compile(r"^(i/\S+)\s+(w/\S+)\s+(attr/\S*)\s*\t(.+)$")


def _index_eol_rows() -> "dict[str, str]":
    out: "dict[str, str]" = {}
    for line in subprocess.run(["git", "ls-files", "--eol"], cwd=REPO_ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", check=True).stdout.splitlines():
        row = _EOL_LINE.match(line.strip())
        if row:
            out[row.group(4)] = row.group(1)
    return out


def test_gitattributes_carries_the_required_rules():
    assert GITATTRIBUTES_FILE.is_file(), "没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定"
    rules = {line.strip() for line in GITATTRIBUTES_FILE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")}
    missing = [rule for rule in REQUIRED_GITATTRIBUTES_RULES if rule not in rules]
    assert not missing, f".gitattributes 缺必需规则：{missing}"
    binary = {rule.split()[0] for rule in rules if rule.endswith("binary")}
    assert set(REQUIRED_BINARY_RULES) <= binary, f"二进制扩展名没显式声明：{set(REQUIRED_BINARY_RULES) - binary}"


def test_index_has_no_crlf_entries():
    rows = _index_eol_rows()
    offenders = sorted(path for path, index_eol in rows.items() if index_eol == "i/crlf")
    assert not offenders, f"{len(offenders)} 枚文件的 CRLF 被提交进了 index（整文件 diff 的形状）：{offenders[:10]}"


def test_non_text_index_entries_are_exactly_the_enumerated_set():
    rows = _index_eol_rows()
    found = {path for path, index_eol in rows.items() if index_eol == "i/-text"}
    assert found == set(ALLOWED_NON_TEXT_INDEX_ENTRIES), (
        f"非文本形态漂移：多出来 {sorted(found - set(ALLOWED_NON_TEXT_INDEX_ENTRIES))}，"
        f"少了 {sorted(set(ALLOWED_NON_TEXT_INDEX_ENTRIES) - found)}。"
        f"新来一枚游离 CR 的文件，和有人把已封版工件强转文本，都走这一格")


def test_eol_rules_are_a_no_op_for_the_current_tree():
    """B0-007 的静态半边：凡被 `eol=` 规则管着的文件，工作树形态**已经**等于规则要求。

    成立 ⇒ 加 `.gitattributes` 不改变任何文件的签出形态，也就不会制造全量归一 diff。
    """
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                             capture_output=True, check=True).stdout.split(b"\0")
    checked = 0
    offenders: "list[str]" = []
    for raw in tracked:
        if not raw:
            continue
        relative = raw.decode("utf-8", "replace")
        suffix = Path(relative).suffix.lower()
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        body = path.read_bytes()
        if suffix == ".sh":
            checked += 1
            if b"\r" in body:
                offenders.append(f"{relative} 含 CR，但规则要求 eol=lf")
        elif suffix == ".ps1":
            checked += 1
            if body.count(b"\r\n") == 0:
                offenders.append(f"{relative} 没有 CRLF，但规则要求 eol=crlf")
    assert checked, "`.sh` / `.ps1` 一枚都不在面上：这条 no-op 证明退化成了空判"
    assert not offenders, "加规则会改动工作树：" + "；".join(offenders)
```

回写常数（不许沿用本计划里的预估 1329）：

Run: `python scripts/b0_collection_probe.py | head -1`
Expected: `TOTAL <实测 N>`；把 `EXPECTED_COLLECTED = N` 写进文件，并把 N 与"本文件贡献 13 枚"同时记进 `task-2-report.md`。若 N ≠ 1316 + 13，说明有模块被 import 失败拖住，当场报告不要凑数。

- [ ] **Step 6: 逐枚点名 `_OWN_TEST_NAMES`（自我存续钉的第二个源，故意与装饰器重复）**

放在 helper 区之后：

```python
#: 13 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
#: 只遍历本模块的用例，对本文件被摘走任何东西都无感。
_OWN_TEST_NAMES = (
    "test_collected_count_matches_the_pinned_number",
    "test_the_gate_module_itself_is_collected",
    "test_collection_measurement_counts_node_ids_not_the_summary_line",
    "test_backend_contracts_has_no_unittest_discover_step",
    "test_backend_contracts_runs_the_pytest_suite",
    "test_step_ordering_still_explains_itself",
    "test_install_face_uses_requirements_txt_as_the_source",
    "test_extra_pip_arguments_are_exactly_the_exemption_table",
    "test_every_exemption_row_states_why",
    "test_gitattributes_carries_the_required_rules",
    "test_index_has_no_crlf_entries",
    "test_non_text_index_entries_are_exactly_the_enumerated_set",
    "test_eol_rules_are_a_no_op_for_the_current_tree",
)
```

- [ ] **Step 7: 跑定向套件，确认"该红的红、该绿的绿"**

Run: `python -m pytest backend/tests/test_ci_gate_contract.py -q`
Expected（**逐枚点名，别按"改造前的门都该红"猜**）：
- **红 5 枚**：`test_backend_contracts_has_no_unittest_discover_step`、`test_backend_contracts_runs_the_pytest_suite`（`(?!/)` 让 SECA-20 的单文件子集不算数）、`test_install_face_uses_requirements_txt_as_the_source`、`test_extra_pip_arguments_are_exactly_the_exemption_table`、`test_gitattributes_carries_the_required_rules`。
- **绿 8 枚**：三枚收集钉（常数已按 Step 5 实测回写）、`test_step_ordering_still_explains_itself`、`test_every_exemption_row_states_why`、以及 `test_index_has_no_crlf_entries` / `test_non_text_index_entries_are_exactly_the_enumerated_set` / `test_eol_rules_are_a_no_op_for_the_current_tree` 三枚**回归守卫**（它们不是迁移门：index 本来就全 LF、`i/-text` 本来就是那三枚、`.sh`/`.ps1` 形态本来就合规）。
若出现"全绿"⇒ 解析 helper 失效（找不到 job 块时抛的是 AssertionError 还是静默返回空，必查）。
若 `test_the_gate_module_itself_is_collected` 红在 `_OWN_TEST_NAMES` 与实收不符 ⇒ 按实收修名单，不许改 `dir()` 自动遍历。

- [ ] **Step 8: 全量套件不许被本文件弄坏**

Run: `python -m pytest backend/tests -q`
Expected: `1329 + 0 failed`（或实测 N），耗时 ≈ 170s + 一次收集的 40–62s。本文件那 13 枚里有 1 枚会跑子进程收集 —— **这是本任务有意引入的常驻成本**，写进报告，由 Task 5 的耗时读数复核是否可接受（不可接受时按 §10.3 报，不许悄悄换成进程内量法）。

- [ ] **Step 9: 台账与快照**

`progress.md` 追加：`- Task 2 complete：13 枚门落地，红相 {k} 枚红（清单见 task-2-report.md），EXPECTED_COLLECTED=<N> 双写完成`。
快照 `snap-task2-post/test_ci_gate_contract.py`。子代理不得跑 git 写命令。

---


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
   `autocrlf=false` 的机器（Linux 默认）可以把 CRLF 字节写进 index。这一族还有第三枚钉：**解析
   覆盖度**（§16 卡 K）——`git ls-files --eol` 的每一行都必须被读到，"解析出的条数 == `git ls-files`
   的跟踪条数"，不等即红；它不假设属性列长什么样，所以任何未来的丢行都只会响亮地红、不会静默瞎。
   同一枚覆盖度钉还有**非空地板**（Task 6 修复轮 1，变异台 N6 实测换来的那一格）：两侧都必须收得到
   东西才轮到等量判据说话 —— 否则 `0 == 0` 会让钉自己放行，而下游 `i/crlf` 消费门跟着变成空判绿。

自我存续是**两枚**钉、各守一面（规格 §16 卡 H 把原来混写成一件事的那句拆开了）：

* `test_the_gate_module_itself_is_collected` 守"本文件贡献了几枚"——抓改名、抓摘走整枚用例、
  抓常数被人凑。它**抓不到哑掉的门**：`--collect-only` 对 skip / skipif / unittest.skip 标记
  照样打印 node id（独立评审实测 4 枚、rc=0），被哑掉的门在枚数面上完全隐形。
* `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 守后一半——直接扫本文件自己的
  字节，任何哑门装饰器都不许出现。代价说清楚：这枚钉只看本文件，别的门文件被哑掉归它们自己的
  账；而"本文件被改名或整枚删除"两枚钉都覆盖不到，那是规格 §14 L6 登记的不可消除自指盲区，
  别把它当已解决。

ci.yml 类门的共同口径：所有对**命令**的匹配都先在 `_step_script()`（剥掉 `#` 注释行）上做。
原因不是洁癖——计划要求树上留一句解释"`python -m unittest discover` 那一步已删除"的注释，而
`_job_steps` 会把两枚 step **之间**的注释归进前一枚 step，拿原文匹配命令的门因此会永远红在错误
的 step 上。唯一例外是 `test_step_ordering_still_explains_itself` 的文字存在半边：它的宾语正是
注释本身，必须看原文。

第 16 枚门（R9 ②）不属于上面四族，它守的是"这份 workflow 打得开"：Task 3 真踩到计划正文里的
`- name: Run backend contract suite (single runner: pytest)` —— plain scalar 里的 `: ` 被 YAML
读成映射分隔符，`yaml.safe_load` 当场 `ScannerError`，而上面 15 枚门全是正则 + 行切片、从不
加载 YAML ⇒ 一份语法就错的 ci.yml 可以拿 14 绿，到远端才炸 `Invalid workflow file`。PyYAML 既
不在 `backend/requirements.txt` 里（B0 也不许动它），门又必须只用标准库，所以这里**不做 YAML
解析器**（那等于给自己造第二份真相），只钉住刚刚真咬过我们的那一族形状：含 `: ` 的 plain scalar
必须整体加引号；R10 的修复轮 2 又补了两条——同一枚 `ScannerError` 家族里的尾冒号邻形
（`- name: Note:`）一起钉，而引号判定从"只看原始值"改成"先看剥完行内注释的值"，因为原始值的末
字符是注释散文时那对引号"配不成"，`- name: "…"  # 说明` 这形合法写法会被判成假红（假红正是本仓库
最贵的那种错：它教会人加豁免）。修复轮 3 把那条修法补成**两读并判**：剥注释那一步本身是
quote-blind 的，引号里的 `#` 会先把值劈断，所以"只看剥后的那一读"又镜像地假红了
`- name: "Run: everything #1"`——同一族错，改前改后各咬一口，两头都得放行。
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
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITATTRIBUTES_FILE = REPO_ROOT / ".gitattributes"
BASELINE_NODE_IDS = (REPO_ROOT / ".superpowers" / "sdd" / "ENTERPRISE_B0_PLAN"
                     / "baseline" / "collected-node-ids.txt")

BACKEND = "backend-contracts"

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


# 常数每加一枚门就要**重新实测**回写（不许凑）：1316 是 Task 1 的基线，本文件从 16 枚起算。
# 1332 = 1316 + 16（Task 3 实测）；1335 = +3（`9bed85a` SEC-A-CORR-01 的三枚结构钉，属加测试）；
# 1336 = +1（第 17 枚门 B0-12 区间化，独立终审 Important 2）。每一格都由
# `python scripts/b0_collection_probe.py` 现场量出，不是推导出来的。
EXPECTED_COLLECTED = 1336


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
    """自我存续（卡 H 的 (a) 半边）：不依赖总数，只盯"本文件贡献了几枚"。

    改名、摘走整枚用例、把常数被人凑都会在这里红。**加 skip 不会** —— `--collect-only` 照打
    node id，那一面由 `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 守。
    """
    mine = [node_id for node_id in _collected() if node_id.startswith(f"{OWN_MODULE}::")]
    assert sorted(mine) == sorted(
        f"{OWN_MODULE}::{name}" for name in _OWN_TEST_NAMES), (
        f"门自己被摘了或哑了：本文件应有 {len(_OWN_TEST_NAMES)} 枚，实收 {len(mine)} 枚")


#: 哑门装饰器的形状：at 号 + 点分段名 + skip / xfail 词干（pytest.mark.skip、
#: pytest.mark.skipif(...)、unittest.skip(...)、pytest.mark.xfail 都在这一形里）。
#: 刻意不在本文里把 at 号和词干写成一行示例 —— 那会被这枚模式扫到自己的源码行，门当场假红。
#: 模式里用 `[ \t]` 而不是 `\s`，跨行不认：否则一枚正常装饰器的下一行只要以 skip 开头
#: （本文件的 tokenize 循环里就有 `skip_next`）就会被当成装饰器命中。
_MUTING_DECORATOR = re.compile(
    "@" r"[ \t]*(?:[\w.]+[ \t]*\.)?(?:skip\w*|xfail\w*)", re.IGNORECASE)


def test_the_gate_module_itself_carries_no_skip_or_xfail_decorator():
    """自我存续（卡 H 的 (b) 半边）：本文件字节内不许出现任何哑门装饰器。

    为什么必须是机器判据而不是口径：枚数钉对 skip 类标记天生瞎（独立评审实测：带三种哑门标记的
    夹具照样被 `--collect-only` 打印 4 枚 node id、rc=0），所以随便给一枚门挂上 skip 标记就能让
    本文件 16 枚全绿而其中任意几枚永不执行——正是规格 F6"门在场但哑了"。这一格把"哑掉"
    变成可判定的。
    """
    source = Path(__file__).resolve().read_bytes().decode("utf-8", "replace")
    offenders = [match.group(0) for match in _MUTING_DECORATOR.finditer(source)]
    assert not offenders, (
        f"本门文件里出现 {len(offenders)} 枚哑门装饰器：{offenders[:5]}。"
        f"收集面枚数对它们无感，job 可以是绿的而门不再执行")


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


_STEP_COMMENT_LINE = re.compile(r"^[ \t]*#")


def _step_script(step: str) -> str:
    """把一段 step 原文里的 `#` 注释行整行剥掉，只留下会真正执行的正文。

    所有对**命令**的匹配都必须先过这里，原因是 I-1 那颗地雷：计划明确要求 ci.yml 里留一句
    "原既有步 `python -m unittest discover` 已删除"的注释（§5.2 的两条顺序理由之一），而
    `_job_steps` 把两枚 step **之间**的注释归进前一枚 step。不剥注释的话：
      * `test_backend_contracts_has_no_unittest_discover_step` 在一次完全正确的 Task 3 之后
        仍然红，而且红在 `validate_demo_assets` 那一步上（它把注释当成了命令）；
      * 锚点识别同理会被注释污染。
    只剥整行注释，不动行尾内联 `#` —— 内联那半由 `_pip_package_tokens()` 自己按 `#` 切。
    唯一的例外是 `test_step_ordering_still_explains_itself` 的文字存在半边：它的宾语正是注释。
    """
    return "\n".join(line for line in step.splitlines()
                     if not _STEP_COMMENT_LINE.match(line))


_TEST_RUN_MARKER = re.compile(r"^\s*(?:-\s+)?run:", re.MULTILINE)
#: 安装步要求的标量形态：`run: |` 字面块（`|-` / `|+` 同认）。折叠标量 `>-` 下 YAML 语义是一行、
#: 原文却是好几行，按物理行的 tokenize 与 YAML 语义分叉，续行的包名会整体消失（卡 I 的第三个假绿）。
_LITERAL_BLOCK_RUN = re.compile(r"^\s*run:\s*\|", re.MULTILINE)
#: 跑全目录的那枚主门。`(?!/)` 的意义见 `test_backend_contracts_runs_the_pytest_suite`。
_SUITE_WIDE_PYTEST = re.compile(r"python -m pytest backend/tests(?!/)")


def _test_runs(text: str, job: str) -> "list[str]":
    return [step for step in _job_steps(text, job) if _TEST_RUN_MARKER.search(_step_script(step))]


def test_backend_contracts_has_no_unittest_discover_step():
    offenders = [step for step in _test_runs(_ci_text(), BACKEND)
                 if "unittest discover" in _step_script(step)]
    assert not offenders, (
        f"F1 复活：`backend-contracts` 里又出现 unittest 收集（{len(offenders)} 处）。"
        f"裸 pytest 函数枚枚不收，而 job 可以是绿的\n"
        f" offending step 正文（已剥注释）：{[s.strip()[:200] for s in offenders][:3]}")


def test_backend_contracts_runs_the_pytest_suite():
    """必须是"跑整个目录"的那一步，而且必须**没被过滤旗标缩成子集**。

    `(?!/)` 是这枚门的实质：只写 `"python -m pytest backend/tests" in step` 的话，
    SECA-20 那步（`backend/tests/test_secret_hygiene_contract.py`）子串命中 ⇒ 门在改造前就绿，
    而它要防的"主门被删掉"永远抓不到。

    I-5 是另一半：光"命中一次目录级调用"不够 —— 同一步挂上 `-k` / `--ignore` / `--deselect` /
    `-x` / `--lf` 之类旗标就只跑一个子集，收集数钉（B0-01）声称的那 1332 枚从此没有任何一步
    真正执行过，而 16 枚门照样全绿。所以主门正文里一枚过滤旗标都不许出现。
    """
    runs = _test_runs(_ci_text(), BACKEND)
    suite_wide = [step for step in runs
                  if _SUITE_WIDE_PYTEST.search(_step_script(step))]
    assert suite_wide, (
        "主门不跑全量套件：B0-01 的收集数钉必须由这一步实际执行，而不是只写在文档里。"
        "注意 SECA-20 那枚单文件子集不算——它只跑 5 枚")
    muted: "list[str]" = []
    for step in suite_wide:
        flags = _main_gate_filter_flags(_step_script(step))
        if flags:
            muted.append(f"{sorted(set(flags))} ← {step.strip()[:160]}")
    assert not muted, (
        "主门被过滤/短路旗标缩成了子集，收集数钉不再由这一步实际执行：\n" + "\n".join(muted))


#: 把"跑整目录"缩成"跑一个子集"或让它提前短路的旗标（I-5 / R8 点名 `-k` `--ignore`
#: `--deselect` `-x` `--lf` `--kf` `-m`，其余是同一族的其他写法/长名）。
MAIN_GATE_FILTER_FLAGS = (
    "-k", "-m", "-x", "--exitfirst", "--deselect", "--ignore", "--ignore-glob",
    "--lf", "--last-failed", "--nf", "--new-first", "--ff", "--failed-first", "--kf",
    "--co", "--collect-only", "--maxfail", "--sw", "--stepwise",
)


def _main_gate_filter_flags(script: str) -> "list[str]":
    """主门正文里的过滤旗标 token。

    先把 `python -m` / `python3 -m` 这枚**前缀**摘掉再 tokenize —— 不摘的话
    `python -m pytest` 自带的 `-m` 会被当成 pytest 的 marker 表达式旗标，门一落地就假红。
    `--opt` 与值之间允许任意个空格（`- m` 这种写法也一并剥掉），但 `-m "not slow"` 里
    **第二枚** `-m` 必须留下 —— 反证台 D 段就是量这一对的。
    `--flag=value` 与 `--flag value` 两种写法都认；`-q` 不是过滤旗标（它不改收集面）。
    """
    normalized = re.sub(r"\bpython[3]?(?:\.exe)?\s+-\s*m\s+", " ", script)
    out: "list[str]" = []
    for raw in normalized.replace("\n", " ").split():
        token = raw.strip("\"'").rstrip(";,")
        if not token:
            continue
        if token in MAIN_GATE_FILTER_FLAGS:
            out.append(token)
        else:
            head = token.split("=", 1)[0]
            if len(token.split("=", 1)) == 2 and head in MAIN_GATE_FILTER_FLAGS:
                out.append(head)
    return out


#: 顺序钉的四枚锚点（规格 §5.1 的目标步骤序列）。谓词一律跑在 `_step_script()` 上。
#: 第二位是"必需"标志：compose / pwsh / 扫描三枚缺席即红；主门标 `False` 是因为它的缺席由
#: 门 5 归因（本枚不重复报同一个根因），在场时仍参与严格全序。详见该门的 docstring。
_ORDER_ANCHORS: "tuple[tuple[str, bool, object], ...]" = (
    ("SECA-20 扫描步", True, lambda s: "test_secret_hygiene_contract.py" in s),
    ("主门（pytest 跑全目录）", False, lambda s: bool(_SUITE_WIDE_PYTEST.search(s))),
    ("compose 校验步", True, lambda s: "docker compose" in s),
    ("pwsh 语法校验步", True, lambda s: "deploy.ps1" in s),
)


def test_step_ordering_still_explains_itself():
    """顺序的两条理由（§5.2）要用文字留在树上，而且**顺序本身必须为真**（I-4 / R8）。

    原写法只断言"SECA-20"与"unittest"两个词在 job 块里出现过 —— 把扫描步挪到主门之后它照样绿，
    而那正是 f6c67b5 之后唯一会让人"顺手挪一步"的失配。`_job_steps` 给的是有序段，所以判据
    改成段索引的严格全序。文字存在那半边**保留**，而且必须看原文（注释正是它的宾语、不能剥）。
    """
    text = _ci_text()
    block = _job_block(text, BACKEND)
    assert "SECA-20" in block and "unittest" in block, (
        "ci.yml 里解释扫描步为何排在主门之前的注释被删了：那正是 f6c67b5 那轮踩过的地方")

    scripts = [_step_script(step) for step in _job_steps(text, BACKEND)]
    anchors: "list[tuple[str, int]]" = []
    absent: "list[str]" = []
    for label, mandatory, probe in _ORDER_ANCHORS:
        hits = [i for i, script in enumerate(scripts) if probe(script)]
        if not hits:
            assert not mandatory, (
                f"顺序钉的必需锚点 `{label}` 在 ci.yml 里找不到：位置判据不能对『找不到』保持沉默")
            absent.append(label)
            continue
        anchors.append((label, hits[0]))
    order = [index for _, index in anchors]
    assert len(set(order)) == len(order) and order == sorted(order), (
        f"step 顺序被改动，§5.2 的两条理由不再成立：{' → '.join(f'{label}#{index}' for label, index in anchors)}"
        f"（要求严格递增：扫描 < 主门 < compose < pwsh；缺席锚点 {absent}）")

#: 除 requirements.txt 之外允许出现的 pip 参数 → (处数, 为什么它是豁免而不是偷懒)。
#: 形状沿用 SECA-20 扫描门的 `EXEMPTIONS`：键不含行号，处数是计数，多一处少一处都红。
PIP_INSTALL_EXEMPTIONS: "dict[str, tuple[int, str]]" = {
    "pytest": (1, "测试运行器，不是应用运行时依赖。塞进 requirements.txt 会让镜像为跑测试多背一包"),
    "torch": (1, "不是新增依赖：sentence-transformers 的传递依赖就在 requirements.txt 里。"
                "这一行只选 CPU 发行源（~200MB 而不是默认那个带 CUDA 的 ~2.5GB）"),
}


def _install_steps(text: str, job: str) -> "list[str]":
    return [step for step in _test_runs(text, job) if "pip install" in _step_script(step)]


def test_install_face_uses_requirements_txt_as_the_source():
    steps = _install_steps(_ci_text(), BACKEND)
    assert steps, "`backend-contracts` 没有任何安装步"
    assert any("-r backend/requirements.txt" in _step_script(step) for step in steps), (
        "依赖又变成 YAML 里的手写清单：`f6c67b5` 的远端 ModuleNotFoundError 就是这么来的")


def _pip_package_tokens(step_texts: "list[str]") -> "list[str]":
    """只取 `pip install` 之后的**包名** token。

    绝不拿整段 step 文本去 tokenize：那会把 YAML 注释里的中文词、`sentence-transformers`、
    `-r backend/requirements.txt` 里的 `requirements.txt` 全算成"未豁免参数"，门一落地就假红。
    带值选项（`-r` / `--index-url`）连值一起跳；含 `/` 的是路径不是包名。

    口径的已知边界：**按物理行**认 `pip install`，所以折叠标量（`>-`）里续写到第二行的包名
    根本不会出现在同一物理行 ⇒ tokenize 结果为空。这不是"没有额外参数"，而是这枚门哑了 ——
    由 `test_extra_pip_arguments_are_exactly_the_exemption_table` 的地板 + `run: |` 形状钉兜住
    （规格 §16 卡 I）。
    """
    takes_value = {"-r", "--requirement", "--index-url", "--extra-index-url", "-i", "-f", "--find-links"}
    out: "list[str]" = []
    for text in step_texts:
        for line in _step_script(text).splitlines():
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


#: 安装面里**带来源语义**的选项（卡 I (3)）。包名钉只回答"装什么"，这一格回答"从哪儿装"。
_PIP_SOURCE_OPTIONS = {
    "-r": "requirement", "--requirement": "requirement",
    "--index-url": "index", "-i": "index", "--extra-index-url": "index",
}
#: 钉住的来源**值**。写成显式集合而不是"任意 https 都行"：`torch` 这个名字在敌意镜像和 CPU
#: pytorch 镜像上长得一模一样，只钉包名等于把发行源交给写 YAML 的那个人。
ALLOWED_PIP_SOURCE_VALUES = (
    "https://download.pytorch.org/whl/cpu",
    "backend/requirements.txt",
)


def _pip_source_option_values(step_texts: "list[str]") -> "list[tuple[str, str]]":
    """把安装面里 `--index-url` / `--extra-index-url` / `-r` 这类选项的 **(选项, 值)** 收出来。

    `--opt value` 与 `--opt=value` 两种写法都认；口径与 `_pip_package_tokens` 一致（同一物理行、
    注释先丢），因此 `run: |` 形状钉同样保护它 —— 折叠标量下第二行的值会看不见。
    """
    out: "list[tuple[str, str]]" = []
    for text in step_texts:
        for line in _step_script(text).splitlines():
            body = line.split("#", 1)[0]
            if "pip install" not in body:
                continue
            tokens = [raw.strip("\"'") for raw in body.split("pip install", 1)[1].split()]
            cursor = 0
            while cursor < len(tokens):
                token = tokens[cursor]
                if token.startswith("-") and "=" in token:
                    option, _, value = token.partition("=")
                    if option in _PIP_SOURCE_OPTIONS:
                        out.append((option, value))
                    cursor += 1
                    continue
                if token in _PIP_SOURCE_OPTIONS:
                    if cursor + 1 < len(tokens):
                        out.append((token, tokens[cursor + 1]))
                        cursor += 2
                    else:
                        out.append((token, ""))        # 选项挂空 ⇒ 也当越界
                        cursor += 1
                    continue
                cursor += 1
    return out


def test_extra_pip_arguments_are_exactly_the_exemption_table():
    """三个方向都算违规（与 SECA-20 的 `_gate_offenders` 同判据）：多出来的、处数不等、死行。

    卡 I (2) 另加两枚地板，因为"tokenize 到 0 枚"和"确实没有额外参数"长得一模一样：
      * 安装步必须是 `run: |` 字面块 —— 折叠标量下按物理行的 tokenize 与 YAML 语义分叉；
      * tokenize 结果必须**非空**，空即红（红在"门哑了"，不是红在"CI 干净"）。
    """
    steps = _install_steps(_ci_text(), BACKEND)
    folded = [step for step in steps if not _LITERAL_BLOCK_RUN.search(_step_script(step))]
    assert not folded, (
        f"{len(folded)} 枚安装步不是 `run: |` 字面块：折叠/单行标量里续行的包名会整体消失，"
        f"豁免表钉会红在『死行』这个错误的理由上、或者干脆哑掉。第一段正文："
        f"{[s.strip()[:160] for s in folded][:1]}")
    tokens = _pip_package_tokens(steps)
    assert tokens, (
        "安装面 tokenize 出来是空的 —— 这不能读成『没有额外 pip 参数』，只能读成这枚门哑了"
        "（卡 I (2) 的地板）。要么安装步根本没写 `pip install`，要么它不是 `run: |` 形态。")
    seen: "dict[str, int]" = {}
    for token in tokens:
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


def test_install_face_pip_source_values_are_pinned():
    """卡 I (3)：`-r` / `--index-url` / `--extra-index-url` / `-i` 的**值**逐枚落在钉住的集合内。

    评审量出的第一个假绿就在这一格：`pip install torch --index-url https://evil.example.com/simple`
    在包名钉里只看到 `torch`，绿；而豁免行写的理由正是"选 CPU **pytorch 发行源**"——发行源本身
    没人钉过。本枚与 `test_extra_pip_arguments_are_exactly_the_exemption_table` 的分工是
    "装什么 / 从哪儿装"两维，缺一维都会放走一次真实的供应链漂移。
    """
    pairs = _pip_source_option_values(_install_steps(_ci_text(), BACKEND))
    offenders = [f"`{option} {value}` 不在钉住的来源集合内"
                 for option, value in pairs if value not in ALLOWED_PIP_SOURCE_VALUES]
    assert not offenders, (
        "安装面出现了没钉过的依赖真源/发行源：" + "；".join(offenders)
        + f"\n钉住的是：{list(ALLOWED_PIP_SOURCE_VALUES)}"
        + f"\n本次收到的 (选项, 值)：{pairs}")


def test_every_exemption_row_states_why():
    for token, (count, why) in PIP_INSTALL_EXEMPTIONS.items():
        assert count >= 1, token
        assert len(why) >= 12, f"豁免行 `{token}` 的『为什么』短到不像是理由，像是占位"

# ---------------------------------------------------------------------------
# 第 16 枚门（R9 ② 落地；R10 修复轮 2 把邻形扩了一形）：plain scalar 的值里含 `: `、
# 或剥完行内注释后以 `:` 结尾时，整个值必须带引号。
# 口径仍钉在"刚刚真咬过我们的那一族形状"上，不扩成一台 YAML 机器：tab / 缩进 / 引号配对
# 三件套按 R10 判为 YAGNI，留在临时脚本里当证据。
# ---------------------------------------------------------------------------

#: 结构行的形状：`[缩进][- ]键: 值`。键限定成 ASCII 单词字符（workflow 的键全在这一族：
#: `name` / `run` / `uses` / `key` / `shell` / `python-version`……），于是中文散文、
#: `- 6333:6333`（ports 序列项）、`qdrant/qdrant:v1.19.1`（冒号后没有空格）都不算结构行。
_STRUCTURAL_SCALAR_LINE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?:(?P<dash>-)[ \t]+)?"
    r"(?P<key>[A-Za-z0-9][A-Za-z0-9_.\-]*)[ \t]*:[ \t]+(?P<value>\S.*)$")

#: 块标量的开头指示符：`|` `|-` `|+` `|2` `>` `>-` `>+`……值为这一形时它下面缩进更深的行全是正文。
_BLOCK_SCALAR_INDICATOR = re.compile(r"^[|>][0-9]*[-+]?[0-9]*$")

#: flow 集合的值：`branches: [main]` / `ports: [6333, 6334]` / `with: {…}`。
_FLOW_STYLE_VALUE = re.compile(r"^[\[{]")

#: 内联注释：plain scalar 里"空格 + 井号"起就是注释（YAML 也是这条规则），
#: 注释里的 `: ` 是散文、不是值的一部分。**但这一步不看引号**（quote-blind）：值里
#: `- name: "跑一件事 #1"` 那枚井号在引号内也会被当成注释起点劈掉，所以引号判定必须
#: 同时看原始值与剥后的值两读——修复轮 3 的镜像假红就是只看了剥后那一读。
_INLINE_COMMENT = re.compile(r"[ \t]#")


def _fully_quoted(value: str) -> bool:
    """整体被同一枚引号包住（`"…"` / `'…'`）：里面的 `: ` 是值的一部分，YAML 不会误读。"""
    return len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'")


def _workflow_scalar_entries(text: str) -> "list[tuple[int, str, str, bool]]":
    """把 workflow 原文切成结构标量条目 `(行号, 键, 值, 是否带 `- ` 前缀)`。

    这里唯一的"语义"是一条缩进规则：一枚 `键: |` / `键: >-` 之后、缩进比它深的行都是正文，
    整段跳过。这不是怕麻烦，而是**判据不能反过来咬人**——`run: |` 里的 python/shell 代码随时
    可以合法写出 `print("failed: x")`，那枚冒号在 YAML 语义里根本没有歧义，拿它判红就是一枚
    会自己假红的门。跳过正文也不等于放宽：本门的宾语是 step 名与键值，Task 3 炸的也正是它。
    同样刻意留在范围外的是多行 plain scalar 的续行、锚点与别名（`&x` / `*x`）——它们都不是
    咬过我们的那一形，再往下钉就等于开始重造解析器（R9 ② 明令禁止的那份"第二套真相"）。
    """
    out: "list[tuple[int, str, str, bool]]" = []
    block_indent = None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            # 空行 / 整行注释：ci.yml:22 那句 `ModuleNotFoundError: httpx` 走这一支被放过
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if block_indent is not None:
            if indent > block_indent:
                continue                       # 块标量的正文，不是 `键: 值`
            block_indent = None                # 缩进回落 ⇒ 块结束，本行照常参与检查
        match = _STRUCTURAL_SCALAR_LINE.match(line)
        if match is None:
            continue
        value = match.group("value").rstrip()
        if _BLOCK_SCALAR_INDICATOR.match(value):
            block_indent = indent              # 这一行没值可查，它只是开了一个块
            continue
        out.append((lineno, match.group("key"), value, match.group("dash") is not None))
    return out


def _unquoted_colon_bearing_scalars(text: str) -> "list[tuple[int, str, str]]":
    """条目里"值有歧义、又没整体加引号"的那几枚 —— R9 ① 咬过我们的原形 + R10 扩的尾冒号邻形。

    **引号判定跑在两读上**（修复轮 2 的 I-3 + 其镜像假红，修复轮 3）：`_fully_quoted()` 既看剥完
    行内注释的值、也看原始值，任一成立即放行。只看不剥的那一读会假红
    `- name: "…"  # 说明`（原始值末字符是注释散文，那对引号"配不成"）；只看剥后的那一读假红
    `- name: "Run: everything #1"`（`_INLINE_COMMENT` 是 quote-blind 的，引号里那枚 `#` 先把值
    劈掉，收尾引号随之消失）。两枚都是合法 YAML 被判红，而假红正是本仓库最贵的那种错：
    失效史反复是 假红 → 有人加豁免 → 真形状跟着漏（§2、卡 I 各留了一页）。
    两读各自的代价也要量清楚（逐形谓词台见报告《Task 3 修复轮 3》）：
      * `_fully_quoted()` 比的是**首尾字符同为引号**、不是引号配对，所以 `"a: b" and "c"`
        （宿主 PyYAML 实测 ParserError）在加 `or` **之前就已经**被放行 —— 那是既有的边界，
        不是本轮换来的。
      * 加 `or` 新开的那一面窄到要写成 `"a: b #c" d"`（引号内含 `#`、引号外还有散文、散文末尾
        再补一枚同类引号）才踩得到，实测那一形从 RED 翻成 GREEN ⇒ 登记为已知边界，不为此引解析器。
      * 反向还有一枚**本判据治不好**的假红：`- name: "…#1"  # 注释`（引号内含 `#`、后面还挂真
        注释）——quote-blind 的第一刀落在引号里面，两读都凑不出完整引号对，实测改前改后同为
        RED。它不在本轮清单里，要消只能真的去解析 YAML（R9 ② 禁止）。
    常见的那枚部分引号 `- name: "Run: a" baz`（首尾不同字符）仍然红。这枚门的宾语始终是
    "带冒号的步名"，不是 YAML 语法全量（要全量就得引解析器，等于造第二份真相）。
    尾冒号邻形（Minor 5，R10 点头才扩）：剥完的值以 `:` **结尾**（`- name: Note:`）是嵌套映射
    的 opener，宿主 PyYAML 实测 `ScannerError: mapping values are not allowed here`，与含 `: `
    同属一枚事故家族 ⇒ 一个子句一起钉。**仍然不做** tab / 缩进 / 引号配对三件套（R10 判 YAGNI）。
    """
    offenders: "list[tuple[int, str, str]]" = []
    for lineno, key, value, dashed in _workflow_scalar_entries(text):
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
        if _FLOW_STYLE_VALUE.match(body):
            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
        if _fully_quoted(value) or _fully_quoted(body):
            continue                           # 任一读法整体被同一对引号包住 ⇒ 冒号是值的一部分
        if ": " in body or body.endswith(":"):
            offenders.append((lineno, ("- " if dashed else "") + key, body))
    return offenders


def test_workflow_plain_scalars_bearing_a_colon_space_are_quoted():
    """第 16 枚门（R9 ②）：`- name:` / `key:` 这类 plain scalar 值里含 `: ` 时必须整体加引号。

    存在理由是一次真实事故、不是审美：计划正文原本写
    `- name: Run backend contract suite (single runner: pytest)`，那枚没引号的 `: ` 让 YAML
    把它读成嵌套映射，`yaml.safe_load` 当场 `ScannerError: mapping values are not allowed
    here` ——而前面 15 枚门**没有一枚会加载 YAML**（PyYAML 不在 requirements.txt，门也不许引
    第三方依赖），所以一份连 GitHub 都打不开的 workflow 能拿 14 绿，直到远端报
    `Invalid workflow file` 才响。修法是钉形状而不是引依赖。地板与
    `test_extra_pip_arguments_are_exactly_the_exemption_table` 的"非空 tokenize"同族：扫不到
    任何 `- name:` 就当场红，因为那只可能是门哑了，不可能是"步名全都合法"。

    改过的三处，门数与门名都不变（R10 明令不加门）：
      * 覆盖面（轮 2 / Minor 5）：除"值里含 `: `"外，另钉"剥完注释的值以 `:` 结尾"
        （`- name: Note:`），同一枚 `ScannerError` 事故家族、同一条修法。
      * 引号判定的宾语（轮 2 的 I-3 → 轮 3 补成两读并判）：轮 2 把判定从"只看原始值"挪到
        "只看剥完注释的值"，修好了 `- name: "…"  # 说明`；但 `_INLINE_COMMENT` 是 quote-blind
        的，引号里的 `#` 会先把值劈断，于是 `- name: "Run: everything #1"` 换边假红。轮 3 定稿为
        **两读任一成立即放行**。方向感：本仓库的失效史是"假红 → 加豁免 → 真形状跟着漏"，
        所以两头都不许留；`or` 换来的那一窄面与它治不掉的残留都在
        `_unquoted_colon_bearing_scalars` 的 docstring 里逐形登记。
    """
    text = _ci_text()
    entries = _workflow_scalar_entries(text)
    named = [row for row in entries if row[1] == "name" and row[3]]
    assert named, (
        f"workflow 里一枚 `- name:` 结构行都没扫到（结构行共 {len(entries)} 枚）：这不能读成"
        f"『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）")
    offenders = _unquoted_colon_bearing_scalars(text)
    assert not offenders, (
        f"{len(offenders)} 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把"
        f"那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`："
        + "；".join(f"第 {lineno} 行 `{key}: {value}`" for lineno, key, value in offenders)
        + "\n修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），"
          "不是把带冒号的那半句删掉")

REQUIRED_GITATTRIBUTES_RULES = (
    "* text=auto",
    "*.sh text eol=lf",
    "*.ps1 text eol=crlf",
    # 2026-09-29 加的第四枚：P0 闸的外部锚 `[I2]` 量的是**检出后**的字节，而 `* text=auto` +
    # `eol: unspecified` 把检出形态交给每台机器的 core.autocrlf —— Windows 干净 clone 会把
    # `docs/evidence/**` 六枚 bundle JSON 拉成 CRLF，于是同一枚 commit 在 Linux 绿、在 Windows 红
    # （台账 R32 / 3B 报告 F9 的隔离实验：同一 clone 只改行尾 ⇒ `3 failed` ↔ `15 passed`）。
    # 规则只写在 `.gitattributes` 里不够：没有这一枚钉，任何人删掉它就静默退回那台单机耦合的闸。
    # 所以并进这枚**已存在**的门——加一条必需规则，不新增测试、不动收集数钉。
    "docs/evidence/** text eol=lf",
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
#: 属性列**允许含空格**（规格 §16 卡 K）。`.gitattributes` 的 `*.sh text eol=lf` 一类规则生效后，
#: 这一列就写成 `attr/text eol=lf` / `attr/text eol=crlf`；原样式 `attr/\S*` 只认到空格为止
#: ⇒ 那两行**静默不匹配**、解析面从 313 掉到 311，丢掉的恰好是本仓对行尾最敏感的两枚文件
#: （`scripts/deploy.ps1` 与 `.superpowers/scripts/run_p0_failover_acceptance.sh`）。
#: 修法是把这一列的终点从"下一个空白"改成"记录里那枚制表符"——`git ls-files --eol` 在路径前
#: 输出**一枚字面 tab**（实测：每条记录恰 1 枚 tab，见 `_index_eol_records` 的口径说明），
#: 于是属性列用 `[^\t]*` 认到 tab 之前、只把其间的对齐空格剥掉：空格在列内合法，但绝不跨 tab吃路径。
_EOL_LINE = re.compile(r"^(i/\S+)\s+(w/\S+)\s+(attr/[^\t]*?)\s*\t(.+)$")


def _git_z_records(*args: str) -> "list[str]":
    """跑一枚只读 git 命令，按 `-z` 的 NUL 分隔切记录（不解引号、不改字节）。

    两侧都取 `-z` 是**覆盖度比较的口径**（卡 K）：默认 `core.quotePath=true` 会把非 ASCII 路径
    八进制转义并套上双引号，本仓实测有 20 枚这样的路径（`demo-data/01-差旅费用管理制度.md` 一类）。
    明文面上它们是 `"demo-data/01-\\345\\267\\256..."`、`-z` 面上是原始 UTF-8 字节，同一枚文件的
    两种写法互不相等 ⇒ 拿"明文 --eol"去比"`-z` 跟踪面"会当场全差、门假红。两侧同用 `-z`
    （git 在 `-z` 下不做引号转义）才是同一条口径，比较结果不受 quotePath 影响。
    """
    raw = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True,
                         check=True).stdout
    return [record.decode("utf-8", "replace") for record in raw.split(b"\0") if record]


def _index_eol_records() -> "list[str]":
    """`git ls-files --eol` 的原始记录面（每枚跟踪文件一条）。单独留接缝是为了能被反证台喂合成面。"""
    return _git_z_records("ls-files", "--eol", "-z")


def _tracked_paths() -> "list[str]":
    """`git ls-files` 的跟踪面（每枚跟踪文件一条），与 `_index_eol_records` 同用 `-z` 口径。"""
    return _git_z_records("ls-files", "-z")


def _index_eol_rows() -> "dict[str, str]":
    """解析 index 列，并**先钉住解析覆盖度**（规格 §6.4 / §16 卡 K）——这条是本族门的主判据。

    为什么覆盖度必须先于两条形状判据：`test_index_has_no_crlf_entries` 与
    `test_non_text_index_entries_are_exactly_the_enumerated_set` 只看"解析到的行里有什么"，
    对"解析到了哪些行"完全无感。卡 K 的实测形状是：`attr/` 列一开始含空格，`attr/\\S*` 就丢两行，
    而丢的两行都是 `i/lf` ⇒ 两条形状判据一个都不违反 ⇒ 门**绿着变瞎**。本枚断言不依赖"属性列
    长什么样"的任何假设，只看两个数：解析出的行数必须等于 `git ls-files` 的跟踪文件数。
    将来再出现同类丢行（换 git 版本、换列序、新字段带空格）同样是响亮地红，而不是静默收窄覆盖面。

    判据取"两道地板 + 逐条计数 + 路径集合"，缺一都不完整：
      * **非空地板**（N6 实测换来的，Task 6 修复轮 1）：跟踪面与解析面**都必须有东西**。
        等量判据两侧同空时成立在 `0 == 0` 上——那不是"面面俱到地一致"，那是这枚钉不再检查
        任何东西。变异台 N6 那一发的读数是：覆盖度钉放行、`test_index_has_no_crlf_entries`
        **空判绿**，只有 `i/-text` 枚举集合钉拦住（兜底链生效，但那证明的是"这一族的组合有牙"）。
        地板的红要说清是**钉哑了**，不能读成"仓库干净"——与 `test_eol_rules_are_a_no_op_for_the_current_tree`
        的 `assert checked`、卡 I (2) 的"tokenize 非空"、门 16 的"扫不到 `- name:` 即红"同族手法。
      * **逐条计数**（`len(parsed) == len(tracked)`）：抓"某一行整体没被读到"这一族，正是卡 K。
        计数按**记录条**而不是按字典条目算 —— 一枚路径在合并冲突态会在两侧各出现多枚 stage 条目，
        按字典条目比会把那种正常状态弄成假红（本仓库的账是"假红最贵"）。
      * **路径集合相等**（`missing` / `extra` 双向）：抓"读到了但读歪了"（比如属性列跨了 tab、
        把路径的前缀吃进列里）——那时条数仍是 313，只有集合会差。两边同时点名，失败信息给的就是
        缺/多的路径而不是一个数。等量+集合两条是**并判**的：只比条数会放走"条数相等但集合不同"那一形。
    """
    records = _index_eol_records()
    tracked = _tracked_paths()
    assert tracked, (
        "`git ls-files` 跟踪面一枚都没有 ⇒ 这枚解析覆盖度钉退化成了空判：它的绿不能读成"
        "『index 面与跟踪面一致』，只能读成『钉不再检查任何东西』（卡 K 的地板，N6 实测那一形）。"
        f"\n同一时刻的 `--eol` 记录面 {len(records)} 条；消费这份面的 "
        "`test_index_has_no_crlf_entries` 与 `test_non_text_index_entries_are_exactly_the_enumerated_set`"
        "也跟着失去覆盖面 —— 先弄清跟踪面是怎么收空的，再谈行尾干不干净")
    parsed: "list[tuple[str, str]]" = []
    unparsed: "list[str]" = []
    for record in records:
        row = _EOL_LINE.match(record)
        if row is None:
            unparsed.append(record)
            continue
        parsed.append((row.group(4), row.group(1)))
    rows: "dict[str, str]" = dict(parsed)
    assert parsed, (
        f"解析面一枚都没有 ⇒ 这枚解析覆盖度钉退化成了空判：红在『钉哑了』，不是红在『仓库干净』"
        f"（卡 K 的地板）。`git ls-files --eol` 记录面 {len(records)} 条、未解析 {len(unparsed)} 条、"
        f"跟踪面 {len(tracked)} 枚"
        f"\n未解析记录样本（前 5 条）：{[u[:120] for u in unparsed[:5]]}"
        f"\n最可能的那一形 = `_EOL_LINE` 的某一列认不了当前 git 的输出"
        f"（属性列跨空格/制表符、列序变了、新字段带空格）——它丢的恰好是行尾最敏感的那几枚文件")
    missing = sorted(set(tracked) - set(rows))
    extra = sorted(set(rows) - set(tracked))
    assert len(parsed) == len(tracked) and not missing and not extra, (
        f"行尾门的解析覆盖度掉了（卡 K 的那一形）：`git ls-files --eol` 共 {len(records)} 条记录、"
        f"正则解析出 {len(parsed)} 条（未解析 {len(unparsed)} 条），"
        f"`git ls-files` 跟踪面 {len(tracked)} 枚 ⇒ 两侧必须**逐条等量且路径集合相等**。"
        f"\n未解析记录样本（前 5 条）：{[u[:120] for u in unparsed[:5]]}"
        f"\n跟踪面有而解析面缺（前 10）：{missing[:10]}"
        f"\n解析面有而跟踪面无（前 10）：{extra[:10]}"
        f"\n不修好的代价：`test_index_has_no_crlf_entries` 与 "
        f"`test_non_text_index_entries_are_exactly_the_enumerated_set` 会在被丢掉的行上"
        f"保持绿色而实际不再检查它们——『门在场』不等于『门在跑』")
    return rows


def test_gitattributes_carries_the_required_rules():
    assert GITATTRIBUTES_FILE.is_file(), "没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定"
    rules = {line.strip() for line in GITATTRIBUTES_FILE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")}
    missing = [rule for rule in REQUIRED_GITATTRIBUTES_RULES if rule not in rules]
    assert not missing, f".gitattributes 缺必需规则：{missing}"
    binary = {rule.split()[0] for rule in rules if rule.endswith("binary")}
    assert set(REQUIRED_BINARY_RULES) <= binary, f"二进制扩展名没显式声明：{set(REQUIRED_BINARY_RULES) - binary}"


def test_index_has_no_crlf_entries():
    """`i/crlf` 必须为零。覆盖面由 `_index_eol_rows()` 的解析覆盖度钉担保（卡 K）。"""
    rows = _index_eol_rows()
    offenders = sorted(path for path, index_eol in rows.items() if index_eol == "i/crlf")
    assert not offenders, f"{len(offenders)} 枚文件的 CRLF 被提交进了 index（整文件 diff 的形状）：{offenders[:10]}"


def test_non_text_index_entries_are_exactly_the_enumerated_set():
    """`i/-text` 恰好三枚（形状钉，不是数量钉）。同样骑在覆盖度钉上：覆盖面一掉就先红（卡 K）。"""
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
        if suffix not in (".sh", ".ps1"):
            continue                                # 先看后缀再读字节：313 枚文件含二进制
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        body = path.read_bytes()
        if suffix == ".sh":
            checked += 1
            if b"\r" in body:
                offenders.append(f"{relative} 含 CR，但规则要求 eol=lf")
        else:
            checked += 1
            lf, crlf = body.count(b"\n"), body.count(b"\r\n")
            # 混合行尾的 .ps1 会被规则改写：只"有 CRLF"不够，必须**每一枚** LF 都在 CRLF 里。
            if lf != crlf:
                offenders.append(
                    f"{relative} 的 LF {lf} 枚 != CRLF {crlf} 枚 ⇒ 含裸 LF（混合行尾），"
                    f"但规则要求整文件 eol=crlf")
    assert checked, "`.sh` / `.ps1` 一枚都不在面上：这条 no-op 证明退化成了空判"
    assert not offenders, "加规则会改动工作树：" + "；".join(offenders)

#: B0-12 的区间化判据（独立终审 Important 2；用户 2026-09-30 裁定开工）。基线取 `security-a-rc1`
#: 那枚 commit 的 **sha 常数**而不是 tag 名：tag 按裁定不可变也不许移位，而浅签出能不能解析 tag
#: 取决于 runner 的 fetch 形态——钉 sha 把失败模式收敛成**一种**（"历史没取全"），而不是两种。
APP_SURFACE_BASE_SHA = "7cc5efc0460abb01171c20cee61ef01bf5282a3d"
#: 基线到 HEAD 之间 `backend/app/**` 上唯一被登记的改动：SEC-A-CORR-01（errata §5 的最小修正面）。
ALLOWED_APP_SURFACE_CHANGES = frozenset({"backend/app/identity/__init__.py"})


def test_the_app_surface_delta_since_the_sealed_base_is_exactly_the_registered_exception():
    """B0 不许动 `backend/app/**`；CORR-01 是**单独裁定**的一次 ⇒ 把这条区间钉成机器判据。

    为什么必须机器化：卡 J 那三子句原本是人做的审计，而它的第一子句
    `git diff --name-only HEAD -- backend/app` 减掉两枚 identity 后今天只剩用户自己的 README，
    对"这一串 commit 里 app 面只允许 CORR-01 那一处"**完全不设防**（独立终审实测并点名）。
    区间判据两个方向都红：多出未登记的 app 改动，或有人把已登记的例外从表里悄悄摘掉。
    """
    probe = subprocess.run(["git", "cat-file", "-e", APP_SURFACE_BASE_SHA + "^{commit}"],
                           cwd=REPO_ROOT, capture_output=True, text=True)
    if probe.returncode != 0:
        raise AssertionError(
            f"基线 commit {APP_SURFACE_BASE_SHA[:12]} 在本签出里不可解析 ⇒ 这枚门**哑了**，"
            f"绝不能读成『app 面没有改动』。修法在 CI 侧：`actions/checkout` 需要 "
            f"fetch-depth: 0（否则浅签出没有历史）。stderr: {probe.stderr.strip()[:200]}")
    listing = subprocess.run(["git", "diff", "--name-only",
                              APP_SURFACE_BASE_SHA + "..HEAD", "--", "backend/app"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
    assert listing.returncode == 0, f"区间 diff 取不到：{listing.stderr.strip()[:200]}"
    changed = frozenset(line.strip().replace("\\", "/")
                        for line in listing.stdout.splitlines() if line.strip())
    unexpected = sorted(changed - ALLOWED_APP_SURFACE_CHANGES)
    dropped = sorted(ALLOWED_APP_SURFACE_CHANGES - changed)
    assert not unexpected and not dropped, (
        f"app 面相对基线 {APP_SURFACE_BASE_SHA[:12]}（= tag security-a-rc1）的差集与登记表不符："
        f"未登记的改动 {unexpected}；被摘掉的例外 {dropped}。"
        f"登记表当前只许可 {sorted(ALLOWED_APP_SURFACE_CHANGES)} 一处（SEC-A-CORR-01）。"
        f"要新增改动请走一条有出处的修正单，并把那一枚加进 ALLOWED_APP_SURFACE_CHANGES——"
        f"**别把整条判据改成 allowlist 为空或干脆摘掉它**")


#: 17 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
#: 只遍历本模块的用例，对本文件被摘走任何东西都无感。
_OWN_TEST_NAMES = (
    "test_collected_count_matches_the_pinned_number",
    "test_the_gate_module_itself_is_collected",
    "test_the_gate_module_itself_carries_no_skip_or_xfail_decorator",
    "test_collection_measurement_counts_node_ids_not_the_summary_line",
    "test_backend_contracts_has_no_unittest_discover_step",
    "test_backend_contracts_runs_the_pytest_suite",
    "test_step_ordering_still_explains_itself",
    "test_install_face_uses_requirements_txt_as_the_source",
    "test_extra_pip_arguments_are_exactly_the_exemption_table",
    "test_install_face_pip_source_values_are_pinned",
    "test_every_exemption_row_states_why",
    "test_workflow_plain_scalars_bearing_a_colon_space_are_quoted",
    "test_gitattributes_carries_the_required_rules",
    "test_index_has_no_crlf_entries",
    "test_non_text_index_entries_are_exactly_the_enumerated_set",
    "test_eol_rules_are_a_no_op_for_the_current_tree",
    "test_the_app_surface_delta_since_the_sealed_base_is_exactly_the_registered_exception",
)

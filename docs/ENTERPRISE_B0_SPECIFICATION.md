# ENTERPRISE-B0 · 门禁地基规格（CI 收集面 / 单一 runner / 行尾确定性）

| 项 | 值 |
| --- | --- |
| 文档 | `docs/ENTERPRISE_B0_SPECIFICATION.md` |
| 状态 | **SPEC 草案（2026-09-28）**，待用户复核后冻结。本文档不伴随任何代码改动 |
| 上游 | `docs/ENTERPRISE_ACCEPTANCE_GAP_ANALYSIS.md`（新开 `G20`，并对 `G0` 出勘误卡，见 §16 卡 D） |
| 前置 | SEC-A 封版 `7cc5efc` + annotated tag `security-a-rc1`；Model Router V2.3 tag `model-router-v2.3-rc1`（**两枚 tag 均不触碰、不 amend、不移位**） |
| 范围裁定 | 企业验收框架的子规格 B 已按用户裁定拆为三张并串行：**B0 门禁地基 → B1 知识治理与摄取侧安全 → B2 评测与引用真实性**。本文档只管 B0 |
| 硬边界 | **B0 零 `backend/app/**` 语义改动**（用户裁定）。落盘键名脱敏、文档元数据、评测与引用真实性分别归 B1 / B2 |

---

## 1. 目的、范围、不做什么

**目的**：让"门"从"本地存在"变成"CI 收集并且真的会红"。B0 不新增任何安全语义，它修的是**判定能力本身**——在 SEC-A 收尾时已实测确认：SEC-A 六枚门文件里的 40 枚裸 `pytest` 函数中，CI 今天只用 pytest 跑 5 枚，其余要么走一枚收不到裸函数的 `unittest` 步，要么根本不跑。

**做**（四块，全部收口）：

1. **单一 runner**：`backend-contracts` 的收集/执行从 `python -m unittest discover` 换成 `python -m pytest backend/tests -q`，并删除 unittest 步。
2. **依赖同源**：安装清单从 YAML 里的手写包名，改为引用 `backend/requirements.txt` 本身（+ 一条 CPU-torch 发行源例外，理由见 §6.3）。
3. **收集面可判定**：新增一枚"收集数必须等于钉住常数"的门，消灭静默不收集。
4. **行尾确定性**：新增 `.gitattributes`，把归一化从"每台机器各自的 `core.autocrlf`"变成仓库属性；并钉住行尾形状。

**不做**（明确排除，防范围漂移）：

- 不改 `backend/app/**` 的任何一行（§10 的归因规则规定：改动它 = 越界）。
- 不做任何**全量行尾归一提交**，不改工作树字节，不触碰已封版工件（§4 B0-007）。
- 不碰 `knowledge_os.py` 那 8 处落盘写手的键名黑名单 → **B1**。
- 不做 lint / typecheck / pip-audit / gitleaks / bandit / OpenAPI 契约（`G0` 那行的其余缺项）→ 本框架任何一张都不做，另行排期。B0 只承诺"收集面完整"。
- 不拆 job（方案 2 已被否决，理由留在 §5.3 作为历史）。
- 不改 `backend-integration` / `backend-quality` / `frontend-build` 三个 job 的依赖形态与步骤。

---

## 2. 事实基线（2026-09-27/28 只读盘点，全部经实测）

> 行号会漂。凡引用 `ci.yml` 的内容，判据一律**认 step 名与内容，不认行号**（SEC-A §20.4 立的规矩，本规格沿用）。

| 事实 | 证据 |
| --- | --- |
| `backend/tests/` 恰有 **40 枚** `test_*.py`；另有 4 枚非 `test_` 前缀辅助模块（`conftest.py`、`sec_a_seed.py`、`sec_a_fixtures.py`、`real_llm_failover_kit.py`） | 逐文件枚举 |
| 形态分布：纯 `unittest.TestCase` **37** 枚、纯裸 pytest 函数 **1** 枚（`test_security_a_closure.py`）、混合 **1** 枚（`test_secret_hygiene_contract.py`：18 TestCase + 23 裸函数）、刻意默认收 0 枚 **1** 枚（`test_real_llm_failover_acceptance.py` 的 `REAL_LLM_ACCEPTANCE` 收集门） | 逐模块双 runner 计数 |
| **裸函数在 unittest 下枚枚不跑**：`TestLoader.loadTestsFromModule` 要求 `isinstance(obj, type)` 且是 `TestCase` 子类 ⇒ 模块级 `def test_*` 一律被挡 | `inspect.getsource(unittest.loader.TestLoader.loadTestsFromModule)` 逐字（宿主 CPython 3.13.7） |
| 收集差 `1316 − 1271 = 45 = 40`（裸函数）`+ 5`（一枚 6 case 的 `parametrize` 展开） | **逐位闭合，无残差** |
| **`Ran N tests` 不是收集数**：纯收集语义下两 cwd 都是 1271、`loader.errors = 0`；两 cwd 的 `Ran` 读数 1251 / 1271 之差来自 `subTest` 被中断 | `TestLoader().discover(...).countTestCases()` 单独复量 |
| 既有 unittest 步在 main 上**本就红**，且早于 SEC-A：裸 venv 0 包 `132 tests / 3 failures / 26 errors`；补齐轻量清单后反而 `11 failures / 160 errors` | `task-10i-ci-proof.txt` 第 1 节；远端 run `36295632046` 步骤读数（Install success、SECA-20 success、既有步 failure） |
| **该步一红，同 job 后续步永不执行**：Docker Compose 配置校验与 `scripts/deploy.ps1` pwsh 语法校验两步因此大概率从未跑过 | GitHub Actions 语义（一失败即止）+ `ci.yml` 注释自陈 |
| **pytest 已在 `backend-contracts` 清单里**（随 SECA-20 加入）。缺的是**重依赖**：`sentence-transformers`、`pymupdf`、`python-docx`、`ddgs`、`typesafe-sdk` 五包无任何 job 在该装 | `ci.yml` 安装步逐字 |
| 在该轻量清单形态下，**10 枚测试模块连 import 都过不去**（不是"跑不过"）：认证腿、改密、用量、V2.3 路由、口令生命周期、真 LLM 验收、`test_typesafe_*` 五枚、用户目录。（SEC-A 文档写的是"余下 5 枚契约文件"——那是按 SEC-A 自己的文件数口径说的，AST 闭包口径是 10 枚，含 V2.3/TypeSafe 期入库的模块。两数不冲突，但 **B0-01 用收集数把这类口径差一次性消解**：不再需要数"几枚文件受影响"。） | AST 模块级 import 传递闭包；瓶颈是 `app/store.py`、`app/retrieval.py`、`app/ingestion.py`、`app/web_search.py`、`app/typesafe_judgments.py:14` |
| `conftest.py` 模块级 import 面**只有标准库 + pytest**；真正把重依赖拉进来的是 **7 枚 session/function autouse 夹具**（`:703/:781/:804/:829/:842/:867/:902`） ⇒ **把 `app.*` 挪进函数体不能降依赖** | AST 逐字 |
| `uvicorn` 在 `backend/app/` 里只出现在 4 处注释，无运行时 import ⇒ 今天无危害；但若 B0 之后加"真起一次服务"的门就会立刻需要它 | `grep` 实测 |
| **`core.autocrlf = true`，全仓无 `.gitattributes`**。index 侧 **100% `i/lf`**（3 枚 `i/-text` 除外），工作树 168 LF-only / 120 CRLF-only / 24 MIXED / 1 无换行 ⇒ `git add` 一枚 CRLF 文件会静默改动其行尾表现 | `git ls-files --eol` 全量 + 逐文件字节扫描 |
| 3 枚 `i/-text` 中只有 `frontend/public/yaoke-logo.webp` 是真二进制；另两枚是 markdown：`docs/MODEL_ROUTER_V23_DESIGN.md` 含 **140** 个游离 CR 字节、`.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md` 含 **1** 个。两枚均无 NUL、UTF-8 可解码 | 字节级复量 |
| `SettingsConfigDict(env_file=".env")` 是**相对 cwd** 的路径 ⇒ `cwd=仓库根`（CI 形态）下 `backend/.env` 天然不被加载；`cwd=backend` 下被加载。宿主 `backend/.env` 真实存在且被 gitignore | `backend/app/config.py:8` |
| 宿主解释器 3.13.7，CI `python-version: '3.12'`，发布容器内 3.12.14 | 三处实测 |
| SECA-20 扫描器**读工作树文件**、只按扩展名跳过二进制、`errors="ignore"` ⇒ `.gitattributes`（只改 index 归一化、而 index 已全 LF）**不改变扫描面** | `test_secret_hygiene_contract.py` 的 `_hit_counts` / `_delivery_surface_names` |
| SECA-20 那枚 `-k` 子集实测选中 **5 / 46** | `--collect-only` 读数 |
| 用户裁定（2026-09-28）：B0 验收线 = **换成 pytest 且 backend-contracts 全绿**；`.gitattributes` **只加规则不做全量归一**；落盘脱敏归 B1 | 本会话三条拍板 |

---

## 3. 失效模型（B0 的靶区不是攻击者，是"门自己骗自己"）

不叫威胁登记，因为 B0 没有新增被攻击的面。

| ID | 失效方式 | 现状 | B0 的对策 |
| --- | --- | --- | --- |
| F1 | **静默不收集**：runner 形状决定某些测试永不执行，而 job 仍是绿的 | 已实证（40 枚裸函数） | §6.1 收集数钉 + §6.2 单 runner 钉 |
| F2 | **手写清单漂移**：CI 的依赖清单与 `requirements.txt` 是两份真相，加包时 CI 静默落后 | 已实证（`f6c67b5` 远端 `ModuleNotFoundError: httpx`；今天 10 枚模块 import 不过） | §6.3 依赖同源钉 + 豁免表 |
| F3 | **恒红步掩盖后续步**：一枚永不通过的门让排在它后面的门全部不跑 | 已实证（compose 校验与 pwsh 语法校验大概率从未执行） | §5.2 顺序 + §11 B0-10 首次起跑结论 |
| F4 | **本地绿 ≠ CI 绿**：`.env` 存在性、cwd、解释器版本三项环境差 | 部分实证（两 cwd 的 8F/113E ↔ 17F/8E 翻转） | §8 四格复量规程 + §4 B0-008 远端权威 |
| F5 | **行尾由机器决定**：`core.autocrlf` 是每台机器的设置，不是仓库属性 | 已实证（index 全 LF、工作树三态并存、143 枚文件在归一化边界上） | §7 规则 + §6.4 形状钉 + no-op 判据 |
| F6 | **门存在但只是纸门**：门禁写在测试里却没有被任何收集器看见 | 已实证（SEC-A 六枚门文件里 CI 只跑 5 枚） | 本规格整体 |

---

## 4. 冻结不变量

- **ENTER-B0-001** `backend-contracts` 的测试收集/执行**只能有一个 runner**，且必须是 pytest。`unittest discover` 在该 job 内不得存在（§6.2）。
- **ENTER-B0-002** 收集面必须**可判定且被钉住**：pytest 收集数 == 显式常数；不等即红。**禁止**用 unittest 的 `Ran N` 作为收集数（§2 已证它混入了执行中断）。
- **ENTER-B0-003** CI 依赖必须与 `backend/requirements.txt` **同源**。YAML 内不得出现逐包版本清单；唯一豁免是 §6.3 那枚 CPU-torch 发行源行，且豁免以"表 + 处数 + 理由"的形状钉登记（沿用 SEC-A `EXEMPTIONS` 的设计，不另起一套）。
- **ENTER-B0-004** B0 的最终 diff 对 `backend/app/**` **必须为空**。这是一枚可审计的结构判据（§11 B0-12），不是口头承诺。
- **ENTER-B0-005** 不得以"删测试 / 降断言 / 加 skip"求绿。既有 unittest 形态断言若有任何 pytest 下不等价的能力，必须先有等价物再切换。判据：切换前后 `passed` 总数只增不减，且 §6.1 的常数按实测上调而非下调。
- **ENTER-B0-006** 行尾归一化必须是**仓库属性**：`.gitattributes` 存在且含 §7 的必需规则；`git ls-files --eol` 不得出现 `i/crlf`；`i/-text` 集合必须等于 §6.4 枚举的那 3 枚（漂移即红——这条同时钉住"又来一枚游离 CR 的文件"）。
- **ENTER-B0-007** B0 的 `.gitattributes` 必须是**可证明的 no-op**：加入前后 `git status --porcelain` 输出**逐行相同**、`git diff` 为空、无任何工作树文件字节变化。注意基线本来就不干净（`backend/app/identity/README.md`、`__init__.py` 两枚未提交改动是飞书对接留下的），所以判据是"与基线相同"，**不是**"干净"——写成"干净"会让 T4 红在别人留下的改动上。做不到 no-op 就不进仓。
- **ENTER-B0-008** "全绿"的权威**只能是远端 run 的 step 级读数**。本地复量是必要非充分。禁止以"本地过了所以 CI 应该过"结案（`f6c67b5` 就是这么被打脸的）。

---

## 5. CI 目标形态

### 5.1 `backend-contracts` 的步骤序列（唯一权威形状）

```
1  actions/checkout@v4
2  actions/setup-python@v5            python-version: '3.12'
3  pip cache                          actions/cache@v4，key = hashFiles('backend/requirements.txt') + python 版本 + "cpu-torch"   ← 临时项，见下
4  Install backend dependencies       python -m pip install --disable-pip-version-check torch --index-url https://download.pytorch.org/whl/cpu
                                      python -m pip install --disable-pip-version-check -r backend/requirements.txt
                                      python -m pip install --disable-pip-version-check pytest
5  Run SECA-20 delivery-surface secret scan      （命令原样保留，位置不变）
6  python -m compileall -q backend/app scripts
7  python scripts/validate_demo_assets.py
8  Run backend contract suite         python -m pytest backend/tests -q
9  Validate Docker Compose configuration        （cp backend/.env.example backend/.env; docker compose config）
10 Validate Windows deployment script syntax    （shell: pwsh）
```

step 3 的 pip cache 是**临时项**：它的存废由 B0-13 的耗时读数决定。装上全量依赖后这个 job 从 ~20 秒变成分钟级，cache 是唯一让它保持可用的手段；但若实测命中率低（`requirements.txt` 很少改，应该会高），或者它引入"本地与 CI 装到的包不完全同一份"这类新的不等价，那就删掉它——**速度不值得拿等价性换**。

### 5.2 顺序的两条不可回退理由（必须写进 YAML 注释）

1. **SECA-20 保持在主门之前**：成本为零，收益是 step 8 万一红，扫描门照样已报。SEC-A 立这条时针对的是"恒红步吞掉后续步"；B0 之后 step 8 不再恒红，但**顺序不需要反过来**——反过来没有收益，却有回归风险。
2. **step 9/10 保持在最后**：它们是 B0 之后**第一次真正被执行**的门。把它们放前面会让 B0 的失败归因多一个变量；放后面则一旦 step 8 红，它们本轮不出结论，符合"一次只引入一个变量"。

### 5.3 被否决的方案（留档，防重提）

- **拆 light / full 两 job**：需要一个显式 `--ignore` 清单，即又一份会漂移的、漂移后**静默不收集**的手写真相；要兜住得加跨 job artifact + "两 job 收集数之和 == 常数"的门。B0 的目的就是消灭静默不收集，不能用自己的手段反造一个。
- **只补那 5 个缺包**：`f6c67b5` 是这条路的实证失败——手写清单不等于实测集合。

---

## 6. 四枚门的规范

宿主文件：`backend/tests/test_ci_gate_contract.py`（B0 唯一新增测试文件）。四枚门都必须是**被 B0 自己那枚 pytest 步收集**的——否则就是 F6 的现行犯。

### 6.1 收集数钉

- 量法：`cwd = 仓库根`，`python -m pytest backend/tests -q --collect-only`，统计匹配 `^backend/tests/[^:]+::` 的**行数**。
- **禁止**解析尾行统计文句（`N tests collected`）——那是给人读的，形状会变。
- 判据：`实际 == _EXPECTED_COLLECTED`。常数在 spec 冻结后的第一枚任务里重取并写入，同时写进验收文档，两处必须一致（双写互校）。参考值：2026-09-28 本地实测 **1316**。
- 失败语义：不等即红，红面必须打印"多出的/缺失的 node id 集合差"，不能只报两个数——否则排查要重跑一遍。
- **自我存续子钉（不可省）**：本门还必须断言"`test_ci_gate_contract.py` 自身在收集面上、且其被收集枚数 > 0"，**不依赖常数**。它抓的是"门还在场但被 `skip` / 被 marker 摘空 / 常数值被人凑"这一类——这些情况下总数可能不变，只有"门自己贡献了几枚"会变。它**抓不到**"门自己被改名/删除"，那是不可消除的自指盲区，见 §14 L6。

### 6.2 单 runner 钉

- 断言 `backend-contracts` 的 steps 中：不存在任何 `run` 含 `unittest discover`；且存在至少一枚 `run` 含 `python -m pytest backend/tests`。
- 认 step 内容不认行号。其他 job（`backend-integration` 跑 `scripts/*.py`）不在本钉口径内，**不得**被顺手扩管。

### 6.3 依赖同源钉

- `backend-contracts` 的安装面必须包含 `-r backend/requirements.txt`。
- 该 job 内除 requirements 引用外，允许出现的其它 `pip install` 参数**恰好等于豁免表**：
  - `pytest` —— 测试运行器，不是应用依赖，不该进 `requirements.txt`；
  - `torch --index-url https://download.pytorch.org/whl/cpu` —— 不是新增依赖（`sentence-transformers` 的传递依赖），只是**发行源选择**，避开默认 CUDA wheel（~2.5 GB vs ~200 MB）。
- 豁免表形状沿用 SEC-A 的 `dict[str, tuple[int, str]]`（键 → 处数 → 为什么）。**多一处、少一处、或改了理由，都红**。这条是 §5.3 那个否决理由的结构化防线：否则下次有人为了省 2 分钟把包名抄回 YAML，B0 的全部意义蒸发。

### 6.4 行尾钉

- `.gitattributes` 必须存在，且必须含 §7 列出的每一条必需规则（逐条字符串匹配，不做"差不多就行"）。
- `git ls-files --eol` 输出里：`i/crlf` **计数必须为 0**；`i/-text` 的文件集合必须恰等于
  `{.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md, docs/MODEL_ROUTER_V23_DESIGN.md, frontend/public/yaoke-logo.webp}`。
- 这条是**形状钉**而不是数量钉：集合相等，才能同时抓到"新来一枚游离 CR 文件"和"有人把某枚强转成文本"。
- **解析覆盖度本身是判据**（B0-T4 之后实测补入，见 §16 卡 K）：`git ls-files --eol` 的每一行都必须被门读到，
  即"解析出的行数 == `git ls-files` 的行数"，不等即红。理由不是洁癖——`attr/` 列在规则生效后会含空格
  （`attr/text eol=lf`），按 `\S*` 抽列的解析器会**静默丢行**，而丢掉的恰好是被 `eol=` 规则管着的那几枚文件。

---

## 7. `.gitattributes` 规范

```gitattributes
# 归一化由仓库决定，不由每台机器的 core.autocrlf 决定。
* text=auto

# 进镜像/进 Linux 执行的文件必须是 LF：CRLF 的 .sh 在容器里直接跑不起来。
*.sh text eol=lf

# Windows 部署脚本按 Windows 形态签出。
*.ps1 text eol=crlf

# 真二进制。显式声明，不靠 git 猜。
*.png binary
*.jpg binary
*.jpeg binary
*.webp binary
*.ico binary
*.gif binary
*.woff binary
*.woff2 binary
```

三条设计决定，都要在 spec 评审时被看见：

1. **不给 `*.py` / `*.md` / `*.yml` 加 `eol=`**。只加 `text=auto` 就已经把"check-in 归一化"从机器属性变成仓库属性（这是 §2 里那枚真危害——Linux 默认 `autocrlf=false` 的人把 CRLF 字节提交进 index——的根因）。而给 `*.py` 加 `eol=lf` 会改变 120 枚 CRLF 工作树文件的签出形态，属于 B0 明令禁止的全量归一。
2. **不强行处理那两枚含游离 CR 的 markdown**。加 `*.md text` 会把 `docs/MODEL_ROUTER_V23_DESIGN.md`——一枚**已封版**的 V2.3 工件——在 index 里改字节。B0 不改它。它的存在由 §6.4 的 `i/-text` 形状钉管住：不静默、不扩多、但也不动。
3. **`eol=lf` / `eol=crlf` 两条对当前树是零影响**（实测 `.sh` 仅 1 枚且已是 LF、`.ps1` 仅 1 枚且已是 CRLF），所以 §4 B0-007 的 no-op 判据可满足。
4. **本块的空格是判据的一部分**。§6.4 的门按 `line.strip()` 比**整行字符串**，只剥首尾、不折内部空白——`*.sh` 与 `text` 之间多打一个空格就会当场红。上稿这里就多了一个空格（B0-T4 实现时按门的形状改正并回指本规格）。因此：**不许为了排版把这几行对齐成列**；要改排版必须先改门，而门的形状归 §6.4 管。
   同一轮实现还纠正了取证手法的一处假绿：对**未跟踪**文件跑 `git diff --exit-code <file>` 恒返回 0（git 根本不看它），还原证明必须用逐字节 `cmp`，不能用 `git diff`。§9 与 §12 里任何"还原一致"的取证都按此口径。

---

## 8. 本地 / 远端等价复量规程

B0 之后"门在 CI 跑"是全部价值所在，因此**等价性本身要被证明**，不能被引用。

### 8.1 四格复量矩阵（必做）

`{cwd = 仓库根, cwd = backend}` × `{backend/.env 在场, backend/.env 移开}`

- 每格记录：收集数、`passed` 数、`failed/error` 明细。
- "移开"= **挪出仓库**到一次性目录（`HOLD="$(mktemp -d)"; mv backend/.env "$HOLD/env"`），跑完还原并逐字节确认还原一致。**禁止在仓库内改名**（`.env.bak` / `env.bak` 都不行），禁止删除。
  理由见 §16 卡 F：`.gitignore:6` 是精确路径 `backend/.env`，就地改名的产物会作为"未忽略的 untracked"落进 SECA-20 扫描面，把两枚钉子当场拖红——那既是测量污染，也是被误读成 `.env` 维度有差异的唯一途径。
- 已实测事实使这一格变轻：`env_file` 是相对 cwd 的路径 ⇒ CI 形态（仓库根）本就不加载 `backend/.env`。所以本规程的目的不是"发现差异"，而是**把这份安全从巧合升级为被声明的条件**。
- 解释器版本差（宿主 3.13.7 / CI 3.12）不在四格内消解，改由 §8.2 消解。

### 8.2 容器内第三格（强烈推荐，成本已降为一次性）

发布镜像内已有 Python **3.12.14**（SEC-A 容器基准实测所用量测环境）。B0 应在该容器内以 CI 同形态（`cwd=/app`、无 `.env`）跑一次全量 pytest。这样"CI 版本上的等价"有一格真读数，而不是赌 3.12→3.13 无差。

### 8.3 远端往返（权威判据）

同 commit 的本地读数与远端 step 读数必须**逐位相同**（B0-03）。任一不符 ⇒ 先归因（版本 / cwd / env / 依赖 / OS），不许"本地过即通过"。

---

## 9. 反例证明（变异台）

沿用 SEC-A 做法：`.superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py`，逐发"植入 → 确认对应门红 → 还原 → 确认绿"，带字节安全 `--check` 模式（还原后与基线逐字节比对）。至少五发：

| 变异 | 必须让它红 |
| --- | --- |
| 植入一枚既有测试模块使其脱离收集（改名成不以 `test_` 开头，例如 `test_web_security.py` → `web_security_hidden.py`）——这正是 F1 的机制本身 | §6.1 收集数钉 |
| 把 `unittest discover` 步加回 `ci.yml` | §6.2 单 runner 钉 |
| 把安装步换成手写包名清单（模拟"以后有人图省事"） | §6.3 依赖同源钉 |
| 在豁免表里偷偷多留一个包名 / 删掉某条理由 | §6.3 豁免表形状钉 |
| 删除 `.gitattributes` 的某一条必需规则 | §6.4 行尾钉 |

**每一发都要有"确实变红"的输出留档**。SEC-A 的教训：先证明门会红，才有资格说门在工作。

---

## 10. 允许触碰面与失败归因规则

### 10.1 白名单（穷举）

| 允许 | 用途 |
| --- | --- |
| `.github/workflows/ci.yml` | §5 的形态改造 |
| `.gitattributes`（新） | §7 |
| `backend/tests/test_ci_gate_contract.py`（新） | 四枚门的宿主 |
| `backend/tests/**`（既有） | 测试自身的 cwd / 相对路径 / `.env` 依赖缺陷——这是 B0 的靶区 |
| `docs/**`、`.superpowers/sdd/ENTERPRISE_B0/**` | 规格、计划、台账、验收 |

### 10.2 禁止

`backend/app/**`、`frontend/**`、`scripts/**`、`docker-compose.yml`、`backend/requirements.txt`（它是真源，B0 只引用不修改）、两枚既有 tag。

### 10.3 step 8 变红时的三分法（唯一合法出路）

1. **收集 / 依赖 / cwd / env 形态问题** → B0 靶区，改白名单内的文件。
2. **测试自身缺陷**（相对路径、`.env` 依赖、subTest 中断掩盖、断言写死了本机形态）→ 允许改 `backend/tests/**`，但每处必须留下"这条为什么这样钉"的一行说明；禁止把断言改弱（§4 B0-005）。
3. **暴露出的是 app 语义缺陷** → **停止**。登记到本规格 §14 与 B1/B2 队列，出一张 §16 格式的修订卡，**不在 B0 修**。

> 为什么这条必须写死：step 8 一红的瞬间，最省事的出路就是改一行 app 代码。B0 的全部纪律价值就在这一步上。

---

## 11. 判据矩阵

状态只允许 `GREEN / PENDING_EXTERNAL / BLOCKED`。

| ID | 判据 | 执行位置 |
| --- | --- | --- |
| B0-01 | pytest 收集数 == 钉住常数 | 本地两 cwd + 远端 |
| B0-02 | 远端 `backend-contracts` **整个 job** success（step 级读数入档，非单步） | 远端 |
| B0-03 | 同 commit 的本地与远端收集数逐位相同 | 本地 + 远端 |
| B0-04 | §8.1 四格全绿，且 `.env` 还原后逐字节一致 | 本地 |
| B0-05 | 单 runner 钉绿 | 本地 + 远端（门自身被收集） |
| B0-06 | 依赖同源钉绿（含豁免表形状） | 本地 + 远端 |
| B0-07 | `.gitattributes` 的 no-op 性：前后 `git status --porcelain` **逐行相同**（基线本就带两枚 identity 未提交项，见 §4 B0-007）、`git diff` 空、工作树无字节变化 | 本地 |
| B0-08 | 行尾钉绿：无 `i/crlf`；`i/-text` 集合 == 枚举 3 枚 | 本地 |
| B0-09 | SECA-20 扫描门豁免表零漂移（复量 SEC-A 封版读数：258 文件 / 16 命中 / 31 处） | 本地 |
| B0-10 | Docker Compose 配置校验、`deploy.ps1` pwsh 语法校验两道**首次真起跑**各有明确 GREEN/FAIL 结论 | 远端 |
| B0-11 | §9 五发变异逐发红 + `--check` 还原一致 | 本地 |
| B0-12 | `backend/app/**` 未被 B0 改动。**判据不是"列表为空"**（§4 B0-007 已声明基线本就带两枚 identity 未提交项）。**卡 G 的第一子句在落地时被证伪**（见卡 J）：`security-a-rc1` 就是 HEAD，那两枚未提交改动本身就会出现在 diff 里。现行判据三条：① `git diff --name-only HEAD -- backend/app` **减去那两枚 identity 文件**后为空；② `git diff --cached --name-only -- backend/app` 为空；③ 两枚 identity 文件的 sha256 与 **B0-T1 记录的基线值**逐字符相同 | 本地 |
| B0-13 | 全量 pytest 的 CI 耗时读数入档，pip cache 取舍有证据 | 远端 |
| B0-14 | `G20` 新开 + `G0` 勘误卡落档 | 文档 |
| B0-15 | （§8.2）容器内 3.12 形态那一格有读数 | 本地容器 |

---

## 12. 验收证据面

- 远端：`gh run view <id> --json jobs,name,url` + `--log` 的 step 名与结论逐条留档（run id、commit sha、时间）。SEC-A 已确立这条：只有本地读数不足以封版。
- 本地：每次全量跑记录 `collected / passed / failed / errors / subtests`，并注明 **cwd 与 `.env` 状态**——不带这两项的读数字格在本项目已被证明不可跨会话复用。
- 禁止出现的措辞："应该绿""理论上等价"。判据未取到读数即 `BLOCKED` 或 `PENDING_EXTERNAL`，不得写 `GREEN`。

---

## 13. 任务切分与排期

| 任务 | 内容 | 依赖 |
| --- | --- | --- |
| B0-T1 | 基线复量：收集数、四格 `.env`/cwd、耗时读数；冻结 §6.1 常数 | — |
| B0-T2 | 写 `test_ci_gate_contract.py` 四枚门 —— **此时它们必须红**（ci.yml 尚不合规），这是 TDD 的红相 | T1 |
| B0-T3 | `ci.yml` 形态改造（cache + 同源安装 + pytest 步 + 顺序注释写明理由） | T2 |
| B0-T4 | `.gitattributes` 落地 + §6.4 转绿 + B0-07 no-op 证明 | T2 |
| B0-T5 | B0-09 扫描面漂移复量 + 全量回归 | T3,T4 |
| B0-T6 | 变异台五发 + `--check` | T5 |
| B0-T7 | 远端往返 + 验收文档 `docs/ENTERPRISE_B0_ACCEPTANCE_<封版当日日期>.md`（命名沿用 SEC-A 的 `SECURITY_A_ACCEPTANCE_2026-09-26.md` 惯例，日期在封版时确定） | T6 |

**B0-T7 内含两道需要显式授权的闸**：`push`（远端往返必须推）与 commit 本身。按既定规矩，未到那一步不擅自推、不擅自提交。

体量：7 枚任务，无 app 依赖变更，无镜像重建。

---

## 14. 已知限制（B0 不消解，登记）

- **L1** 宿主 3.13.7 与 CI 3.12 的差，B0 只能靠 §8.2 那一格部分覆盖；不做双版本本地 CI。
- **L2** 两枚含游离 CR 的 markdown（140 与 1 处）留在 `i/-text` 状态。来源未查（B0 不改文件），"游离 CR 从哪来"登记为 B1 前的独立小条目。
- **L3** `uvicorn` 仍无任何 job 安装。今天无危害（无运行时 import），但"真起一次服务"的门一加就会立刻需要它。
- **L4** B0 之后 lint / typecheck / pip-audit / gitleaks / OpenAPI 契约仍然没有——`G0` 那行的其余缺项不因 B0 而声称完成。
- **L5** `unittest` 形态的 subTest 中断掩盖（§2 的 `Ran` 读数不可信）在切换后自然消失，但历史文档里那些 `Ran 132 / 11 failures / 160 errors` 类读数从此不可与新读数混读，需按 §16 卡 D 的方式标注口径切换点。
- **L6** **自指盲区不可消除**：一枚门无法证明"自己没有被人从收集面上摘掉"。§6.1 的自我存续子钉只抓"门在场但哑了"（skip / marker / 凑常数），抓不到"门被改名或删除"。现有缓解只有两条，都不如机器化：常数**双写**（门里 + 验收文档里，任一处改动在评审时是可见 diff）、以及任何触碰 `backend/tests/**` 的评审默认看收集数读数。**不把它写成"已解决"**。
- **L7** B0 之后 CI 的收集数会**第一次包含那 40 枚裸函数**。如果其中有在 Windows/宿主形态绿、在 ubuntu/3.12 形态红的用例，B0 的时间线会被一轮真实修复拉长。这不是设计缺陷，是 B0 存在的理由被验证的瞬间——但它意味着**不能**用"SEC-A 实测两 cwd 全绿"来预判 B0 全绿，B0-02 只能靠远端读数结。
- **L8（B0-T5 容器格实测）** 开区间依赖（`fastapi>=0.115,<1`、`PyJWT` 无版本钉）会让"同一份 `requirements.txt`、不同时间安装 = 不同解析结果"。本轮已实证一次后果：`fastapi 0.141.1` 在顶层 `app.routes` 多挂 `_IncludedRouter`，使一枚 SEC-A 覆盖门**静默失明 27/48 条服务腿**。B0 修的是症状（枚举改为递归），**没有修债**：依赖解析仍不可复现。真债归 B1 的依赖策略（锁文件 / 上界 / 解析可复现性），本规格不许把它写成"已解决"。
- **L9（同上实测）** 套件 warning 总数**不是跨环境绝对量**：宿主 `JWT_SECRET` 31 字节触发 34 枚 PyJWT `InsecureKeyLengthWarning`，容器同一枚默认值 45 字节则不触发 ⇒ `36 vs 2`。因此 B0 不建立"远端应等于本机 36"这类门。若将来要为 warning 建门，只允许两种形态：同一 job 内取 before/after **差值**，或先把 `JWT_SECRET` 的长度与类别钉死再取绝对数。

---

## 15. 交接口（B0 交给 B1 / B2 的东西）

- **给 B1**：任何新进 `backend/tests/` 的门都会被 CI 收集 ⇒ B1 的摄取侧扫描/PII/元数据门不再需要自己论证"能不能被跑到"。B1 同时接手：`knowledge_os.py` 那 **8 枚调用点 / 6 份持久化文件**（`document_registry.json`×3、`failure_triage.json`、`ingestion_jobs.jsonl`、`feedback.jsonl`、`access_requests.jsonl`、`eval_runs.jsonl`）从形态脱敏切到 `redact_for_persistence` 键名域，并把 SEC-A 那枚"AST 等式钉"的常数从 4 推到 6。
- **给 B2**：单一指标实现的前提（一套 runner、一份依赖清单）；以及 B2 的评测门若需要 `pytest` fixture/参数化，不再面临"unittest 收不到"的坑。
- **给框架**：`G20` 编号与 `G0` 勘误，后续任何"我加了个门"的声称都必须先回答"它被哪一步收集"。
- **给 B1 的依赖策略（L8/L9 的债主）**：B0 让 CI 第一次真跑全 1332 枚，代价是把"开区间依赖 + 不可复现解析"从潜在问题变成**已经咬过一次**的问题（`_IncludedRouter` 使覆盖门失明 27 腿；warning 总数随 env 长度漂移）。B1 需要回答的是解析可复现性（锁文件 / 版本上界 / 安装面与运行面同源），以及**要不要**为 warning 建门——若建，只允许同 job 内 delta 或先钉 `JWT_SECRET` 形态再取绝对值。B0 明确不替它决定，也不把症状修好写成债已清。

---

## 16. 修订卡（五段式：原规格 → 实测反例 → 修订后的规范 → 判据是否变化 → 对应回归证据）

> 本项目惯例：**判据一律不降**。九张卡：A–C 是事实/计量口径更正，D 是新开条目，E 是 B1 的输入，
> **F 是取证手法更正（判据未变）**，**G 是本规格内部两节自相矛盾的对齐（判据收紧）**，
> **J 是 G 的第一子句在落地时被证伪后的再修正（等价但可满足）**，**K 是 B0 自己的交付物把门看瞎（判据收紧）**。
> **F 是取证手法更正（判据未变）**，**G 是本规格内部两节自相矛盾的对齐（判据收紧）**。

**卡 A —— "CI 缺依赖"**
- 原规格：本会话前段口头结论"CI 现在既缺依赖也缺 runner 形态"。
- 实测反例：`ci.yml` 安装步含 `pytest`；缺的是 `sentence-transformers` / `pymupdf` / `python-docx` / `ddgs` / `typesafe-sdk` 五包。
- 修订后规范：§2 与 §6.3 的表述——"pytest 在场但只跑 5 枚；缺重依赖导致 10 枚模块 import 不过"。
- 判据变化：无（更准，不更松）。
- 回归证据：§11 B0-01 / B0-06；§9 第 3 发变异。

**卡 B —— "5 份持久化文件"**
- 原规格：SEC-A 收尾记录"`_write_json` / `_append_jsonl` 共 8 枚调用点、5 份持久化文件"。
- 实测反例：目标路径去重后是 **6** 枚（`document_registry.json` 被 3 处写）。
- 修订后规范：§15 的枚举。
- 判据变化：无；B1 的等式钉目标值由 5 改 6，是**扩面**。
- 回归证据：B1 承接（本规格不含）。

**卡 C —— "conftest 模块级 import 导致远端 httpx 红"**
- 原规格：`e5ff798` commit message 与 SEC-A 验收文档 §SECA-20 行写作"module-level import"。
- 实测反例：`conftest.py` 模块级只有标准库 + `pytest`；`sec_a_seed.py` 模块级也没有 `app.*`。真正把 `httpx` 拉进来的是 7 枚 autouse 夹具的**首次发射时点**。
- 修订后规范：§2 那行——"收集期危害不在 import 期，在第一枚测试的 fixture 期 ⇒ 挪 import 进函数体无效"。
- 判据变化：无；反而封掉了一条看似可行的偷懒路线。
- 回归证据：§11 B0-06（依赖同源钉让"少装一包"当场可红）。

**卡 D —— `G0 工程` 那行的"已有测试"**
- 原规格：`docs/ENTERPRISE_ACCEPTANCE_GAP_ANALYSIS.md` 的 `G0` 行把 `python -m unittest discover` 计入"已有 build/测试/真BGE门禁/前端构建"。
- 实测反例：该步枚枚收不到裸函数（§2 的 45 枚差），且它在 main 上本就红，红到吞掉后面两步。"有测试步"≠"测试被收集"。
- 修订后规范：新开 **`G20 门禁收集面与行尾`**，覆盖收集面完整性、runner 单一性、依赖同源、行尾确定性；`G0` 行改为"有测试步，但收集面不完整 → 见 G20"。
- 判据变化：无（新增判定面）。
- 回归证据：§11 B0-14 + 全张矩阵。

**卡 E —— "payload 仅 8 字段"**
- 原规格：`G1` 行"payload 仅 8 字段（`ingestion.py:162`）"。
- 实测反例：解析键 4（`content` / `page` / `chunk_index` / `section_title`）+ 富化键 6 = **10**。另需补一条：同一份富化字面量在 `ingestion.py:162-173` 与 `knowledge_os.py:226-237` 各写一遍（两条摄取路径、两份真相）。
- 修订后规范：`G1` 改 10 字段并登记"双份富化字面量"。
- 判据变化：无；这是 B1 的输入，不属 B0。
- 回归证据：B1 承接（本规格不含）。

**卡 F —— §8.1 的"就地改名躲一下"**
- 原规格：§8.1 规定四格复量里"移开 `backend/.env`"的做法是**仓库内**改名 `.env` → `env.bak`，跑完还原。
- 实测反例：B0-T1 首跑，`cwd` 两格"无 `.env`"各 `2 failed`，红的是 `test_repository_tracked_files_hold_no_credential_material`（`test_secret_hygiene_contract.py:626` 那族）与豁免表对账枚 `test_the_exemption_table_matches_the_hit_set`（`:635`）——`.gitignore:6` 是**精确路径** `backend/.env`，`env.bak` / `.env.bak` 两种写法都躲不过 ignore 判定（`git check-ignore` rc=1），于是它作为"未忽略的 untracked"进入 SECA-20 扫描面（`_delivery_surface_names()` 的 `git ls-files -z --cached --others --exclude-standard`）。把 `.env` 挪出仓库复量，两格同回 `1316 passed / rc=0` ⇒ **`.env` 维度中性，红纯由测量残留**。
- 修订后规范：§8.1 改为"必须挪出仓库到 `mktemp -d`，还原后断言 `git status --porcelain` 与基线逐行相同"；并升格为计划的全局约束，管住一切"为了测一次而把文件从树里藏起来"的动作（含 Task 5 的植入-复绿证据）。
- 判据变化：**判据一字未降**（四格仍要求 `1316 passed / 0 failed`）。变的是取证手法。附带采入一条正向证据：扫描门对"交付面里多一枚文件"确实敏感且归因正确，这是 B0-09 想要的性质，不是缺陷。
- 对应回归证据：`task-1-report.md` 修复轮 1（四格等读 + 复原校验 + 敏感性复验三段）。

**卡 G —— §4 B0-007 与 §11 B0-12 自相矛盾**
- 原规格：§4 B0-007 写明"基线本来就不干净（两枚 identity 未提交项），判据是与基线相同而非干净"；§11 B0-12 却仍要求"`backend/app/**` 的 diff 为空"，且把"已暂存未提交 ∪ 未跟踪"也算进必须为空的并集。
- 实测反例：按 B0-12 字面跑，`git status --porcelain -- backend/app` 必然列出那两枚 identity 文件 ⇒ B0 一执行到最后一条判据就红在**不属于 B0** 的改动上；而把它"消掉"最省事的动作恰好是把那两枚提交掉——一条判据自己把越界诱惑造了出来。这是同一轮修订里我只改了一处、没改另一处造成的，性质上属于**我自己的编辑失配**，不是规格的原始判断。
- 修订后规范：B0-12 拆成两条可分别证伪的判据——已跟踪侧（`git diff --name-only security-a-rc1 -- backend/app` 与 `git diff --cached --name-only -- backend/app` 皆空）+ identity 两枚的 sha256 必须等于 B0-T1 记录的基线值。"未跟踪"不再是判据项，因为 B0 在 `backend/app/` 下不新建任何文件，这一维由白名单本身保证。
- 判据变化：**收紧**。原来"列表为空"看着更严，实际是**不可满足**因而等于失效；现在的 sha 对照既可满足又能真的抓到"B0 偷改了 app"。
- 对应回归证据：B0-T1 已在报告里记下两枚基线 sha（`3bc681bbc52c` / `2cfab9f18182`，评审独立复核一致，并以 mtime 佐证未触碰）；B0-T5 Step 4 按新口径复量。

**卡 H —— §6.1 "被 marker 摘空"这半句是错的**
- 原规格：§6.1 自我存续子钉声称能抓"门还在场但哑了（被 `skip` / 被 marker 摘空 / 常数被人凑）"。
- 实测反例：B0-T2 独立评审在树外夹具上量过 `@pytest.mark.skip`、`@pytest.mark.skipif`、`@unittest.skip` 三种——
  `--collect-only` **照样打印它们的 node id**（4 枚、rc=0）。所以对任意一枚门加 `skip`，枚数不变、
  收集数钉与自我存续钉同时仍绿，而门再也不执行。只有**模块级**摘除（整文件名消失）才会被枚数抓到。
  这恰是 F6"门在场但哑了"的那一类，而 §9 五发变异覆盖的是"改名藏模块"，没有覆盖 skip。
- 修订后规范：自我存续子钉的口径改为两件事——(a) 本文件枚数与 `_OWN_TEST_NAMES` 逐名相等（抓改名/删除/凑数）；
  (b) **新增一枚机器判据**：断言本门文件自己的字节里不出现 `skip` / `xfail` 装饰器（抓"哑掉"）。
  (a) 抓不到 (b) 抓得到，两条各守一面，不再用一句话混称。
- 判据变化：**收紧**（多一枚机器判据）。原句是把两件不同性质的事写成了一件，属规格自己的措辞越界。
- 对应回归证据：B0-T2 修复轮的 §9 追加变异（对一枚门加 `@pytest.mark.skip` ⇒ 必须红）与 (b) 的定向跑。

**卡 I —— §6.3 "其它 pip 参数恰好等于豁免表"被实现缩成了"其它包名"**
- 原规格：§6.3 要求"该 job 内除 requirements 引用外，允许出现的其它 pip **参数**恰好等于豁免表"。
- 实测反例：B0-T2 的门实现只 tokenize 包名，于是三个假绿被量出来——
  ① `pip install torch --index-url https://evil.example.com/simple` ⇒ 只看到 `torch`，绿；
  而豁免行写的理由正是"选 **CPU pytorch** 发行源"，发行源本身没人钉；
  ② `pip install --no-deps -r backend/requirements-dev.txt pytest` ⇒ 第二份依赖真源不可见，绿；
  ③ 折叠成 `>-` 的 YAML 里，只有第一物理行被 tokenize，后续行的包名整体消失，绿。
- 修订后规范：§6.3 的判据拆成三条可分别证伪的钉——(1) 包名集合 == 豁免表（原有）；
  (2) 安装面 tokenize 结果**非空**，为空即红（防"门哑了"被当成"没有额外参数"）；
  (3) 安装面里出现的每个 `--index-url` / `--extra-index-url` / `-r` 的**值**都必须落在显式钉住的集合内
  （`https://download.pytorch.org/whl/cpu` 与 `backend/requirements.txt`），并规定安装步必须用 `run: |`
  字面块（折叠标量会让按物理行的 tokenize 与 YAML 语义不一致，见计划 Task 3 Step 2 的形状要求）。
- 判据变化：**收紧**。原实现比规格宽（"参数"→"包名"），且失败方向是 fail-open。
- 对应回归证据：B0-T2 修复轮的三枚合成形状复量 + §9 N4 变异（未豁免包）与新增的"空 tokenize"变异。


**卡 J —— 卡 G 的第一子句在落地时被证伪**
- 原规格：卡 G 把 B0-12 的第一子句写成"`git diff --name-only security-a-rc1 -- backend/app` 为空"。
- 实测反例：`security-a-rc1` peel 出来就是 HEAD（`7cc5efc`），而两枚 identity 改动是**未提交的工作树改动**，
  所以这条 diff 今天就会把两枚文件列出来 —— 与卡 G 想消除的那个"红在别人改动上"的失效一模一样。
- 修订后规范：改为"`git diff --name-only HEAD -- backend/app` **减去两枚 identity 文件**后为空" +
  `--cached` 为空 + 两枚 identity 的 sha 等于 B0-T1 基线（三条同时成立）。
- 判据变化：**等价但可满足**。原写法不可满足 ⇒ 事实上等于没有判据；新写法的覆盖面是"B0 不得触碰 app 面"，
  且仍由 sha 钉住那两枚没被顺手改掉。
- 对应回归证据：B0-T4 评审独立跑过 `git diff --name-only HEAD` = 恰三枚文件（`ci.yml` + 两枚 identity），
  identity sha 与 `progress.md` 里 Task 1 冻结值逐字符相同。

**卡 K —— `.gitattributes` 一落地就把行尾门自己看瞎了**
- 原规格：§6.4 要求门看住"index 无 `i/crlf`"与"`i/-text` 恰好三枚"，并默认解析器看得见每一行。
- 实测反例：`_EOL_LINE` 用 `attr/\S*` 抽属性列。规则生效前该列恒无空格（全仓无 `.gitattributes`），313 行全解析；
  规则生效后 `scripts/deploy.ps1` 与 `.superpowers/scripts/run_p0_failover_acceptance.sh` 两行变成
  `attr/text eol=crlf` / `attr/text eol=lf`，含空格 ⇒ **解析行数掉到 311，丢的正是这两枚对行尾最敏感的文件**。
  今天不违反任何不变式（两行都是 `i/lf`），所以门**静默**失去覆盖而不是红 —— 恰是 §3 的 F1/F6 形状，
  而且是被 B0 自己的交付物触发的。
- 修订后规范：§6.4 增"解析覆盖度"判据（解析行数 == `git ls-files` 行数，不等即红）+ 解析器改为可容空格列
  （`attr/\S.*?\s*` + 制表符）。覆盖度断言是主判据：它不依赖任何关于 attr 列形状的具体假设，将来再出现同类丢行也会红。
- 判据变化：**收紧**（新增一枚覆盖度钉）。代价：不修则 §6.4 的两枚门在最有价值的两枚文件上是假的，
  而"我们加了 .gitattributes 并且门绿着"这条陈述会被当作已验证。
- 对应回归证据：B0-T4 修复轮 —— 丢行前后的行数对照、两枚被丢路径点名、覆盖度钉在人为截断 attr 列时必须红。

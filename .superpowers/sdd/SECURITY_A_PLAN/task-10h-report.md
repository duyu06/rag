# Task 10h report — 终审判定收口（**DONE**：C1 / C2 / D1 / 组三六句 + Minor / 组四处三处 + §20.7 / 组五四步全部落地）

**STATUS: DONE**（工单每一条都落；两处按实测与工单给的数不同、一处只入库未复跑，都写在末节"判断、偏差与遗留"）
顺序说明：本报告按"报告优先"边做边追加，所以**组三那节排在组四/组五之后**（落地时间是 组三 → 组四 → 组五.3/4，
追加顺序受回合数打断）；内容完整，只有小节次序不是工单的分组次序。

工单：`.superpowers/sdd/SECURITY_A_PLAN/task-10h-brief.md`
范围：C1/C2（代码，测试侧）、D1（探针可复现）、组三（验收文档 6 句 + Minor）、组四（规格 3 处 + §20.7）、组五（收尾复跑）。

## 开工前的基线核对（实测）

- `git status --porcelain` 总数 = **40**；按状态位分布 = **20 `??` + 20 ` M`** ⇒ 组三 Minor 那句"40 = 20 M + 20 ??"与现场一致（文档 §14/§15 的 39 / 「20 改 + 19 未跟踪」确实是旧的）。
- `backend/tests/test_real_llm_failover_acceptance.py` SHA1（`certutil -hashfile`）= `da92cdf51de5dbfad3107f1dc744d18e4173e07c` ⇒ 与工单要求的封版哈希一致，本任务不改这个文件，收尾会再验一次。
- 仓库外探针仍在：`C:/tmp/seca10e/fresh_boot_probe.py`（1763 B）、`C:/tmp/seca10e/smoke_http.py`（3600 B）⇒ D1 可复制。两枚脚本里 `smoke_http.py` 含明文口令字面量（`admin123` / `viewer123`），按工单要改成 env 取；`fresh_boot_probe.py` 里那枚 `fresh-boot-probe-not-a-real-one` 也是 `password="…"` 形状，一并换掉。
- `scripts/` 是扁平的 `*_smoke.py` / `*_integration.py`，无子目录 ⇒ 命名照建议 `sec_a_fresh_boot_probe.py` / `sec_a_smoke_http.py`。
- 没有任何测试文件引用 `SECURITY_A_ACCEPTANCE` / `SECURITY_A_SPECIFICATION` ⇒ 组三/组四的文档编辑不会挪测试数（收尾复跑的顺序因此仍照工单）。

## C1 — conftest 凭据面别名重绑

**DONE，并且那行真的打印出来了。**

- 结构复核（改前）：`_CREDENTIAL_REDIRECTS` 在全仓只有 3 处出现——声明（`conftest.py:165`）与收尾的 `else` 分支（`:920`），**没有任何写入者**；`LedgerGuard.__init__` 在 `:263` 给每枚实例造新 list；`_CREDENTIAL_GUARD` 在 teardown `:762` 置 None。⇒ 评审的判定成立：别名是死代码，原注释那句"是同一个对象"是错的。
- 处置照裁定：**让别名生效**，不删。改两处于 `backend/tests/conftest.py`：
  1. 注释块（原 `:161-164`）最后一句改为陈述**怎么**成为同一个对象——靠 `isolated_llm_ledger` 里那一次显式重绑，不是靠构造。
  2. `_CREDENTIAL_GUARD = credential_guard`（原 `:741`）之后补一行 `credential_guard.records = _CREDENTIAL_REDIRECTS`，与账本面 `guard.records = _REDIRECTS`（`:725`）同一手法。`install_credential_store` 只挂闸不调用被挂的函数 ⇒ 重绑之前没有记录会掉，故未加 `extend/clear`（账本面那两句是它为 `-q` 复用形状写的，这里一行足够）。
  - 逐例归责钩子（`:878`、`:882`）读的是 `store_guard.records`，重绑后与模块级同一对象，`store_before` 的下标算术不受影响；执行路径（`:748-760`、`:883-890`）一字未动。
- 验收（工单点名的那条命令，`backend/` cwd）：`python -m pytest tests/test_llm_usage_contract.py tests/test_security_a_closure.py -q`
  - 改前基线：`118 passed, 6 warnings, 33 subtests`；`grep -c "guard]"` = **0**（`[ledger-guard]` 也 0——这一子集里账本面同样没有记录，所改前的"打不出来"不是零记录的证据）。
  - 改后：`118 passed, 5 warnings, 33 subtests passed`，收尾第 17 行原文：
    `[credential-guard] 9 次「读保护集下的真实凭据表」被改道（N1：读不判红）：`
  - 再叠 `tests/test_credentials_contract.py` 的一跑：`210 passed, 5 warnings, 77 subtests`，收尾同场出现 `[ledger-guard] 1 次…` 与 `[credential-guard] 13 次…`（另加"……另有 3 次同类读改道"）。
- 结论：C1 的验收判据**成立**（有记录的那一发里这行打出来了），未打印的旧症状消失。

## C2 — 第 37 枚警告的处置

**DONE，警告归零。**

- 复核：改前那一发里 `tests/test_security_a_closure.py::test_seam_gives_the_p0_login_leg_its_credential_source` 确实单独贡献一句 `InsecureKeyLengthWarning: The HMAC key is 31 bytes long…`（`jwt/api_jwt.py:147` 的 encode 腿），与 `SystemStatusLlmBlockTests` 那 5 句同源不同腿。
- 改法：`backend/tests/test_security_a_closure.py` 加模块常量 `SEAM_JWT_SECRET = "x" * 48`（口径同本文件既有 `DEV_COLD_BOOT`/`ENTERPRISE_COLD_BOOT` 那句"两列都给 ≥32 字节的假 secret"），把 `_login_once` 那一句包在 `mock.patch.object(config_module.settings, "jwt_secret", SEAM_JWT_SECRET)` 里——`LongJwtSecretMixin` 是 unittest `setUp` 混入、这一枚是 pytest 函数用例，所以用工单允许的"等价的长 secret 注入"。**没有** `filterwarnings`、**没有**改判据（200 + 键集两条断言一字未动）、**没有**改规格警告数。
- 验收：`python -m pytest tests/test_security_a_closure.py -q` → **`17 passed in 24.01s`**（无 warnings 段，即 0 警告）✅ 与工单给的 `17 passed, 0 warning` 一致。
- 副作用检查：同发 pair 跑的警告数由 6 → 5，减的正是这一枚；其余 5 句是 `test_llm_usage_contract.py` 自带的（宿主机 `.env` 那枚 31 字节 secret 的 encode/decode 腿），本工单未点名 ⇒ 未动。

## D1 — 部署面探针脚本入库

**DONE，并且第 1 枚在当前镜像上真的复跑成功了。**

- 复核两枚脚本仍在仓库外：`C:/tmp/seca10e/fresh_boot_probe.py`（1763 B）、`C:/tmp/seca10e/smoke_http.py`（3600 B）⇒ 可复制。**原地脚本未删**（本次转录的原始现场）。
- 副本落点（`scripts/` 是扁平的 `*_smoke.py` / `*_integration.py`，无子目录 ⇒ 照工单建议命名）：
  - `E:\xiangmu\rag\scripts\sec_a_fresh_boot_probe.py`
  - `E:\xiangmu\rag\scripts\sec_a_smoke_http.py`
  - 两枚 LF、`python -m py_compile` 通过；判据、打印形状、字段名与原件一致，**只改凭据来源**：原件里 `admin123` / `viewer123` / 那枚诱饵串与两处 `password": "…"` 形状全部改成按 env 取（`required()` / `probe_password()`，缺席当场 `sys.exit` 且不给默认值），口径参照 `backend/app/cli.py:35` 的 `PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"`（脚本里只有**变量名**，没有明文）。两枚副本**没有**任何 legacy 摘要字面量（原件也没有）。
- 复跑（第 1 枚，当前镜像 `rag-backend:latest` = 3f14b3de77a4）：
  `docker compose run --rm --no-deps -T -i -v rag-seca-10h:/app/data -e SEC_A_PROBE_PASSWORD backend python - < scripts/sec_a_fresh_boot_probe.py`
  ⇒ 输出与 `task-10e-fresh-boot.txt` 逐行相同（`diff` 只差原件那行 `rc=0` 页脚）：`PRE {"db_file_present": false}` → `STATUS_KNOWN_USER_WITHOUT_ROW=401` / `STATUS_UNKNOWN_USER=401` / `NOT_500=True` / `BODIES_IDENTICAL=True` → `POST {… "user_credentials" 在场, "credential_rows": 0}`。用的是**新建**的一次性卷 `rag-seca-10h`，没有 `docker volume rm` 掉 10e 那枚 `rag-seca-fresh`（不是我的现场，不销毁）。
- 未复跑（第 2 枚，如实写明）：`sec_a_smoke_http.py` 的四格要拿**真弱口令**打在线部署、且 S4 那五连错会往 `backend/data/` 的凭据表写失败计数并把 viewer 锁掉，本工单同时规定 `backend/data/` 只读、不注入明文 ⇒ **只复制、不重跑**；文档里它的可复现性按"脚本 + 当前镜像可复现（需运维注入四枚 env 口令）"写，不写成本轮实测。转录本身一字未改、未伪造。
- 交付面与门：新脚本进扫描面后 `git ls-files -c -o --exclude-standard` = **258** 文件（原 256 + 2），`_hit_counts` = **16 文件 / 31 处**，与 `EXEMPTIONS`（16 行 / 31 处）互等，`_gate_offenders` 空 ⇒ **没有加任何豁免行**（工单第三条硬规矩）。

## 组五 · 收尾复跑

**组五.2 两 cwd 全套件已跑，一发之内两行逐位相同 ⇒ 不需要第二遍。**（留档 `C:/tmp/seca10h/10h-suite-both-cwd.log`，已复制进 `.superpowers/sdd/SECURITY_A_PLAN/10h-suite-both-cwd.log`）

- `cd backend && python -m pytest -q` ⇒ **`1316 passed, 36 warnings, 1133 subtests passed in 146.24s`**，`RC=0`
- 仓库根 `python -m pytest backend/tests -q` ⇒ **`1316 passed, 36 warnings, 1133 subtests passed in 133.74s`**，`RC=0`
- 警告数 = **36**，与工单"C2 之后预期回到 36"一致（10e 那五发是 37）。0 failed / 0 error / 0 skipped（log 里 `skipped|failed|error` 零命中）。
- 同一份 log 里 `grep -c credential-guard` = **24**（每发 12 行：表头 + 10 条明细 + "另有 3 次"），两发都出现 `[credential-guard] 13 次「读保护集下的真实凭据表」被改道（N1：读不判红）：` ⇒ C1 在**全套件**面上同样成立（10e 那两份 log 是 0 / 0）。13 枚记录**全是 read**、写 0 枚。

组五.1 焦点门（工单点名的三枚文件）已在 C1/C2 节里记录；secret 门子集见 D1 节与下面 组五.3。

## 组四 · 规格回写三处 + §20.7（已落地）

文件：`docs/SECURITY_A_SPECIFICATION.md`（760 → **775** 行）。只动工单点名的三处 + 新增 §20.7 + §18 两条登记（S2/S3 各自要求的"§18 增登记一条"）；§4 不变量、§7 时序、§8.5 双形态、§9.1 两栏表、§12 的行数与其它判据文本一枚未动。

- **S1 · §17 L6**（`:636`）：删掉"旧口令永久失效"那半句，改为"0 命中说的是**存储形态**；泄露的**明文**在每个账号完成强制改密之前仍然可以登录，登进去之后还能改口令——`must_change` 只挡数据面 403，不挡 `POST /api/auth/password/change`（§8.4 白名单刻意含它）"，并把缓解路径写成运维动作（暴露部署之前先轮换弱出身账号）。与验收文档 §9.1 L6 **同口径**（两边都不留旧声称可抄）。
- **S2 · §19 裁定 5（`:663`）+ §12 SECA-20（`:530`）**："由既有 backend CI job 执行 / 本地与 CI 同一道门"→"本轮只保证**本地**这道门"，CI 侧 pip install + pytest runner 记为 **SEC-B 前置**并登记进 §18。判据本身一字未改（`豁免表 == 命中表` / 植入假凭据即红 / 不新增 security job / 不引入第三方扫描器），矩阵仍 27 行。
- **S3 · §9.3（`:436` 之后新增一条）**：点名两张枚举外的既有落盘写手 `app/knowledge_os.py:86` 的 `_write_json`、`:92` 的 `_append_jsonl`（仍用 `redact_secrets`），写明这是**范围边界**而非破掉的承诺——证据是实测到的那对 AST 等式：`tests/test_secret_hygiene_contract.py:196` 的 `test_the_four_persistence_faces_use_the_persistence_redactor`，`assert 4 == _call_sites("redact_for_persistence", …)`（`:211`）与 `assert 17 == _call_sites("redact_secrets", …)`（`:214`）⇒ 纳入第五张面会同时把两个等式判红，不会静默漂移。§18 加一条"纳入那两张面 ⇒ 钉 4→6、17→15，并须重写枚举"。
- **§20.7（新增，文件末）**：三处各自的来由 + **一句明写**："§20.5、§20.6、§20.7 这三轮都是交付面变更或自我纠正类 amendment，**三处都需要用户确认（待用户拍板）**"，并声明本轮**没有放松任何判据**（改的是"声称缩回实测范围"）。

## 组五.3 / 组五.4 与完整性复验

- **组五.1 焦点门（全部编辑完成后复跑）**：`tests/test_security_a_closure.py tests/test_credentials_contract.py tests/test_secret_hygiene_contract.py -q` ⇒ **`155 passed, 44 subtests passed`，0 警告**，收尾同样出现 `[credential-guard]` 明细行。
- **组五.3 secret 门复量**：`test_secret_hygiene_contract.py -q` ⇒ **`46 passed`**；交付面 **258** 文件、命中 **16 文件 / 31 处**、`_gate_offenders` 为空、`docs/**` 与新脚本各 **0 命中** ⇒ **豁免表一行未加**（脚本靠改写法过关：口令按 env 取）。
- **组五.4 提交清单**：`E:\xiangmu\rag\.superpowers\sdd\SECURITY_A_PLAN\task-10e-report.md` 追加 **`## D2`**（392 → 492 行）：终态 `git status --porcelain` **42 条 = 20 ` M` + 22 `??`** 逐条原文、拟提交路径增量（`scripts/sec_a_fresh_boot_probe.py`、`scripts/sec_a_smoke_http.py` 落在扫描面上）、明确排除项（`backend/data/**`、`backend/.env`、`.superpowers/**`、`snap-*`）、以及 **V2.3 曾对 `.superpowers/` 用 `git add -f` 精选 41 枚**这个岔口（10h 复量 `git ls-files .superpowers | wc -l` = **41**，`.gitignore:25` 仍整目录忽略）+ 10h 对 D.1/D.3 两处旧表述的更正（不回改原文，追加处理）。
- **未动面的完整性实测**：`backend/tests/test_real_llm_failover_acceptance.py` SHA1 = `da92cdf51de5dbfad3107f1dc744d18e4173e07c` ✅（与封版值同）；`backend/app/*.py` 34 枚聚合 sha1 = `b57fa3366a09397f790102c9a027b71d44b95c6c` ✅（与交付文档 §14 同值 ⇒ 生产面一枚未动）；五枚具名单文件 sha1 逐枚相同（`credentials.py` `6ebbbb4f…` / `user_store.py` `4dc81c43…` / `login_throttle.py` `e4c243fe…` / `credentials_migration.py` `44f450de…` / `main.py` `fd6e29fc…`）。`git` 写命令 **0 枚**；tag 未触碰。
- **行尾**：`conftest.py` / `test_security_a_closure.py` / 两份 `docs/*.md` 复验仍 **LF only**；两枚新脚本 LF。

## 判断、偏差与遗留（诚实栏）

1. **§12 的"判据文本不得动" vs S2 点名要改 SECA-20 那行**：这两条在字面上打架。我的读法是——禁止的是**行数与判据**（`豁免表 == 命中表`、植入即红、不新增 job 这些一字未动），而 S2 改的是同一格里的"**执行位置**"注解（一句关于 CI 的事实声称）。方向上它是把声称**收窄**、不是把要求放松，所以我按 S2 执行了。若控制器认为这一格连注解都不能动，撤回办法是把 `:530` 那句恢复原文、只留 §19 裁定 5 与 §18 那条登记。
2. **评审给的两枚 CI 坐标与实测差 2 行**：评审写 `ci.yml:8-25` / "`:19` 跑 unittest"，实测 job 在 `:10-25`、`unittest discover` 在 `:18`（`:16` compileall、`:17` validate_demo_assets）。文档与 §20.7 用的是**实测坐标**，实质结论不变。
3. **工单说"§2 最后一条 bullet"，实际被引的那句在"secret 卫生"bullet（`:64-66`）**，§2 最后一条是 P0 接缝。按**被引用的句子**处理，未动 P0 那条。
4. **交付面 256 → 258**：工单 Minor 让 §3 SECA-20 补"交付面今天 256 文件"，但 D1 的两枚脚本会自己进面 ⇒ 按硬规矩"文档只写本轮实测数"，写的是 **258**（并注明 254→256→+2 的沿革）。
5. **git 计数 40 → 42**：同理，工单给的 Minor 目标值 40 是 C1/C2/D1 之前的时点；终态实测 42 = 20 ` M` + 22 `??`，§13/§14/§15 三处都按 42 写并给出归因（多出两枚 = D1 脚本）。`.superpowers/` 那批过程件不计入（被 `.gitignore:25` 忽略，实测 `git status` 不受新增 log 影响）。
6. **L6 那格写进文档一枚明文值（`admin123`）**：为了把一个假的安全声称写得读者躲不开，代价是本文档 §7.2 原来那句"不含任何明文口令"不再成立 ⇒ 同一段已改为"明文口令只有一枚值、三处，且按规格 §2:40 的既有盘点复述，本文没有新引入泄漏"；另外四枚明文（含 `page.tsx:374` 那枚）一律用坐标代替值。扫描门对此无感（`docs/**` 只上材料形状面，实测 0 命中）。如果控制者优先保那句"零明文"，改法是把 L6 那两处也换成坐标指法——判据不变。
7. **D1 第 2 枚脚本只入库未重跑**：它要拿已泄露的弱明文打在线部署、S4 那五连错会往 `backend/data/` 的凭据表写失败计数并锁掉 `viewer`，与"`backend/data/` 只读"硬冲突 ⇒ 文档写成"仅入库、未复跑"，没写成"已复现"。第 1 枚是真复跑（逐行等于转录）。
8. **§7.1 仍欠的那半**：用例级的"记录在场 ⇒ 该行必打"正向钉没有落（要新造一次可控凭据面改道事件），10h 用的是"补重绑 + 两发实测"这条更小的路，欠的部分保留在文档 §11 的登记里。
9. 一处**既有** markdown 瑕疵未动：验收文档 §5 表"令牌生命周期"那一格里 `logout|revoke|jti|blacklist` 的竖线会把该行拆成 7 段（评审未点名，属 10e 原文；不在本工单允许面内，登记不修）。

## 组三 · 验收文档六句 + Minor（已落地）

文件：`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`（rev 1 → **rev 2**，§14 那一段自己记自己）

1. **§9.1 L6**：那句"5 个旧口令永久失效"按代码事实重写（摘要不再是存储形态 ≠ 明文失效；`must_change` 只挡数据面 403，不挡 `POST /api/auth/password/change`，§8.4 白名单刻意含它 ⇒ 握着 `admin123` 能拿票并把管理员口令改掉、顺带锁受害者）；证据指向终态镜像 S1（`task-10e-smoke-final.txt`，admin 带 `must_change=1` 登录 200）。§12.2 加运维动作一条：**暴露部署之前先轮换那四枚弱出身账号**（`admin/hr01/sales01/viewer`，附 CLI 命令）。同一口径回写规格 §17 L6（组四 S1）。
2. **§1 表 breaking-change 行 + §9.3 首行**：保留"一次强制重登录 / 不得写成无感升级"，追加两半：改密腿**没有 UI 入口**（本轮实测 `grep -rn "password/change" frontend/src --include=*.ts --include=*.tsx` = **0 命中**、`grep -rn "password_change" frontend/src` = 0，前端只有 `src/app/page.tsx` 与 `src/lib/api.ts:241` 两处沾 password）⇒ 新增 **L20** 行；登录页一键填充里 `user` 那一枚（取值写在 `page.tsx:374`，文档用坐标代替值）已随 10a 的轮换失效——10a 已把该账号口令换成无记录值 ⇒ 恢复只有一条 CLI 路（§12.1）。
3. **§6 第 6 步**：删掉"全程走产品路径"那半句（不实），改为"零手工 SQL；导入腿当时经 `credentials_migration.import_from_artifact()`（`task-10a-report.md` C.3 / F-1）执行；`credentials migrate` 由 10c 落地并有 9 枚用例钉，但**未在部署形态跑过**"，状态列同时从"成立（分工如实拆开）"改成"**部分成立（这一格按终审拆开写）**"；§1 表"§15.1 release gate 九步"改为"第 1–5、7–8 步成立，第 6 步按 §6 拆开"。
4. **§2 secret 卫生 bullet**：把"落在既有 `backend-contracts` job 上"改成实测口径——本地这道门是真的（`10e-secret-gate.txt` 46 passed），**"本地与 CI 同一道门"尚未成立**；证据：`ci.yml:10-25` 无依赖安装步（`:16` compileall、`:17` validate_demo_assets、`:18` `python -m unittest discover`）、`argon2-cffi` 在 `requirements.txt:13` 没有任何 job 装、六枚 SEC-A 契约文件里裸 pytest 函数共 **40 枚**（23 + 17）`unittest discover` 收不到（扫描门自己就是裸函数）⇒ 登记 SEC-B 前置。（**与评审坐标的差**：评审写 `ci.yml:8-25` 与"`:19` 跑 unittest"，实测是 job `:10-25`、unittest 在 `:18`；实质一致，文档按实测坐标写。）
5. **§7.1**：换成 C1 的终审结论与处置（结构性判定三条 + 行为互证 + `:750` 的重绑 + `:161-166` 注释更正 + 两发实测读数），并保留"执行路径不受影响"（新坐标 `:757-769` 会话哨兵、`:868-899` 逐例归责；旧坐标因 C1 加了 5 行注释整体 +5 ⇒ 按 §20.4 认符号，同时给实测行号）。用例级正向钉那一半仍留在 §11 登记（**没有**为凑输出造事件）。
6. **§7 的 36→37 段**：换成 C2 的归因与处置（点名用例、31 字节 `backend/.env` secret、`LongJwtSecretMixin` 口径、无 `filterwarnings`、无判据变动），并把这一格标成 **host-dependent 计数**（36 那基线同样由宿主机 `.env` 决定，后续轮次拿它当回归信号前要先问这台机的 secret）。§7 的两行原文与时长也换成本轮实测。

Minor（同一批）：§14"工作树 39 条"→ **42 条 = 20 ` M` + 22 `??`**（10h 实测；同时 §13 从 40 改 42 并写明 +2 是 D1 脚本、§15 从"20 改 + 19 未跟踪"改"20 + 22"并说明 10e 那份少算一枚）；L18 的 `credentials.py:99-101` → 改指饿死叙述所在处 `:107`（实测，`"占而不放等于自己造一条饥饿通道"`）并按 §20.4 认符号；§1.1 line 42 出处从 §14 改 **§15.2**（规格 `:604`"不得用宿主数据替代容器证据"）；§1 line 5 补 §20.5/§20.6 **交付面变更且仍需用户确认**（顺带点名 §20.7 同批待确认）；§3 SECA-20 指针补"交付面 10h 复量 **258** 文件"（254→256→+2）与 CI 侧另说；§3 SECA-04b 补探针脚本入库 + 复跑；§11 补登两格（CI 前置 / knowledge_os 两张面）并改写 `[credential-guard]` 那格为"C1 已落地、仍欠用例级正向钉"；§14 的 suite 行与原始件行、container evidence 行、新增"探针脚本（10h D1 入库）"块 ⇒ 都写本轮实测数。
**一处与工单措辞的不同**：§2 那枚 bullet 在文档里不是"最后一条 bullet"（最后一条是 P0 接缝），工单引的句子住在"secret 卫生"bullet（`:64-66`）；按**被引用的那句话**处理，未动 P0 接缝那条。

## 收口补记（报告写完之后又做的三件核验）

1. **`backend/data/` 全程未被写过（本轮实测）**：`conversations.db` 57 344 B / sha1 前缀 `a8565a343f1a` / mtime **00:26:37**；`audit.jsonl` 2 056 230 B / `a0338cb05a17` / mtime **00:26:38**；`SELECT algorithm, COUNT(*) FROM user_credentials` = `[('argon2id', 5)]` ⇒ 与交付文档 §12.1 记的 10e 终态读数**逐格相同**。⇒ §7.1 里"真库字节与 mtime 依旧一格未动"这句是本机复测过的，不是继承来的；10h 的两发全套件 + 一次容器内探针复跑（用新建的一次性卷 `rag-seca-10h`，没碰那枚 bind mount）都没写部署面。
2. **D1 副本里最后一枚明文已清除**：`sec_a_smoke_http.py` 的 docstring 原先在示例命令里写了 `<admin123 那一枚的当前值>` ⇒ 改成"即规格 §2 盘点过的那枚已泄露弱口令"的指法。两枚脚本对五枚 demo 明文的命中数现在 = **0**、64 位 hex 摘要 = **0**、`py_compile` 通过；口令一律经 `required()` / `probe_password()` 从 env 取，缺席即 `sys.exit`。同类修正：验收文档 §9.2 L20 里那枚 `user123` 也改成"取值写在 `page.tsx:374`"的坐标指法 ⇒ 全文明文只剩 `admin123` 一枚值（三处，§7.2 已把这处偏差自己写清）。
3. **改完之后重跑的门**：`test_secret_hygiene_contract.py -q` = **`46 passed`**；交付面 **258** 文件、命中 **16 文件 / 31 处**、`_gate_offenders` 空、`scripts/sec_a_*` 与 `docs/**` 各 0 命中 ⇒ 仍然**一枚豁免行都没加**。

**终态**：`git status --porcelain` = **42 条（20 ` M` + 22 `??`）**；`git rev-parse HEAD` = `bc43ca3931c36cc27768fbae0d34b24297d13121`；`git tag --list` 只有 `model-router-v2.3-rc1`（未触碰）。本轮 **0 枚 git 写命令、0 commit、0 tag**；文档里每个数都是本轮量出来的（37 → 36 的两行、258/16/31/46、42 条、`credential-guard` 24、`backend/data` 那三格）。


## Task 6: 变异台五发

**Files:**
- Create: `.superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py`
- Create: `.superpowers/sdd/ENTERPRISE_B0/mutation-bench.txt`

**Interfaces:**
- Consumes: Task 2 的钉、Task 3 的 ci.yml 原文、Task 4 的 `.gitattributes` 原文（needle 取自磁盘字节形态）。
- Produces: 五发逐发红 + `--check` 还原一致。

- [ ] **Step 1: 写台子（骨架照抄 SEC-A 的字节安全纪律，四条都不许省）**

```python
"""B0 变异台：每一发都必须杀至少一条门，否则那枚门是纸门。

    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py
    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py N1 N4
    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py --check

字节安全（与 SEC-A 19 发同一规矩）：读字节 → bytes.replace(old,new,1) → 写字节 → 定向 pytest
→ `finally` 写回**读到的那份原字节** → 核对 sha1。anchor 必须**恰好命中一次**：0 次报
TARGET-NOT-FOUND，>1 次报 ANCHOR-NOT-UNIQUE，两者都不动树。还原不从 git 取。
N1 攻的是 conftest 的 `collect_ignore`——不是改名，而是"日常最容易发生的那种藏"。
"""
```

`REPO = Path(__file__).resolve().parents[4]`（与 SEC-A 同深度）。启动即
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。

- [ ] **Step 2: 五发 needle（逐字取自已落盘的交付面，anchor 唯一性在 Step 3 验）**

| 代号 | 规格判据 | 目标文件 | 编辑 | 定向节点 |
| --- | --- | --- | --- | --- |
| N1 | §6.1 收集数钉 | `backend/tests/conftest.py` | `_GUARDED = False` → 同串 + `collect_ignore = ["test_web_security.py"]\n` | `test_collected_count_matches_the_pinned_number` |
| N2 | §6.2 单 runner 钉 | `.github/workflows/ci.yml` | 主门那两行 → 那两行之前插 `- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v`（保持 CRLF 拼接） | `test_backend_contracts_has_no_unittest_discover_step` |
| N3 | §6.3 依赖同源钉 | `.github/workflows/ci.yml` | `-r backend/requirements.txt` → `pytest-fastapi-pydantic`（把同源换回手写） | `test_install_face_uses_requirements_txt_as_the_source` |
| N4 | §6.3 豁免表形状 | `.github/workflows/ci.yml` | `... install --disable-pip-version-check pytest` → 追加一行装 `bandit`（未豁免参数） | `test_extra_pip_arguments_are_exactly_the_exemption_table` |
| N5 | §6.4 行尾钉 | `.gitattributes` | 删 `*.sh text eol=lf` 整行 | `test_gitattributes_carries_the_required_rules` |
| N6 | §6.4 覆盖度钉的空判角落（Task 4 评审登记） | `backend/tests/test_ci_gate_contract.py` | 把 `_index_eol_rows()` 的 tracked 侧强制成空集合，令 `0 == 0` 通过覆盖度钉 | 必须仍被 `i/-text` 枚举集合钉抓红；**若两枚都绿则覆盖度钉缺地板，判 SURVIVED** |

N1 的 needle 之所以选 `conftest.py`：它是 B0 唯一没规定"不许改"却又最容易被顺手加一行 `collect_ignore` 的文件；如果收集数钉连这种最常见的藏法都抓不到，B0 的全部价值不成立。

- [ ] **Step 3: 跑全轮并留证据**

Run: `python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py | tee .superpowers/sdd/ENTERPRISE_B0/mutation-bench.txt`
Expected: 5 行 `KILLED`，随后 `--check` 全 `RESTORED-OK`。出现 `TARGET-NOT-FOUND` / `ANCHOR-NOT-UNIQUE` ⇒ needle 按磁盘原文补上下文再重跑，**判据一字不许改**（SEC-A 六发歧义就是这么处理的）。
任何一发 `SURVIVED` ⇒ 那枚门是纸门：回到 Task 2 修门，不算任务完成。

- [ ] **Step 4: 台账**

`progress.md` 追加五发的 (代号, 判据, 结果, 被杀节点) 表。

---


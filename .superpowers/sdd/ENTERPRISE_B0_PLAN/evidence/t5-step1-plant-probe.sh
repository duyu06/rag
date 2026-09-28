#!/usr/bin/env bash
# B0-T5 Step 1 —— SECA-20 敏感性复验（植入 → 看红 → 删除 → 复绿 + 面文件数回归断言）
# 规格 §8.1 / §16 卡 F 的两条硬要求：
#   1) 任何"植入-删除"的证据动作必须 trap 兜底（EXIT INT TERM 三路都收），异常与中断都不留残留；
#   2) 结尾断言面文件数回到植入前的读数。
# 探针刻意落在仓库根的未跟踪文件上（.gitignore 不匹配 ⇒ 落进 `git ls-files -c -o --exclude-standard`
# 的交付面），这正是卡 F 想要的形状：新增一枚文件必须被门当场抓到。
set -u
cd "$(git rev-parse --show-toplevel)" || exit 99   # -> 仓库根（不靠脚本相对层数，避免上一版 cd 跑偏）
test -f backend/tests/test_secret_hygiene_contract.py || { echo "FATAL: not at repo root"; exit 98; }
E=".superpowers/sdd/ENTERPRISE_B0_PLAN/evidence"
PROBE="$PWD/b0_t5_drift_probe.py"
SURFACE_COUNT='import sys;sys.path.insert(0,"backend/tests")
import test_secret_hygiene_contract as m
print(len(m._delivery_surface_names()))'

# --- trap 兜底：无论正常收尾、报错、还是 Ctrl-C，都删探针 ---
trap 'rm -f "$PROBE"; unset PROBE; echo "[trap] probe removed" >&2' EXIT INT TERM

S_BEFORE=$(python -c "$SURFACE_COUNT")
echo "surface files BEFORE plant : $S_BEFORE"

# --- 植入一枚带凭据形状的文件（字面量按拼接构造，与本模块 test_a_planted_credential 同源）---
python - "$PROBE" <<'PY'
import sys
key, value = "JWT_" + "SECRET", "planted-" + "credential-material-32-bytes"
with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as fh:
    fh.write(f'# B0-T5 drift probe (not a credential; removed by trap)\n{key}="{value}"\n')
PY
echo "planted: $PROBE"
# 卡 F 的教训：被 .gitignore 挡掉的探针不在交付面上 ⇒ 实验是空的。这里当场证伪它。
if git check-ignore -v "$PROBE" >/dev/null 2>&1; then
  echo "FATAL: probe is git-ignored => it would never reach the delivery surface"; exit 97
fi
echo "probe ignore check: NOT ignored (rc=1) => on the delivery surface"

S_MID=$(python -c "$SURFACE_COUNT")
echo "surface files AFTER  plant : $S_MID  (expected BEFORE+1)"

echo "--- gate run with probe on the surface (expected RED) ---"
python -m pytest backend/tests/test_secret_hygiene_contract.py -q \
  -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line" \
  2>&1 | tail -14
echo "gate rc(PIPESTATUS)=${PIPESTATUS[0]}"

echo "--- full-module hit/occurrence reading with probe on the surface ---"
python -c 'import sys;sys.path.insert(0,"backend/tests")
import test_secret_hygiene_contract as m
names=m._delivery_surface_names();hits=m._hit_counts(names)
print("surface files",len(names),"hit files",len(hits),"occurrences",sum(hits.values()))
print("probe hits",hits.get("b0_t5_drift_probe.py"))'

# --- 删除 + 复绿 + 面数回归断言 ---
rm -f "$PROBE"
S_AFTER=$(python -c "$SURFACE_COUNT")
echo "surface files AFTER  remove: $S_AFTER"
if [ "$S_AFTER" != "$S_BEFORE" ]; then
  echo "ASSERTION FAILED: surface count did not return to pre-experiment value ($S_BEFORE != $S_AFTER)"
  exit 1
fi
echo "ASSERTION OK: surface files returned to $S_BEFORE"

echo "--- gate run after removal (expected GREEN again) ---"
python -m pytest backend/tests/test_secret_hygiene_contract.py -q \
  -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line" 2>&1 | tail -3
echo "--- probe residue check ---"
ls -la "$PROBE" 2>&1 | tail -1
git status --porcelain > "$E/t5-status-post-step1.txt"
diff <(cat "$E/t5-status-pre.txt") "$E/t5-status-post-step1.txt" && echo "STATUS IDENTICAL to pre-experiment"

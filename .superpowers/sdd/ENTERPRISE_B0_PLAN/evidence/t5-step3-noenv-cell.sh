#!/usr/bin/env bash
# B0-T5 Step 3 —— 无 `.env` 格（CI 形态）。规格 §8.1 + §16 卡 F 的手法要求逐条落地：
#   "移开" = 用 mv 挪出仓库到 mktemp -d 的一次性目录；**禁止仓库内改名**（.env.bak / env.bak 都会
#   作为"未忽略的 untracked"落进 SECA-20 扫描面，把两枚无关的门拖红 —— 那既是测量污染也是唯一
#   能把 `.env` 维度误读出差异的途径）。跑完还原，并断言 sha256 与 git status 都回到基线。
# trap 三路兜底（EXIT INT TERM）：中断/超时也必须把 .env 放回 backend/ 下。
set -u
CELL="${1:-root}"
T="$(git rev-parse --show-toplevel)" || exit 99
cd "$T" || exit 99
E="$T/.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence"   # 绝对路径：上一版在 cd backend 之后还写相对路径，
ENV_PATH="$T/backend/.env"                            # 直接把重定向写挂了（套件根本没跑起来）
HOLD_FILE="$E/t5-hold-dir.txt"
HOLD=""

restore() {
  if [ -n "${HOLD:-}" ] && [ -f "$HOLD/env" ]; then
    mv "$HOLD/env" "$ENV_PATH"
    echo "[restore] backend/.env moved back from $HOLD"
  fi
  rm -f "$HOLD_FILE"
  [ -n "${HOLD:-}" ] && rmdir "$HOLD" 2>/dev/null
  return 0
}
trap 'restore; echo "[trap] env-guard ran" >&2' EXIT INT TERM

test -f "$ENV_PATH" || { echo "FATAL: backend/.env not present before parking"; exit 98; }
if [ -s "$HOLD_FILE" ]; then
  echo "FATAL: a previous park is still open (HOLD=$(cat "$HOLD_FILE")) — refusing to double-park"; exit 97
fi

SHA_BEFORE=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest())")
BYTES_BEFORE=$(wc -c < "$ENV_PATH")
echo "cell              : $CELL"
echo ".env sha256 BEFORE: $SHA_BEFORE  (bytes $BYTES_BEFORE)"

HOLD="$(mktemp -d)"
echo "$HOLD" > "$HOLD_FILE"
echo "hold dir          : $HOLD (outside the repo)"
mv "$ENV_PATH" "$HOLD/env"
echo "backend/.env present after park? $([ -f "$ENV_PATH" ] && echo YES-FATAL || echo no)"
# 树内零副本自检：只看"未跟踪且未被忽略"的那一面 = SECA-20 扫描面的增量维（卡 F 的失效面）
echo "untracked-not-ignored files matching 'env':"
git ls-files --others --exclude-standard | grep -i "env" || echo "  (none)"

OUT="$E/t5-step3-cell3-root-noenv.txt"
[ "$CELL" = "backend" ] && OUT="$E/t5-step3-cell4-backend-noenv.txt"
if [ "$CELL" = "root" ]; then
  { time python -m pytest backend/tests -q ; } > "$OUT" 2>&1; RC=$?
elif [ "$CELL" = "backend" ]; then
  # 子 shell 里 cd：cwd 不外溢，后面的 sha / status 断言仍在仓库根跑
  RC=0; ( cd backend && { time python -m pytest tests -q ; } ) > "$OUT" 2>&1 || RC=$?
else
  echo "FATAL: unknown cell $CELL"; exit 95
fi
echo "suite rc          : $RC"

restore
echo "hold dir removed? $([ -d "$HOLD" ] && echo STILL-THERE || echo gone)"

SHA_AFTER=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest())")
BYTES_AFTER=$(wc -c < "$ENV_PATH")
echo ".env sha256 AFTER : $SHA_AFTER  (bytes $BYTES_AFTER)"
[ "$SHA_BEFORE" = "$SHA_AFTER" ] || { echo "ASSERTION FAILED: .env bytes changed across the park cycle"; exit 1; }
echo "ASSERTION OK: backend/.env restored byte-for-byte (sha256 equal, size equal)"

git status --porcelain > "$E/t5-step3-status-after.txt"
if diff "$E/t5-status-pre.txt" "$E/t5-step3-status-after.txt"; then
  echo "ASSERTION OK: git status --porcelain identical to pre-experiment 8 lines"
else
  echo "ASSERTION FAILED: git status drifted from the pre-experiment baseline"; exit 1
fi
echo "$RC" > "$E/t5-step3-${CELL}-noenv-rc.txt"
tail -4 "$OUT"

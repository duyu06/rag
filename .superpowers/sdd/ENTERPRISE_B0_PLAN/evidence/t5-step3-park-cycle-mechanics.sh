#!/usr/bin/env bash
# B0-T5 Step 3 补档 —— park/restore 机械动作的裸档（**不跑套件**，几秒钟）。
# 说明（写清以免被当成读数）：带套件的那两次 park 周期把 pytest 本体逐字写进了
#   evidence/t5-step3-cell3-root-noenv.txt / t5-step3-cell4-backend-noenv.txt，
#   但 wrapper（sha 前后比对 + status 比对）那几行只在终端里、没 tee。
# 本脚本用**与 t5-step3-noenv-cell.sh 同一套动作**（同一 mktemp -d 手法 + 同一 trap 形状）
#   再走一遍空跑，把 wrapper 的断言行留成裸档；它不产生任何套件读数，因此也不主张任何读数。
set -u
T="$(git rev-parse --show-toplevel)"
cd "$T" || exit 99
E="$T/.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence"
ENV_PATH="$T/backend/.env"
HOLD=""
restore() {
  if [ -n "${HOLD:-}" ] && [ -f "$HOLD/env" ]; then mv "$HOLD/env" "$ENV_PATH"; echo "[restore] moved back"; fi
  rm -f "$E/t5-hold-dir.txt"; [ -n "${HOLD:-}" ] && rmdir "$HOLD" 2>/dev/null; return 0
}
trap 'restore; echo "[trap] env-guard ran" >&2' EXIT INT TERM
SHA_BEFORE=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest())")
HOLD="$(mktemp -d)"; echo "$HOLD" > "$E/t5-hold-dir.txt"
mv "$ENV_PATH" "$HOLD/env"
echo "sha BEFORE      : $SHA_BEFORE"
echo "parked to       : $HOLD (mktemp -d, outside the repo)"
echo ".env in tree?   : $([ -f "$ENV_PATH" ] && echo YES-FATAL || echo no)"
echo "surface now     : $(python -c "import sys;sys.path.insert(0,'backend/tests')
import test_secret_hygiene_contract as m;print(len(m._delivery_surface_names()))")  (must stay 318: no in-tree copy leaked onto the face)"
restore
SHA_AFTER=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest())")
echo "sha AFTER       : $SHA_AFTER"
[ "$SHA_BEFORE" = "$SHA_AFTER" ] && echo "ASSERTION OK: byte-for-byte identical" || echo "ASSERTION FAILED"
echo "surface restored: $(python -c "import sys;sys.path.insert(0,'backend/tests')
import test_secret_hygiene_contract as m;print(len(m._delivery_surface_names()))")"
git status --porcelain > "$E/t5-step3-mechanics-status.txt"
diff "$E/t5-status-pre.txt" "$E/t5-step3-mechanics-status.txt" && echo "STATUS IDENTICAL to the 8 pre-experiment lines"
echo "ls backend/.env : $(ls -la "$ENV_PATH")"

#!/usr/bin/env bash
# run_p0_failover_acceptance.sh —— REAL-LLM-FAILOVER-001（§10 P0）的一键真跑器。
#
# 出处：Model Router V2.3 Task 10 段 A（A-4）。它做且只做三件事：
#   1) 跑 `backend/tests/test_real_llm_failover_acceptance.py` 那枚 P0 例
#      （真 Ollama：primary=ornith-1.5:9b-text 真加载失败 → fallback=phi3:mini 真回答）；
#   2) 让用例自己把 JSON 证据落到
#      `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`，
#      跑完在终端回打十枚断言的实测值、临时库路径与行数、sha1 表；
#   3) 打印「矩阵 P0 行改 GREEN 的许可条件是否全部满足」。
#
# **它不改矩阵文件**：`docs/MODEL_ROUTER_V23_MATRIX.md` 那一行状态字段由主 agent 落笔，
# 本脚本只给判据（`real_llm_failover_kit.green_permission()`），也不 `sed`、也不 patch。
#
# 用法
#   bash .superpowers/scripts/run_p0_failover_acceptance.sh --dry-run   # 只查环境 + 离线自检
#   bash .superpowers/scripts/run_p0_failover_acceptance.sh --probe     # 追加一次 A-2 有界探针
#   bash .superpowers/scripts/run_p0_failover_acceptance.sh             # 真跑（内存不够会拒绝）
#   bash .superpowers/scripts/run_p0_failover_acceptance.sh --yes       # 显式越权内存门槛后真跑
#
# 退出码：0 成功 / 1 用例红 / 2 参数错 / 3 内存门槛没过（未给 --yes）/ 4 前置不满足
set -uo pipefail

MODE="run"
ASSUME_YES="0"
for arg in "$@"; do
  case "$arg" in
    --dry-run) MODE="dry-run" ;;
    --probe)   MODE="probe" ;;
    --yes|-y)  ASSUME_YES="1" ;;
    -h|--help) sed -n '1,30p' "$0"; exit 0 ;;
    *) echo "未知参数：$arg（可用：--dry-run | --probe | --yes | --help）" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKEND="${REPO_ROOT}/backend"
PYTHON="${PYTHON:-python}"

# 这台机器的控制台默认是 GBK：不设这两枚，中文输出会直接 UnicodeEncodeError 把跑真机的人绊倒。
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
unset REAL_LLM_ACCEPTANCE            # 开关只由本脚本在 [3/4] 那一步临时打开

py() {  # 在 backend/ 下以 tests/ 为 sys.path 跑一段 python（heredoc 从 stdin 进）
  ( cd "${BACKEND}" && "${PYTHON}" - "$@" )
}

echo "=== [0/4] 环境前置（零模型加载） ==="
py <<'PY'
import json, sys
sys.path.insert(0, "tests")
import real_llm_failover_kit as kit

mem = kit.memory_check()
inv = kit.ollama_inventory()
print("Ollama:", inv["base_url"], "可达" if inv["reachable"] else f"不可达：{inv['error']}")
print("  条目 :", [(m["name"], m["size_gib"]) for m in inv["tags"]])
print("  已加载:", inv["loaded"] or "（无）")
print("内存   :", mem["verdict"])
for sample in mem["samples"]:
    print(f"  采样   : 可用 {sample['available_gib']} GiB / 总 {sample['total_gib']} GiB"
          f"（占用 {sample['memory_load_percent']}%）")
problems = []
if not inv["reachable"]:
    problems.append("Ollama 不可达：起不了真调用")
if not inv["has_primary"]:
    problems.append(f"缺条目 {kit.PRIMARY_MODEL}：P0 的 primary 腿无从发生")
if not inv["has_fallback"]:
    problems.append(f"缺条目 {kit.FALLBACK_MODEL}：P0 的 fallback 腿答不出东西")
if inv["loaded"]:
    problems.append(f"已有加载中的模型 {inv['loaded']}：ornith 必须保持未加载态，"
                    "否则 P0 的『primary 真失败』前提不成立（先等它自然卸载或 keep_alive 到期）")
if problems:
    print("前置不满足：")
    for item in problems:
        print("  -", item)
    sys.exit(4)
json.dump({"memory": mem, "inventory": inv}, open(
    str(kit.EVIDENCE_DIR / "preflight.json"), "w", encoding="utf-8"),
    ensure_ascii=False, indent=2)
print("已落前置件：", kit.EVIDENCE_DIR / "preflight.json")
sys.exit(0 if mem["enough_for_phi3"] else 3)
PY
PREFLIGHT=$?
if [ "${PREFLIGHT}" -eq 3 ] && [ "${MODE}" = "dry-run" ]; then
  echo ">>> （--dry-run：内存门槛只作报告，不作拦截——真跑才会被拒）"
elif [ "${PREFLIGHT}" -eq 3 ]; then
  echo ">>> 内存门槛没过：真跑会加载 phi3:mini（2.03 GiB），有把机器打进 paging 的风险。"
  if [ "${ASSUME_YES}" != "1" ]; then
    echo ">>> 已拒绝。确认这台机器现在可以扛住，就加 --yes 再跑一次。"
    exit 3
  fi
  echo ">>> --yes 已给出：越权继续（这一条会记进证据 JSON 的 preflight 里）。"
elif [ "${PREFLIGHT}" -ne 0 ]; then
  exit "${PREFLIGHT}"
fi

echo
echo "=== [1/4] primary 腿离线自检（A-3 要求：不加载 phi3 也能验的先验掉） ==="
py <<'PY' || exit 4
import json, sys
sys.path.insert(0, "tests")
import real_llm_failover_kit as kit
print(json.dumps(kit.selfcheck_primary_leg(), ensure_ascii=False, indent=1))
PY

if [ "${MODE}" = "probe" ]; then
  echo
  echo "=== [1b] 重跑 A-2 有界探针（一次真实加载尝试，≤120 秒） ==="
  py <<'PY' || exit 1
import json, sys
sys.path.insert(0, "tests")
import real_llm_failover_kit as kit
record = {"stage": "A-2 primary load probe (re-run via runner)",
          "inventory_before": kit.ollama_inventory(),
          "memory_before": kit.memory_facts(),
          "probe": kit.probe_primary_load(),
          "inventory_after": kit.ollama_inventory()}
kit.write_json(kit.PROBE_FILE, record)
print(json.dumps(record["probe"], ensure_ascii=False, indent=1))
PY
fi

echo
echo "=== [2/4] 将要执行的命令 ==="
CMD=("${PYTHON}" -m pytest tests/test_real_llm_failover_acceptance.py -q -s
     -p no:cacheprovider --tb=short)
echo "  cd ${BACKEND}"
echo "  REAL_LLM_ACCEPTANCE=1 ${CMD[*]}"
echo "  预期耗时：phi3:mini 冷加载 + 生成，数十秒到数分钟；用例内预算 900 秒。"
echo "  证据：.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json"
echo "  临时库/trace：.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/<时间戳>/"

if [ "${MODE}" = "dry-run" ]; then
  echo
  echo "=== --dry-run：到此为止，没有发出任何模型调用 ==="
  echo "  上面 [0/4] 的内存判定 + [1/4] 的离线自检就是「够不够、链条对不对」的全部结论。"
  echo "  真跑：去掉 --dry-run（内存不够时再加 --yes）。"
  exit 0
fi

echo
echo "=== [3/4] 真跑 P0（会真的加载模型） ==="
( cd "${BACKEND}" && REAL_LLM_ACCEPTANCE=1 "${CMD[@]}" )
RC=$?
echo "  pytest 退出码：${RC}"

echo
echo "=== [4/4] 证据回打 + 矩阵改 GREEN 的许可判定 ==="
py <<'PY'
import json, sys
sys.path.insert(0, "tests")
import real_llm_failover_kit as kit

evidence, error = kit.read_evidence()
if evidence is None:
    print(f"证据不存在或不可解析：{error} —— 用例没能跑到写证据那一步（看上面的 pytest 输出）")
    sys.exit(1)
print("十枚断言：")
for item in evidence.get("assertions") or []:
    flag = "PASS" if item.get("pass") else "FAIL"
    print(f"  [{flag}] {item.get('id'):>2} {item.get('name')} ({item.get('elapsed_ms')} ms)")
    if item.get("failure"):
        print(f"        {item['failure']}")
print("真外呼：")
for call in evidence.get("provider_calls") or []:
    print(f"  {call.get('model')}: ok={call.get('ok')} bytes={call.get('request_bytes')} "
          f"elapsed={call.get('elapsed_ms')} ms status={call.get('http_status')} "
          f"kind={call.get('error_kind')}")
ledger = evidence.get("ledger") or {}
print(f"临时账本：{ledger.get('path')} 行数={ledger.get('rows')} "
      f"canary 命中={len(ledger.get('canary_hits') or [])}")
print(f"仓库真实库（必须 0 行）：{json.dumps(ledger.get('protected_repo_ledgers'), ensure_ascii=False)}")
print(f"trace：{(evidence.get('trace') or {}).get('path')} 行数="
      f"{(evidence.get('trace') or {}).get('lines')}")
print("耗时：", json.dumps(evidence.get("timings_ms"), ensure_ascii=False))
print("sha1：")
for path, digest in (evidence.get("files_sha1") or {}).items():
    print(f"  {digest}  {path}")
permission = kit.green_permission()
print("矩阵改 GREEN 的许可条件（当前状态 "
      f"{permission['matrix_status_now']}）：")
for condition in permission["conditions"]:
    print(f"  [{'满足' if condition['ok'] else '不满足'}] {condition['name']}"
          f" —— {condition['detail']}")
print("green_permitted_by_evidence =", permission["green_permitted_by_evidence"])
print("注意：本脚本不改 docs/MODEL_ROUTER_V23_MATRIX.md，落笔归主 agent。")
sys.exit(0 if permission["green_permitted_by_evidence"] else 1)
PY
exit ${RC}

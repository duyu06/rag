"""在发布容器内实测 Argon2id 档位的延迟与内存，作为 SECA-19 的判据。

预算（规格 §12 SECA-19）：串行 P95 ≤ 1500ms；ARGON2_MAX_CONCURRENT_OPS 并发 P95 ≤ 3000ms；
单次运算峰值 RSS 增量 ≤ 256 MiB。不满足 ⇒ BLOCKED，降档必须走规格修订。

**为什么并发是 2 个 worker**（写进代码注释而不是只写进报告，否则下一个人会把它调大）：
`ARGON2_MAX_CONCURRENT_OPS=2` 是 `app/credentials.py` 里那道 `BoundedSemaphore` 的闸门上限，
也是生产进程同一时刻能付出的 Argon2 运算数的天花板。基准若在更多 worker 上跑，测到的是
"闸门之外"的理想值（每枚运算独占 CPU 与内存带宽，P95 反而更低）；若在更少 worker 上跑，
测不到争用。所以必须 **在闸门满配下测** —— 2 worker × 16 轮 = 32 次并发运算排队过 2 个槽，
这才是 SECA-19 要的那格最坏值。同理，32 轮不是随手取的：2 个槽 × 16 圈，P95 落在队尾那两枚
上，样本量够把排队尾效应稳定地暴露出来，又不至于让宿主/容器的一次性抖动主导整个分位数。

**`ru_maxrss` 的单位**：Linux 报 **KiB**，macOS 报 **bytes**。本判据的判定点是发布容器
（Linux），`BUDGET["rss_delta_kib"] = 256 * 1024` 的 KiB 口径在那里成立。宿主那次只是对照
读数（规格 §15.2：不得用宿主数据替代容器证据），单位在 macOS 上会偏 1024 倍——**故意不去
"修平"容器路径**：给容器分支加平台换算就等于让判据随平台漂移。`peak_rss_delta_unit` 字段
把这层口径写明白，读对照数的人自己换算。

强度参数（`t/m/p`）在这里是**字面量**，与 `app/credentials.py:24-26` 同值：本脚本不读
`os.environ`，也不从 `settings` 取，否则它就变成第 4 处可调档位的入口（M16 要杀的就是这个形状）。
"""

import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

try:
    # `resource` 是 POSIX 模块：Windows 宿主上根本没有它（`import resource` 直接
    # ModuleNotFoundError）。**不去"修平"的理由见上面那段**：判据只认容器（Linux），
    # 宿主这一份是对照，缺的只有峰值 RSS 一格，延迟两格照测。容器路径一行未动。
    import resource
except ImportError:  # pragma: no cover - win32 宿主走这一支
    resource = None

from argon2 import PasswordHasher

TIME_COST, MEMORY_COST, PARALLELISM = 2, 19456, 1
# 串行 50 次给 P50/P95 一个能落的样本量；并发 32 次/2 worker = 闸门满配下的 16 圈排队。
SERIAL_RUNS, CONCURRENT_RUNS, WORKERS = 50, 32, 2
BUDGET = {"serial_p95_ms": 1500.0, "concurrent_p95_ms": 3000.0, "rss_delta_kib": 256 * 1024}

ph = PasswordHasher(time_cost=TIME_COST, memory_cost=MEMORY_COST, parallelism=PARALLELISM)
password = f"benchmark-password {time.time_ns()}"
encoded = ph.hash(password)
baseline_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource else None


def one(_: int) -> float:
    started = time.perf_counter()
    ph.verify(encoded, password)
    return (time.perf_counter() - started) * 1000.0


def p95(samples):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


serial = [one(i) for i in range(SERIAL_RUNS)]
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    concurrent = list(pool.map(one, range(CONCURRENT_RUNS)))
peak_kib = (
    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - baseline_kib if resource else None
)

report = {
    "profile": {"time_cost": TIME_COST, "memory_cost": MEMORY_COST, "parallelism": PARALLELISM},
    "environment": sys.platform,
    "serial": {
        "runs": SERIAL_RUNS,
        "p50_ms": round(statistics.median(serial), 1),
        "p95_ms": round(p95(serial), 1),
    },
    "concurrent": {"runs": CONCURRENT_RUNS, "workers": WORKERS, "p95_ms": round(p95(concurrent), 1)},
    "peak_rss_delta_kib": int(peak_kib) if peak_kib is not None else None,
    "budget": BUDGET,
}
# 只补读数口径，不参与判定：verdict 的三把尺子仍是上面 BUDGET 里那三项。
report["environment_detail"] = {
    "python": sys.version.split()[0],
    "peak_rss_delta_unit": "KiB on Linux (ru_maxrss); macOS reports bytes — container is the criterion",
    "rss_delta_meaning": "process peak RSS high-water mark minus baseline, not per-op footprint",
}
report["budget_checks"] = {
    "serial_p95": report["serial"]["p95_ms"] <= BUDGET["serial_p95_ms"],
    "concurrent_p95": report["concurrent"]["p95_ms"] <= BUDGET["concurrent_p95_ms"],
    "peak_rss_delta": (
        None if peak_kib is None else int(peak_kib) <= BUDGET["rss_delta_kib"]
    ),
}
if report["budget_checks"]["peak_rss_delta"] is None:
    # 测不到峰值 RSS 的平台**不出**判定：让一个 None 参与 and 链会把它当成"未超预算"，
    # 那是把缺证据写成通过。容器（Linux）永远走不到这一支——SECA-19 的判据文件就是那一份。
    report["verdict"] = "NOT_THE_CRITERION"
    report["verdict_reason"] = (
        f"ru_maxrss 在 {sys.platform} 上不可得（无 resource 模块）；SECA-19 只按 "
        "argon2-benchmark-container.json 判，本文件仅作对照。"
    )
else:
    report["verdict"] = "GREEN" if (
        report["serial"]["p95_ms"] <= BUDGET["serial_p95_ms"]
        and report["concurrent"]["p95_ms"] <= BUDGET["concurrent_p95_ms"]
        and report["peak_rss_delta_kib"] <= BUDGET["rss_delta_kib"]
    ) else "BLOCKED"
print(json.dumps(report, indent=2, ensure_ascii=False))

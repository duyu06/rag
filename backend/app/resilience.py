"""通用韧性原语：滚动窗口熔断器 + 超时预算（TypeSafe V2 起用，Model Router V2 复用）。

消费方必读的已知限制
--------------------
- **无世代令牌（epoch / generation token）**：OPEN / HALF_OPEN 切换窗口里仍在飞的请求，
  其迟到的 `record()` 会被记进"新状态"的账（CLOSED 期发出的在飞回执可能混进切换后的
  滑窗；HALF_OPEN 期的迟到回执会记错探测名额）。本版本按 YAGNI 不实现 epoch 令牌，
  留待 Model Router V2 再定。规避姿势：**在熔断器外层丢弃 `circuit_open` 时的迟到结果**
  ——外呼前 `allow()` 预检，且一旦判定被跳过/熔断已打开，那条请求的回执一律不再 `record()`。
- **`state` 是带副作用的 getter**：读取即惰性推进 OPEN → HALF_OPEN（"观测即推进"）。
  外呼闸门必须以 `allow()` 返回值为唯一依据；`state` 只用于观测/指标采样，
  且采样本身就会消耗掉 OPEN 的等待窗口。
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

MIN_WINDOW = 8


class CircuitBreaker:
    """Generic rolling-window breaker. One instance per dependency
    (typesafe today; each LLM provider in Model Router V2).

    状态机与口径
    ------------
    - CLOSED：滑窗 `deque(maxlen=window)` 攒够 `max(4, window // 2)` 个样本后，
      失败率**严格大于** `failure_ratio` 才 `_trip()`。`window` 必须 `>= 8`，
      否则构造期即 `ValueError`：门槛 `max(4, window // 2)` 在 window < 8 时超过
      deque 实际可达长度，判定会静默失效（永远不熔断）。
    - OPEN：冷却是**固定时长** `open_seconds`（无指数退避），起点为 `_trip()` 的时刻。
      OPEN 期间的 `record()` 只把样本追加进滑窗，**既不改状态也不重置冷却**；
      到期后由下一次 `allow()` 或 `state` 观测惰性推进到 HALF_OPEN。
    - HALF_OPEN：探测限流。维护"已放行未回执"计数 `_half_inflight`：`allow()` 仅当
      `_half_inflight + _half_success < half_open_probes` 才放行并 `_half_inflight += 1`；
      `record()` 在该分支先 `_half_inflight -= 1` 再记账，成功累计达标即 CLOSED，
      任一失败即 `_trip()` 回 OPEN。

    已知限制：HALF_OPEN 的放行槽位**没有租约回收**——被 `allow()` 放行却永不 `record()`
    的探测会把槽位一直占到状态切换。这里用"进入 HALF_OPEN 时重置计数 + `_trip()` /
    `_reset_closed()` 时清零"来控制影响面：泄漏最多污染当前一个探测窗口，
    冷却到期重新进入 HALF_OPEN 时一定重新拿到满额 `half_open_probes` 个槽位。
    """

    def __init__(self, *, name: str, window: int = 20, failure_ratio: float = 0.30,
                 open_seconds: float = 60.0, half_open_probes: int = 3,
                 clock=time.monotonic) -> None:
        if window < MIN_WINDOW:
            raise ValueError(
                f"window 必须 >= {MIN_WINDOW}（当前 {window}）：否则最小样本门槛 "
                f"max(4, window // 2) 超过滑窗可达长度，熔断判定会静默失效")
        self.name = name
        self._window = window
        self._ratio = failure_ratio
        self._open_seconds = open_seconds
        self._probes = half_open_probes
        self._clock = clock
        self._results: deque[bool] = deque(maxlen=window)
        self._state = "closed"
        self._opened_at = 0.0
        self._half_success = 0
        self._half_inflight = 0
        self._lock = Lock()

    @property
    def state(self) -> str:
        """观测口。**有副作用**：到期时把 OPEN 惰性推进为 HALF_OPEN。
        不要拿它当外呼闸门（那是 `allow()`），也不要在热路径上白读。"""
        with self._lock:
            self._maybe_leave_open()
            return self._state

    def allow(self) -> bool:
        """外呼闸门：CLOSED 恒 True；OPEN 恒 False；HALF_OPEN 按探测名额限流。
        返回 True 且处于 HALF_OPEN 时占用一个探测槽位，等 `record()` 释放。"""
        with self._lock:
            self._maybe_leave_open()
            if self._state == "half_open":
                if self._half_inflight + self._half_success >= self._probes:
                    return False
                self._half_inflight += 1
                return True
            return self._state != "open"

    def record(self, ok: bool) -> None:
        with self._lock:
            if self._state == "half_open":
                # 先归还探测槽位，再记账（迟到/未配对的 record 由 max(0, .) 兜底）
                self._half_inflight = max(0, self._half_inflight - 1)
                if ok:
                    self._half_success += 1
                    if self._half_success >= self._probes:
                        self._reset_closed()
                    return
                self._trip()
                return
            self._results.append(ok)
            if self._state == "closed" and len(self._results) >= max(4, self._window // 2):
                failures = sum(1 for item in self._results if not item)
                if failures / len(self._results) > self._ratio:
                    self._trip()

    def _maybe_leave_open(self) -> None:
        if self._state == "open" and self._clock() - self._opened_at >= self._open_seconds:
            self._state = "half_open"
            self._half_success = 0
            self._half_inflight = 0

    def _trip(self) -> None:
        self._state = "open"
        self._opened_at = self._clock()
        self._results.clear()
        self._half_success = 0
        self._half_inflight = 0

    def _reset_closed(self) -> None:
        self._state = "closed"
        self._results.clear()
        self._half_success = 0
        self._half_inflight = 0


class TimeoutBudget:
    def __init__(self, *, soft_ms: float, hard_ms: float, clock=time.perf_counter) -> None:
        if hard_ms <= 0 or soft_ms <= 0 or soft_ms > hard_ms:
            raise ValueError("需要 0 < soft_ms <= hard_ms")
        self._started = clock()
        self._soft = soft_ms
        self._hard = hard_ms
        self._clock = clock

    def elapsed_ms(self) -> float:
        return (self._clock() - self._started) * 1000.0

    def remaining_ms(self) -> float:
        return self._hard - self.elapsed_ms()

    def over_soft(self) -> bool:
        return self.elapsed_ms() > self._soft

    def exhausted(self) -> bool:
        return self.remaining_ms() <= 0.0

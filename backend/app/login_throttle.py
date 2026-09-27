"""pre-hash 节流（规格 §7.1 步骤 0 / §7.2 第一层）与锁定判定的唯一真源。

两层键不同、职责不同，合并成一枚必然丢掉两种保护之一：

- 本模块的桶是**进程内**的，按 `(归一化 username, client_ip)` 分，重启即清。它回答的
  唯一问题是"这次请求配不配消耗一次内存硬运算"，所以判定必须排在任何身份查找之前——
  闸门排在运算之后，认证面自己就成了 DoS 面。
- `user_store` 的 `failed_attempts`/`locked_until` 是**落库**的，只按 username 分，跨重启、
  跨来源地址共享。第一层少一枚 `client_ip` 键 ⇒ 换个来源地址即可绕过节流；给第二层也
  加上 `client_ip` ⇒ 分布式猜测一人一份计数，锁定永不触发。两枚键都必须有直接断言。

本模块不做 sleep：§7.4 的收敛靠"锁定路径不跑 Argon2"，人工延迟本身是攻击面。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from app.config import settings


def client_ip_of(request) -> str:
    """本次请求的**可信**来源地址。

    只认 `request.client.host`，**不读** `X-Forwarded-For`：当前部署形态里 compose 直接
    把 8001 映射出去、前面没有反代，于是那个头是客户端自述的字符串。信任它等于把
    节流键交给攻击者挑——换一枚伪造头就是一个新桶，第一层当场归零。将来真要前置 nginx，
    改的是这里（并且必须同时约束跳数），而不是调用方。
    """
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "unknown")


def throttle_bucket(username: str, client_ip: str) -> str:
    """节流键：归一化的账号名 + 来源地址。两枚都参与，缺一层的保护就少一半。"""
    return f"{str(username).casefold()}|{client_ip}"


class LoginThrottledError(RuntimeError):
    """节流命中。它**不是**凭据结论：还没做身份查找、还没碰口令，所以 HTTP 面是 429 不是 401。

    住在这一层而不是 `auth`，因为判定与异常同源；`auth` 与 `main` 都 import 同一个类，
    两枚同义异常早晚出现"catch 错那一枚"的缝。
    """


class PreHashThrottle:
    """固定窗口内的滑动计数（每桶一个单调时钟时间戳队列）。"""

    def __init__(self, *, window_seconds: int, max_attempts: int) -> None:
        self._window = float(window_seconds)
        self._max = int(max_attempts)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        #: 回收时缝的起点。**故意不在这里取 `time.monotonic()`**：见 `_sweep_stale` 的
        #: `moment` 基准那一段——初值取真实单调钟，而 `allow(now=)` 给的是注入时钟，两者不同
        #: 基准时第一次回收要等到注入值自然涨过真实单调钟的读数（测试里那往往是"永远"）。
        #: `None` = "还没有过任何一次调用"，第一格由**当下那枚时刻**惰性播下 ⇒ 真实运行时的
        #: 取值一字不变（第一次调用读的就是 monotonic），注入时钟也不再需要迁就一个它看不见的初值。
        self._last_sweep: float | None = None

    def allow(self, bucket: str, *, now: float | None = None) -> bool:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            self._sweep_stale(moment)
            hits = self._hits[bucket]
            while hits and moment - hits[0] > self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(moment)
            return True

    def _sweep_stale(self, moment: float) -> None:
        """整表回收，每个窗口至多一次；调用方持锁。

        单桶判据（`allow` 里那条）只清空**被再次命中**的桶：来源地址打不停时，桶的个数
        就是攻击者的请求数，节流表自己会长成一条内存增长面。这里按"最近一次命中已出窗"
        整片丢弃，语义与逐桶剪枝完全一致（丢掉的桶再命中一次也会重新计入），只是把上限
        从'见过的地址数'收到'一个窗口内在场的地址数'。

        `moment` 的基准有一条**已经拆掉的雷**，留这段是为了不让它再长回来：这条时缝的两端
        （`_last_sweep` 的起点与 `allow(now=)` 的注入值）必须是同一个基准，否则
        `moment - self._last_sweep` 可能是负的、回收就**永不发生**——症状不是报错而是"表只长不缩"，
        且任何只看答复的用例都看不出区别。早期写法把起点钉在构造时的真实 monotonic 上，于是
        注入一条与它无关的时钟就得自己迁就那个看不见的初值（用例里那句"base 要取
        `time.monotonic()`"就是这笔税）。现在起点是 `None`，第一次调用时由**传进来的那枚时刻**
        惰性播种：真实运行时读到的还是同一个 monotonic 读数，注入时钟则从自己的零点开始算。
        播种那次**不**顺手扫一遍表——表还空着，而把 `_last_sweep` 交给后续调用的时刻去推进，
        等于让一次调用把整片表的回收推远一个窗口，那件事仍然不做。
        """
        if self._last_sweep is None:
            self._last_sweep = moment
            return
        if moment - self._last_sweep <= self._window:
            return
        self._last_sweep = moment
        for key in [k for k, dq in self._hits.items() if not dq or moment - dq[-1] > self._window]:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            # 回到"从没被叫过"，而不是回到真实单调钟的此刻：后者会把上面那条时缝重新装上，
            # 而 `reset()` 的调用点全在测试夹具里（那里跑的正是注入时钟）。
            self._last_sweep = None


def is_locked(locked_until: str | None, *, now: datetime | None = None) -> bool:
    """账号此刻是否处于锁定期：`locked_until` 是**锁到的那个时刻**，还没到就是锁着。

    方向别写反：`record_login_failure` 写进去的是 `now + lock_seconds`（未来），所以"还锁着"
    对应 `until > now`。写反的症状是"永远锁不住"——阈值一到就把它当成过期，下一次口令猜测
    照旧跑一次 Argon2，§7.2 第二层直接失效。

    坏值一律 fail closed 当锁定，两种坏法同臂：压根解析不出（ValueError），以及**解析得出
    但没有偏移**（naive）。后者不是假想——运维手改、从另一个写入方恢复来的备份、SQLite 的
    `CURRENT_TIMESTAMP` 惯用法都会给出 `2099-01-01 00:00:00` 这种能解析却无时区的值。
    这里**不**替它补 UTC：猜出来的偏移会把一行不再可信的数据读成"这一行说没锁"，
    而白送一次昂贵运算正是这条门要挡的事。
    """
    if not locked_until:
        return False
    try:
        moment = datetime.fromisoformat(str(locked_until))
    except (ValueError, TypeError):
        return True
    if moment.tzinfo is None:
        return True
    return moment > (now or datetime.now(timezone.utc))


#: 进程内单例。窗口与阈值都是**可用性旋钮**（`login_throttle_*`），不含 m/t/p：
#: 口令强度固定在 `credentials` 的常量上，不可在运行时调（SEC-A-008）。
#: 构造在 import 期完成，与 `credentials._SLOTS` 同一口径；**读取点只有这一处属性**——
#: 谁按值把它绑成自己模块里的第二个名字，替身打在源头那一格上就静默无效。
pre_hash_throttle = PreHashThrottle(
    window_seconds=settings.login_throttle_window_seconds,
    max_attempts=settings.login_throttle_max_attempts,
)

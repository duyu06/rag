"""TypeSafe V2 判定路由（设计 §3 信号矩阵 / §4 动态 TopK）——纯函数、零 IO。

调用方（Task 6 的 retrieval 判定段）负责保证：
1. `rows` 已按本地 Cross-Encoder 的 `rerank_score` **降序**排列（本模块不重排、不排序）；
2. 行内可选字段缺失时按 0 处理（缺分不等于高分，宁可多判）。

不变式：
- 不写入参、不读写配置、不发网络/存储请求；同输入必同输出（可直接做属性/单调性测试）。
- 只读 `app.config.settings` 的 margin/floor/池宽键，运行期改配置即刻生效（不缓存快照）。
"""
from __future__ import annotations

import re
from typing import Any

from app.config import settings

# 复合问句判定复用 V1 已有的权威实现（`typesafe_judgments.query_requirements`），
# 不在此另写一套口径。
# 依赖方向核对：app.typesafe_judgments 只 import app.config 与第三方 typesafe_sdk，
# 不反向引用本模块 ⇒ 无循环 import（brief Interfaces 的第一种方案）。
from app.typesafe_judgments import is_compound_query

# ---------------------------------------------------------------------------
# reasons 词表（主控预裁决锁定为 6 个稳定小写 token，Task 5/6/7 的日志与指标按此拼写）
# ---------------------------------------------------------------------------
REASON_COMPOUND = "compound"        # 多分句复合问句
REASON_MARGIN = "margin"            # CE top1-top2 分差过窄（含 rows<2）
REASON_FLOOR = "floor"              # top1 低于置信地板
REASON_RISK = "risk"                # 命中敏感/严格引用词表
REASON_DISPERSED = "dispersed"      # 候选跨文档分散（no-answer 倾向）
REASON_PARAM = "param"              # 数字/时间/参数敏感（精确量值事实题）

# 发射顺序即此顺序（测试锁定 reasons 按本元组排序，便于日志稳定比对）。
REASON_TOKENS: tuple[str, ...] = (
    REASON_COMPOUND,
    REASON_MARGIN,
    REASON_FLOOR,
    REASON_RISK,
    REASON_DISPERSED,
    REASON_PARAM,
)

# ---------------------------------------------------------------------------
# 阈值常量
# ---------------------------------------------------------------------------
# spec §3 "no-answer 倾向（top1 低于 floor 且候选跨文档分散）"的主控裁决版：
# top1 与 top2-4 的 file_name 全不同 **且 top1 < 0.6** 才算分散。0.6 是 §3 的分散经验线
# （比 confidence_floor=0.20 更靠前：地板只管"完全没戏"，分散管"证据各说一套"）。
_DISPERSED_TOP = 0.60
# active 档免判的"高置信硬底线"（`is_high_confidence_single_fact` 用）。取值与分散线同为
# 0.60，但**语义无关**：一个是"证据各说一套"的分散经验线（§3），一个是"敢不敢跳过判定"的
# 置信底线（§3 active 一支）。评审 nit 要求拆成两个常量，Task 8 标定时可各自独立移动。
# 独立移动时有一条约束要守住（Task 6 的模式单调性）：`_ACTIVE_FLOOR >= _DISPERSED_TOP`，
# 否则 active 会在 [_ACTIVE_FLOOR, _DISPERSED_TOP) 区间比 selective **更少**判（模式倒退）。
_ACTIVE_FLOOR = 0.60
# spec §4 `margin > medium_margin → 4`：§8 没有为 medium 档配键（只有 min/max/compound/
# low_confidence 四键），故按规格原文留常量，不擅自新增配置面。
_MEDIUM_MARGIN_CANDIDATES = 4

# ---------------------------------------------------------------------------
# 敏感词表（spec §3 "命中敏感词表（安全/合同/薪资等，常量表）"）
# ---------------------------------------------------------------------------
RISK_MARKERS: tuple[str, ...] = (
    # 合同与法务
    "合同", "协议", "违约", "赔偿", "诉讼", "仲裁", "法务", "条款", "解除", "终止",
    # 薪酬与人事
    "薪资", "薪酬", "工资", "调薪", "社保", "公积金", "个税", "期权", "股权激励",
    "裁员", "解雇", "辞退",
    # 安全与合规
    "安全", "保密", "隐私", "泄露", "权限", "授权", "密码", "密钥", "合规", "审计",
    "漏洞", "入侵", "渗透",
    # 资金与处罚
    "罚款", "处罚", "处分", "退款", "扣款", "担保",
    # 用户显式要求严格引用（§3 独立信号；reasons 词表被锁成 6 个 token，故并入 risk 发射）
    "必须引用", "严格引用", "请给出处", "原文引用", "逐条引用",
)

# ---------------------------------------------------------------------------
# 数字 / 时间 / 参数信号
# ---------------------------------------------------------------------------
# 参数词枚举（主控预裁决）：数字或时间表达式必须**伴随**其中之一，才认定 query 在问精确量值。
# 词表口径以"答错一个数就是事故"为准，不做开放式的"疑似量词"匹配。
# 匹配是子串式（中文无词边界），故单字单位只留预裁决点名的"瓦"：`米/伏/安` 会命中
# "米价/埋伏/安排"这类高频词，留着就等于给 param 信号开误报口（与裁决缘由同向）。
PARAMETER_WORDS: tuple[str, ...] = (
    "温度", "湿度", "电压", "电流", "功率", "频率", "重量", "体积", "尺寸", "精度",
    "价格", "单价", "报价", "金额", "费用", "成本", "折扣", "比例", "比率", "百分比",
    "人数", "公里", "厘米", "毫米", "瓦", "赫兹", "摄氏度",
    "时长", "天数", "小时", "分钟", "秒", "年限", "工龄", "额度", "上限", "下限",
    "阈值", "距离", "速度", "次数", "利率", "税率", "汇率", "保质期", "保修",
    "有效期", "截止", "到期", "生效", "时间", "日期",
)

# 否定约束（§3 "query 含否定/数字/时间/参数特征"里的"否定"一支）：
# 只收"显式排除/禁止"这类会被检索层读反的多字短语，单字"不"绝不入表（中文里过泛，会把
# 触发率推高到毁掉成本目标的程度——与参数信号同一条裁决缘由）。
# 与数字不同，否定可独立触发：词表本身已经窄到"命中即真排除语义"，不再要求共现量值。
NEGATION_MARKERS: tuple[str, ...] = (
    "不含", "不包括", "不包含", "不适用", "不满足", "不得", "不应", "不允许", "禁止",
    "不予", "无需", "不必", "免除",
)

# 产品型号 token：字母+数字混合标识（X200 / X-200 / KB3）。其中的数字是**身份**不是**量值**。
# 预裁决缘由：若按"含数字即触发"，评测集里 "X200 的工作温度是多少" 这类型号句会被判成
# 参数敏感 → selective 触发率虚高 → calls/query P50≤4、input tokens ↓≥30% 的成本目标打不到。
# Q[1-4] 豁免（评审 F2）：`Q3` 这类"季度"写法形态上像型号，但它同时是 `_TIME_EXPRESSION`
# 的时间支；剔除发生在匹配**之前**，不豁免则该支永不可达（"Q3 的价格是多少" 实测判不出
# param）。开头的 lookahead 只读不消费，命中条件是"字母恰为 Q/q + 数字恰为 1-4 + 后面不再
# 跟字母/数字/连接符"，故 Q3 独立成词时放行给时间支，`XQ3` / `Q3S` / `KB3` 这类真型号照旧
# 被剔除（大小写都列是为与 `_TIME_EXPRESSION` 的 `[Qq][1-4]` 同拼写；入参已小写化）。
_PRODUCT_MODEL = re.compile(
    r"(?![Qq][1-4](?![-_A-Za-z0-9]))[A-Za-z]{1,12}[-_]?\d+[A-Za-z0-9\-]*",
)

# 量值与时间表达式（在剔除型号后的文本上匹配）：
_ARABIC_QUANTITY = r"\d+(?:[.,]\d+)?"                       # 45 / 12.5 / 1,200
_CHINESE_QUANTITY = (                                        # 两年 / 三十天 / 五十元
    # 量词表刻意只留"数词+它"几乎必然是量值的组合：剔掉 人/名/台/件/条/款/角/分 这类
    # 高频多义词（"十分感谢""第三方"），误报会把 param 信号推出去。
    r"[零一二两三四五六七八九十百千万亿半]+(?:个)?\s*"
    r"(?:年|月|日|号|天|周|岁|小时|分钟|秒|元|度|次|%|％)"
)
_TIME_EXPRESSION = (                                         # 2026-09-23 / 本月 / Q3
    r"\d{2,4}\s*[-/.年]\s*\d{1,2}\s*(?:[-/.月]\s*\d{1,2}\s*日?)?"
    r"|(?:本|上|下|去|明|前|后)\s*(?:年|月|季度|半年)"
    r"|[Qq][1-4]"
)

# brief Interfaces 点名的"数字/时间/参数正则"：数字∪中文数量∪时间表达。
# 组合口径见 `_has_fact_signal`：量值须与参数词共现（显式否定短语可单独触发）；
# 不把参数词塞进正则，是为了让"型号数字不算量值"这条裁决在读代码时一眼可见。
_QUERY_FACT_SIGNAL = re.compile(
    rf"(?:{_ARABIC_QUANTITY})|(?:{_CHINESE_QUANTITY})|(?:{_TIME_EXPRESSION})",
)


def _normalize_query(query: Any) -> str:
    """折叠空白 + 转小写：与缓存键同纲，排版差异不改变规则判定。"""
    return " ".join(str(query if query is not None else "").strip().lower().split())


def _score(row: Any) -> float:
    """`rerank_score` 缺失/None/非数 ⇒ 0.0（预裁决口径：缺分不是高分）。"""
    if not isinstance(row, dict):
        return 0.0
    value = row.get("rerank_score")
    if value is None:
        return 0.0
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    # NaN 会让所有比较静默为 False，等价于"永远不触发"——按缺分处理成 0.0。
    return score if score == score else 0.0


def _top1(rows: list[dict[str, Any]]) -> float:
    return _score(rows[0]) if rows else 0.0


def _margin(rows: list[dict[str, Any]]) -> float:
    """CE 分差 = rows[0] - rows[1]；不足两行时取 0.0（触发由 `_has_margin_signal` 兜）。"""
    if len(rows) < 2:
        return 0.0
    return _top1(rows) - _score(rows[1])


def _has_margin_signal(rows: list[dict[str, Any]]) -> bool:
    # rows<2 无分差可算 ⇒ 视为触发（预裁决）：证据面太窄时不做无依据的跳过。
    if len(rows) < 2:
        return True
    return _margin(rows) < float(settings.typesafe_medium_margin)


def _is_dispersed(rows: list[dict[str, Any]]) -> bool:
    """top1 与 top2-4 的 file_name 全不同 且 top1 < `_DISPERSED_TOP`。

    文档名缺失/为空的行**不**参与"算作不同文档"：分散是要多花钱的信号，只在确证时触发。
    具体口径是"任一头部行拿不到非空文档名 ⇒ 整体判未确证（False）"，**不是**跳过缺名行继续比：
    跳过会让"两行都缺名"退化成形如 `len(set()) == len([])` 的真空真，也会让"缺名 + 三个不同
    文档名"这种半截证据被当成确证分散（两条都由用例钉住）。
    """
    if not rows or _top1(rows) >= _DISPERSED_TOP:
        return False
    head = rows[:4]
    if len(head) < 2:
        return False
    docs: list[str] = []
    for row in head:
        doc = str(row.get("file_name") or "").strip() if isinstance(row, dict) else ""
        if not doc:
            return False
        docs.append(doc)
    return len(set(docs)) == len(docs)


def _has_risk_marker(query: Any) -> bool:
    normalized = _normalize_query(query)
    return any(marker in normalized for marker in RISK_MARKERS)


def _has_fact_signal(query: Any) -> bool:
    """数字/时间/参数敏感（§3 的"否定/数字/时间/参数"一支，reasons token 统一为 `param`）。

    预裁决口径：
    - 先剔掉产品型号（`_PRODUCT_MODEL`），型号里的数字是身份不是量值；
      但 `Q1..Q4`（季度）按 `_PRODUCT_MODEL` 的开头 lookahead 豁免——它是时间支，
      一旦被一起剔掉就让 `_QUERY_FACT_SIGNAL` 的 `[Qq][1-4]` 永不可达（评审 F2）；
    - 光有数字（"X200 支持多少种接口"）或光有参数词（"设备功率看哪个指标"）都不算，
      必须**共现**；
    - 显式否定/排除短语（`NEGATION_MARKERS`）单独即触发——词表已窄到命中即是排除语义。
    缘由同 `_PRODUCT_MODEL`：宽口径会把 selective 触发率推到虚高，成本目标失效。
    """
    normalized = _normalize_query(query)
    if not normalized:
        return False
    if any(marker in normalized for marker in NEGATION_MARKERS):
        return True
    has_quantity = bool(_QUERY_FACT_SIGNAL.search(_PRODUCT_MODEL.sub(" ", normalized)))
    if not has_quantity:
        return False
    return any(word in normalized for word in PARAMETER_WORDS)


def trigger_signals(query: Any, rows: list[dict[str, Any]]) -> list[str]:
    """六类信号（spec §3）→ 稳定小写 token 列表；顺序恒为 `REASON_TOKENS` 顺序。"""
    reasons: list[str] = []
    if is_compound_query(str(query if query is not None else "")):
        reasons.append(REASON_COMPOUND)
    if _has_margin_signal(rows):
        reasons.append(REASON_MARGIN)
    if _top1(rows) < float(settings.typesafe_confidence_floor):
        reasons.append(REASON_FLOOR)
    if _has_risk_marker(query):
        reasons.append(REASON_RISK)
    if _is_dispersed(rows):
        reasons.append(REASON_DISPERSED)
    if _has_fact_signal(query):
        reasons.append(REASON_PARAM)
    return reasons


def should_judge(query: str, rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """selective 档闸门：任一信号为真即需判定（spec §3）。

    返回 `(need, reasons)`；reasons 只含 `REASON_TOKENS` 里的 token，可为空列表。
    """
    reasons = trigger_signals(query, rows)
    return bool(reasons), reasons


def is_high_confidence_single_fact(query: str, rows: list[dict[str, Any]]) -> bool:
    """active 档的免判组合（spec §3 "分差 > high_margin 且无风险信号且非 compound"）。

    在规格原文之上再叠加"高置信硬底线 top1 ≥ `_ACTIVE_FLOOR`"与"参数/否定不敏感"：
    - floor(0.20) 只表示"不是完全没戏"，active 要的"高置信"取 0.60 更贴语义，
      顺带排除跨文档分散；
    - 精确量值题（温度/价格/天数…）答错代价最高，active 不得免判。
    这样 active 的免判集恒 ⊆ selective 的免判集 ⇒ 模式越严只会多判，不倒退（Task 6 依赖）。
    注意这里读的是 `_ACTIVE_FLOOR` 而非同值的 `_DISPERSED_TOP`：两者当前都是 0.60 但语义
    不同，Task 8 各自独立标定时靠 `_ACTIVE_FLOOR >= _DISPERSED_TOP` 保单调（见常量注释）。
    """
    if len(rows) < 2:
        return False
    if _top1(rows) < _ACTIVE_FLOOR:
        return False
    if _margin(rows) <= float(settings.typesafe_high_margin):
        return False
    if is_compound_query(str(query if query is not None else "")):
        return False
    if _has_risk_marker(query) or _has_fact_signal(query):
        return False
    return True


def pick_candidate_count(query: str, rows: list[dict[str, Any]]) -> int:
    """动态 TopK（spec §4）：判定前池宽，按"低置信 > 复合 > 分差"顺序取档。

    顺序裁决（spec §4 与 brief 的 TopK 列表冲突处）：floor 档优先于 compound 档，
    两者同时命中时取更宽池（12 > 8）——低置信度下复合句更需要铺开证据。

    返回的是**池宽上限**，不承诺 rows 有那么多：调用方直接 `rows[:count]` 即可。
    """
    if _top1(rows) < float(settings.typesafe_confidence_floor):
        return int(settings.typesafe_low_confidence_candidates)
    if is_compound_query(str(query if query is not None else "")):
        return int(settings.typesafe_compound_candidates)
    margin = _margin(rows)
    if margin > float(settings.typesafe_high_margin):
        return int(settings.typesafe_min_candidates)
    if margin > float(settings.typesafe_medium_margin):
        return _MEDIUM_MARGIN_CANDIDATES
    return int(settings.typesafe_max_candidates)

# UI 文案术语基准（中文化）

本表是全端显示层文案的统一译法基准。仅改显示文案：**代码枚举值、API 字段、权限串、localStorage key、CSS 类名、变量名一律不动**。

## 状态词（枚举值 → 显示中文）

| 枚举值 | 中文 | | 枚举值 | 中文 |
| --- | --- | --- | --- | --- |
| READY | 就绪 | | ONLINE | 在线 |
| INDEXING | 索引中 | | OFFLINE | 离线 |
| PROCESSING | 处理中 | | DEGRADED | 降级 |
| FAILED | 失败 | | DISABLED | 已停用 |
| RUNNING | 进行中 | | COMPLETED | 已完成 |
| WAITING | 等待 | | OK | 正常 |
| DONE | 完成 | | DENIED | 已拒绝 |
| PENDING | 待处理 | | HIT / MISS | 命中 / 未命中 |

## 流水线与权限

- Query Rewrite→查询改写 · Vector Search→向量检索 · Keyword Search (BM25)→关键词检索（BM25） · Reranking→重排序 · Generating Answer→生成回答
- ACCESS RESTRICTED→访问受限 · REQUEST ACCESS→申请权限 · REQUEST SENT→申请已发送
- RESOURCE→资源 · POLICY→策略 · REASON→原因
- 摄取阶段：Upload→上传 · Parse→解析 · Normalize→规范化 · Chunk→切分 · Embed→向量化 · Index→索引

## 导航与通用

- 01 首页 · 02 问答 · 03 检索 · 04 知识库 · 05 检索实验室 · 06 请求追踪 · 07 评测 · 08 运营 · 09 治理 · 10 系统；分区：工作区 / 知识 / 检索 / 评测 / 运营 / 治理 / 系统
- 通用动作：UPLOAD→上传 · SEARCH→搜索 · RETRY→重试 · RETRIEVE→检索 · SAVE→保存 · CANCEL→取消 · DELETE→删除 · ARCHIVE→归档 · DISABLE/ENABLE→停用/启用 · REINDEX→重建索引 · EXPORT→导出 · RUN→运行 · OPEN→打开 · BACK→返回 · VIEW→查看 · COPY→复制 · DOWNLOAD→下载 · SIGN IN→登录 · SIGN OUT→登出
- 时间词：Today→今天 · Yesterday→昨天 · This Week→本周 · Earlier→更早
- 角色：ADMIN/SALES/HR/USER/VIEWER→管理员/销售/人事/普通用户/访客（只读）；"YOU"→本人
- 部门码：ALL→全企业 · HR→人事 · PRODUCT→产品 · SALES→销售 · SERVICE→售后（映射集中在 ui.tsx 的 departmentLabel，数据层仍存英文码）

## 保留英文（不属于文案，不翻译）

HIT@1 · HIT@3 · MRR · P50 / P95 · TTFT · Token/tokens · 模型名（BAAI/bge-small-zh-v1.5、ornith-1.5:9b 等）· 权限串 knowledge:read 等 · trace_id / 各类 ID · URL · 文件格式（PDF/CSV/DOCX/MD）· 数字编号（01–10）· API 路径与示例代码

## 风格规则

- 大写英文 kicker 改为"编号 + 中文短语"，仍用等宽字体与小字距样式；不出现中英混排的同义重复（如 "搜索 SEARCH"）。
- 错误/受限提示必须解释 资源 / 策略 / 原因，禁止裸"无权限"。
- aria-label、placeholder、title 一并中文化。

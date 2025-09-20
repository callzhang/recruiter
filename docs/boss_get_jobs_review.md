## get_jobs/Boss 模块代码走读与可落地优化建议

目标：参考 `vendor/get_jobs` 的成熟思路，优化我们现有的 Python Playwright + FastAPI 服务，提升登录稳定性、抓取质量与可维护性。

### 代码概览（关键文件）
- `vendor/get_jobs/src/main/java/boss/Boss.java`
  - 职位搜索与投递主流程（滚动加载、详情页打开、打招呼、可选图片简历）。
  - 登录流程：cookie 复用 + 二维码登录，带超时控制与滑块验证等待。
  - 黑名单更新：从消息列表页抽取公司与消息，自动扩展黑名单。
- `vendor/get_jobs/src/main/java/boss/BossConfig.java`
  - 配置集中化，包含关键词、城市编码、行业、经验、学历、规模、融资阶段、AI打招呼、是否发送图片简历、期望薪资、过滤不活跃HR等。
  - 将人类友好配置映射为站点实际编码（如城市、薪资、经验）。
- `vendor/get_jobs/src/main/java/boss/BossEnum.java`
  - 站点枚举到代码映射（城市、经验、薪资、学历、规模、融资）。
- `vendor/get_jobs/src/main/java/boss/Locators.java`
  - 定位符集中管理，降低页面改版的维护成本。
- `vendor/get_jobs/src/main/java/boss/BossScheduled.java`
  - 调度入口与安全包装，便于周期性任务执行。

### 可迁移的成熟做法（建议直接吸收）
- 配置映射层：
  - 在我们 `src/config.py` 中引入与 `BossEnum` 等价的映射，支持人类可读配置 → 站点参数的转换（城市、经验、薪资等）。
  - 使用 Pydantic 校验配置，并给出默认值与范围限制。
- 定位符集中管理：
  - 继续沿用 `src/page_selectors.py`，对照 `Locators.java` 增补聊天页、职位页、列表页定位符，避免散落的字符串。
- 登录稳定化：
  - 借鉴其“先加载 cookie → reload → 判断是否需要扫码 → 最长10分钟等待”的策略，保持我们已有的倒计时与提示，并增加滑块验证的显式等待入口（检测到 `/verify-slider` 时暂停并提示）。
  - 统一持久化为 Playwright `storage_state`，同时兼容从 ENV 注入（我们已支持 `BOSS_STORAGE_STATE_JSON/FILE`）。
- 黑名单与质量控制：
  - 在服务侧增加“黑名单自动扩充逻辑”，从消息列表页抽取负面回复关键词，更新 `data/blacklist.json`（与 get_jobs 的 `data.json` 对齐）。
- 任务/节流与稳定性：
  - 滚动加载采用“数量不再增长时停止”的判断；
  - 统一封装 `safe_text/exists/wait_for` 工具方法（我们已有 `utils.py`，可对齐命名与语义）；
  - 控制请求节奏，注入随机等待，规避风控。

### 我们现有服务的针对性优化清单
1) 登录与生命周期
   - 已改为 FastAPI + 线程池包装同步 Playwright 调用；仍需：
     - 在中间件懒加载时区分“首次冷启动”和“请求期间检查”，避免每次请求都跑完整登录校验。
     - 对滑块验证页（`/web/user/safe/verify-slider`）检测后输出可读提示并暂停继续刷新（参考 `Boss.java::waitForSliderVerify`）。

2) 选择器与抓取
   - 按 `Locators.java` 增补/更新 `page_selectors.py`：
     - 搜索/职位详情/聊天列表关键定位符（如 `CHAT_LIST_ITEM`, `LAST_MESSAGE`, `COMPANY_NAME_IN_CHAT`）。
   - 候选人/消息抓取：
     - 先做“加载完成”判定（元素出现/列表数量稳定），再开始解析。
     - 细化过滤条件（剔除筛选Tab文案、空白卡片等），减少误报。

3) 黑名单生成与持久化
   - 参考 `Boss.java::updateListData`，从消息流中抽取负面反馈关键词，更新 `data/blacklist.json`；
   - 服务启动时读取，抓取时应用，导出时一并记录，形成可溯源数据链路。

4) 配置与参数映射
   - 新增 `src/mappings.py`，迁移 `BossEnum` 的概念：
     - 城市、经验、薪资、学历、规模、融资等名称→编码映射；
   - `Settings` 支持人类可读配置（如“北京”“3-5年”“本科”“20-50K”），运行时转为 URL 参数。

5) API 与客户端
   - 在 `boss_client.py` 加入新接口：
     - `/search`（根据映射参数构建 URL 返回预览）
     - `/blacklist`（列出与增补黑名单）
   - 响应中包含 `diagnostics` 字段（如本次登录来源：storage_state/env、页面加载耗时、选择器命中数）。

6) 稳定性与可观测性
   - 日志字段结构化（action、selector、count、duration、url），便于定位“加载中卡住/未命中选择器”等问题。
   - 导出截图与原始 HTML 片段（仅在调试模式），便于快速修复选择器。

### 分步落地计划（按优先级）
- P0
  - 登录流程补全“滑块验证”提示与暂停逻辑；
  - 选择器对齐 `Locators.java` 并重写候选人/消息抓取函数；
  - 增加黑名单文件读取与应用（先只读）。
- P1
  - 引入 `mappings.py` 参数映射；
  - 增加 `/search` 预览接口；
  - 抓取增加稳定等待（数量不增时停止）。
- P2
  - 自动扩充黑名单（从消息页抽取）；
  - 结构化日志与调试导出；
  - 任务节流与重试策略抽象到 `utils`。

### 与我们现有代码的对应关系
- `Boss.java` 登录与等待 → 我们的 `ensure_login` + 倒计时 + 中间件懒加载。
- `Locators.java` → 我们的 `page_selectors.py`（需要对齐与补齐）。
- `BossConfig/BossEnum` → 我们的 `config.py` + 新的 `mappings.py`。
- 黑名单 `data.json` → 我们的 `data/blacklist.json`（新增/沿用）。

以上建议均不改变现有 API 路径与服务形态，可渐进式合入，不影响你的启动与使用方式。



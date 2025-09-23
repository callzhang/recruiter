# Boss直聘自动化机器人

> **合规提醒**：请遵守 Boss直聘服务条款与隐私政策。本系统仅用于**已登录企业/招聘方账号**下，**小流量、人工在环**方式管理候选人信息。请勿尝试绕过验证码/反爬或进行批量化高频抓取。

## 🚀 功能特性

### 核心服务
- **FastAPI后台服务** - 持续运行，支持热重载，CDP外部Chrome连接
- **自动登录管理** - 登录状态持久化，支持滑块验证
- **候选人数据提取** - 智能选择器，支持黑名单过滤
- **消息管理** - 获取对话列表，支持消息处理和历史记录
- **搜索功能** - 参数映射，支持人类可读参数
- **简历处理** - 在线简历查看，WASM文本提取，OCR图像处理
- **智能决策** - AI辅助招聘决策，YAML配置岗位要求
- **通知系统** - DingTalk集成，实时通知HR

### 技术特性
- **Playwright自动化** - 浏览器自动化，支持反爬检测，事件驱动架构
- **API接口** - RESTful API，支持客户端调用，结构化响应
- **配置管理** - 环境变量，参数映射，选择器配置
- **数据持久化** - JSONL格式，自动保存
- **错误恢复** - 页面自动重建，资源清理
- **多策略简历提取** - WASM解析，Canvas钩子，OCR回退
- **批量处理** - 并发API调用，批量简历获取

## 🏃‍♂️ 快速开始

### 方式一：后台服务模式（推荐）
```bash
# 1) 安装依赖
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install

# 2) 启动后台服务
python start_service.py

# 3) 使用客户端调用API
python boss_client.py candidates --limit 10
python boss_client.py messages --limit 5
```

### 方式二：直接API调用
```bash
# 获取候选人列表
curl "http://127.0.0.1:5001/candidates?limit=10"

# 获取服务状态
curl "http://127.0.0.1:5001/status"

# 搜索参数预览
curl "http://127.0.0.1:5001/search?city=北京&job=Python开发"
```

## 📋 API接口

### 服务状态
- `GET /status` - 获取服务状态和登录信息
- `GET /notifications` - 获取操作日志

### 数据获取
- `GET /candidates?limit=N` - 获取候选人列表
- `GET /messages?limit=N` - 获取消息列表
- `POST /messages/history` - 获取指定聊天的消息历史

### 搜索功能
- `GET /search?city=北京&job=Python开发&experience=3-5年` - 搜索参数预览

### 操作接口
- `POST /login` - 手动登录
- `POST /greet?candidate_id=1&message=你好` - 发送打招呼消息
- `POST /resume/request` - 发送简历请求给候选人

### 简历处理
- `POST /resume/online` - 查看在线简历（支持文本提取和图像捕获）
- 支持多种捕获方法：`auto`（智能选择）、`wasm`（文本提取）、`image`（图像捕获）

### AI决策
- `POST /decide/pipeline` - AI辅助招聘决策（基于YAML配置）
- `POST /decide/notify` - 发送DingTalk通知

## ⚙️ 配置说明

### 环境变量
```bash
# 服务配置
BOSS_SERVICE_HOST=127.0.0.1
BOSS_SERVICE_PORT=5001

# 登录状态
BOSS_STORAGE_STATE_FILE=data/state.json
BOSS_STORAGE_STATE_JSON='{"cookies":[...]}'

# 浏览器配置（CDP模式）
CDP_URL=http://127.0.0.1:9222
HEADLESS=false
BASE_URL=https://www.zhipin.com

# AI决策配置
OPENAI_API_KEY=your_openai_api_key
DINGTALK_WEBHOOK=your_dingtalk_webhook_url
```

### 参数映射
系统支持人类可读参数到网站编码的自动映射：
- 城市：北京 → 101010100，上海 → 101020100
- 经验：3-5年 → 105，1-3年 → 104
- 学历：本科 → 203，硕士 → 204
- 薪资：10-20K → 405，20-50K → 406

## 📁 项目结构
```
bosszhipin_bot/
├── boss_service.py          # FastAPI主服务
├── boss_client.py           # 客户端调用
├── start_service.py         # 服务启动脚本
├── src/
│   ├── config.py            # 配置管理
│   ├── mappings.py          # 参数映射
│   ├── page_selectors.py    # 页面选择器
│   ├── blacklist.py         # 黑名单管理
│   ├── resume_capture.py    # 简历捕获模块
│   ├── ocr_service.py       # OCR服务
│   └── service/             # 服务模块
│       ├── browser.py       # 浏览器管理
│       ├── login.py         # 登录服务
│       ├── messages.py      # 消息服务
│       └── resume.py        # 简历服务
├── data/
│   ├── state.json           # 登录状态
│   ├── blacklist.json       # 黑名单配置
│   └── output/              # 输出数据
├── jobs/
│   └── criteria.yaml        # 岗位要求配置
├── docs/
│   ├── status.md            # 项目状态
│   ├── technical.md         # 技术文档
│   ├── architecture.mermaid # 架构图
│   ├── canvas_image_guide.md # Canvas图像指南
│   └── client_api_migration.md # API迁移指南
├── test/                    # 测试文件
├── command.ipynb            # 演示Notebook
└── requirements.txt         # 依赖包
```

## 🔧 高级功能

### 智能简历处理
支持多种简历获取策略，自动选择最佳方法：
- **WASM文本提取** - 直接解析网站内部数据，获取结构化文本
- **Canvas钩子** - 拦截Canvas渲染，重建HTML内容
- **图像捕获** - 多种截图方法，支持分页长简历
- **OCR处理** - 本地和云端OCR，图像转文本

### AI辅助决策
基于OpenAI的智能招聘决策系统：
- **YAML配置** - 结构化岗位要求和筛选条件
- **智能匹配** - AI分析简历与岗位匹配度
- **自动通知** - DingTalk集成，实时通知HR
- **批量处理** - 支持并发处理多个候选人

### 黑名单过滤
系统支持自动过滤黑名单公司和职位：
```json
{
  "blackCompanies": ["不合适的公司"],
  "blackJobs": ["外包", "派遣"],
  "blackRecruiters": ["不合适的HR"]
}
```

### 选择器配置
支持多种选择器策略，自动适配页面变化：
- XPath选择器
- CSS选择器  
- 文本匹配
- 属性匹配

### 事件驱动架构
使用事件驱动模式，提升性能和稳定性：
- **响应监听** - 自动监听网络响应，获取JSON数据
- **页面等待** - 智能等待机制，避免time.sleep
- **缓存管理** - TTL缓存，减少重复请求

### CDP外部浏览器
使用Chrome DevTools Protocol连接外部浏览器：
- **持久会话** - 浏览器独立于服务进程
- **热重载友好** - 服务重启不影响浏览器状态
- **资源隔离** - 更好的稳定性和性能

## ⚠️ 风险控制

### 合规使用
- ✅ 仅用于已登录的企业账号
- ✅ 人工在环，避免全自动化
- ✅ 控制访问频率，避免触发风控
- ✅ 记录操作日志，便于审计

### 技术防护
- ✅ 随机延迟，模拟人工操作
- ✅ 错误检测，自动暂停
- ✅ 资源清理，避免内存泄漏
- ✅ 状态持久化，减少重复登录

## 🚀 部署建议

### 开发环境
```bash
# 启动开发服务（支持热重载）
python start_service.py
```

### 生产环境
```bash
# 使用gunicorn部署
gunicorn boss_service:app -w 4 -k uvicorn.workers.UvicornWorker
```

## 📊 监控指标

### 服务状态
- 运行时间
- 登录状态
- 操作计数
- 错误日志

### 数据统计
- 候选人数量
- 消息数量
- 成功率
- 响应时间

## 🔄 更新日志

### v2.0.0 (2025-09-23) 
- ✅ 实现智能简历处理系统（WASM + Canvas + OCR）
- ✅ 添加AI辅助招聘决策流程（OpenAI + YAML配置）
- ✅ 集成DingTalk通知系统
- ✅ 优化客户端API（ResumeResult对象，便利方法）
- ✅ 实现事件驱动架构（避免time.sleep）
- ✅ 添加CDP外部浏览器支持
- ✅ 创建交互式Notebook演示
- ✅ 完善测试覆盖和文档

### v1.0.0 (2025-09-19)
- ✅ 完成FastAPI服务架构
- ✅ 实现自动登录和状态持久化
- ✅ 支持候选人数据提取
- ✅ 添加搜索参数映射
- ✅ 支持黑名单过滤
- ✅ 实现热重载开发模式

# Boss直聘机器人技术规格

## 系统架构

### 整体架构
- **服务模式**: FastAPI + Uvicorn ASGI服务器
- **自动化引擎**: Playwright (Python) + CDP外部浏览器
- **数据存储**: JSON/JSONL文件 + 内存缓存
- **配置管理**: Pydantic + 环境变量
- **开发模式**: 热重载支持，进程隔离
- **AI集成**: OpenAI API + 本地OCR
- **消息通知**: DingTalk Webhook

### 核心组件

#### 1. 服务层 (boss_service.py)
```python
# FastAPI应用实例
app = FastAPI(title="Boss直聘机器人服务")

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化浏览器
    # 关闭时清理资源
```

#### 2. 登录管理
- **状态持久化**: 使用Playwright的`storage_state`
- **自动检测**: 检查登录URL和页面元素
- **滑块处理**: 检测并等待滑块验证
- **超时控制**: 10分钟登录等待机制

#### 3. 数据提取
- **选择器策略**: 多层级选择器，支持XPath和CSS
- **元素定位**: 文本匹配、属性匹配、类名匹配
- **数据解析**: 结构化信息提取
- **黑名单过滤**: 自动过滤不合适的公司和职位

#### 4. 简历处理系统
- **WASM文本提取**: 动态解析网站内部数据结构
- **Canvas钩子技术**: 拦截绘图API重建文本内容
- **多策略图像捕获**: toDataURL、分页截图、元素截图
- **OCR服务**: 本地pytesseract + OpenAI Vision API

#### 5. AI决策系统
- **YAML配置**: 结构化岗位要求和筛选条件
- **OpenAI集成**: GPT-4辅助简历分析和匹配
- **DingTalk通知**: 实时HR通知和推荐

#### 6. 搜索功能
- **参数映射**: 人类可读参数到网站编码的转换
- **URL生成**: 动态构建搜索URL
- **预览功能**: 参数验证和URL预览

## API接口规范

### RESTful API设计
```python
# 服务状态
GET /status
Response: {
    "status": "running",
    "logged_in": true,
    "timestamp": "2025-09-19T16:10:24.370798",
    "notifications_count": 13
}

# 候选人列表
GET /candidates?limit=10
Response: {
    "success": true,
    "candidates": [...],
    "count": 2,
    "timestamp": "2025-09-19T16:10:34.013659"
}

# 搜索预览
GET /search?city=北京&job=Python开发
Response: {
    "success": true,
    "preview": {
        "base": "https://www.zhipin.com/web/geek/job?",
        "params": {
            "city": "101010100",
            "jobType": "1901",
            "salary": "0",
            "experience": "105"
        }
    }
}
```

### 错误处理
```python
# 统一错误响应格式
{
    "success": false,
    "error": "错误描述",
    "timestamp": "2025-09-19T16:10:24.370798"
}
```

## 配置管理

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
SLOWMO_MS=1000

# AI决策配置
OPENAI_API_KEY=your_openai_api_key
DINGTALK_WEBHOOK=your_dingtalk_webhook_url
```

### 参数映射表
```python
# 城市编码映射
CITY_CODE = {
    "北京": "101010100",
    "上海": "101020100", 
    "杭州": "101210100",
    "广州": "101280100",
    "深圳": "101280600"
}

# 经验要求映射
EXPERIENCE = {
    "在校生": "108",
    "应届毕业生": "102", 
    "1-3年": "104",
    "3-5年": "105",
    "5-10年": "106"
}
```

## 选择器策略

### 多层级选择器
```python
def conversation_list_items() -> List[str]:
    return [
        # 主要选择器
        "xpath=//div[contains(@class,'list') or contains(@class,'conversation')]//li",
        # 备用选择器
        "xpath=//ul/li[contains(@class,'item')]",
        # 文本匹配选择器
        "xpath=//div[contains(.,'年') or contains(.,'经验')]",
        # CSS选择器
        "div.chat-list-box ul li.item"
    ]
```

### 选择器优先级
1. **XPath文本匹配** - 最稳定，基于文本内容
2. **XPath属性匹配** - 基于class/id属性
3. **CSS选择器** - 性能最好
4. **文本选择器** - 兜底方案

## 数据流设计

### 候选人数据流
```
用户请求 → API接口 → 页面访问 → 元素定位 → 数据提取 → 黑名单过滤 → 结构化输出 → 文件保存
```

### 消息数据流
```
用户请求 → API接口 → 页面访问 → 消息列表定位 → 消息内容提取 → 时间戳处理 → JSON输出
```

### 搜索数据流
```
用户参数 → 参数映射 → 编码转换 → URL构建 → 预览输出
```

## 错误处理机制

### 页面错误处理
```python
# 页面访问失败
try:
    self.page.goto(url, timeout=60000)
except Exception as e:
    self.add_notification(f"页面访问失败: {e}", "error")
    # 尝试重新创建页面
    self._recreate_page()
```

### 元素定位失败
```python
# 多选择器尝试
for selector in selectors:
    try:
        elements = self.page.locator(selector).all()
        if elements:
            break
    except Exception:
        continue
```

### 网络超时处理
```python
# 超时重试机制
for attempt in range(3):
    try:
        result = self.page.wait_for_selector(selector, timeout=10000)
        break
    except TimeoutError:
        if attempt == 2:
            raise Exception("元素定位超时")
        time.sleep(1)
```

## 性能优化

### 选择器优化
- **缓存机制**: 选择器结果缓存
- **批量操作**: 一次性获取多个元素
- **智能等待**: 基于网络状态等待

### 内存管理
- **资源清理**: 自动关闭页面和上下文
- **状态持久化**: 避免重复登录
- **垃圾回收**: 定期清理无用对象

### 并发处理
- **线程安全**: 使用锁保护Playwright操作
- **异步处理**: FastAPI异步支持
- **资源隔离**: 每个请求独立的页面实例

## 安全考虑

### 反爬虫对策
- **随机延迟**: 模拟人工操作节奏
- **用户代理**: 使用真实浏览器标识
- **Cookie管理**: 保持登录状态
- **行为模拟**: 鼠标移动、滚动等

### 数据安全
- **本地存储**: 数据不离开本地环境
- **状态加密**: 登录状态文件保护
- **访问控制**: API接口权限控制
- **日志审计**: 操作记录和追踪

## 监控和日志

### 操作日志
```python
# 通知系统
def add_notification(self, message: str, level: str = "info"):
    notification = {
        "id": len(self.notifications) + 1,
        "message": message,
        "level": level,
        "timestamp": datetime.now().isoformat()
    }
    self.notifications.append(notification)
```

### 性能监控
- **响应时间**: API请求处理时间
- **成功率**: 操作成功比例
- **错误率**: 失败操作统计
- **资源使用**: 内存和CPU使用情况

## 部署架构

### 开发环境
```bash
# 热重载开发
python start_service.py
# 自动重启和代码更新
uvicorn boss_service:app --reload
```

### 生产环境
```bash
# 多进程部署
gunicorn boss_service:app -w 4 -k uvicorn.workers.UvicornWorker
# 负载均衡
nginx + gunicorn
```

### 容器化部署
```dockerfile
FROM python:3.9-slim
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install
COPY . .
CMD ["python", "start_service.py"]
```

## 扩展性设计

### 插件系统
- **选择器插件**: 自定义页面选择器
- **数据处理器**: 自定义数据解析逻辑
- **通知插件**: 自定义通知方式

### API扩展
- **中间件支持**: 请求/响应处理
- **认证系统**: API密钥管理
- **限流控制**: 请求频率限制

### 数据源扩展
- **多平台支持**: 支持其他招聘网站
- **数据格式**: 支持多种输出格式
- **集成接口**: 与外部系统集成
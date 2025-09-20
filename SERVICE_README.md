# Boss直聘后台服务系统

## 概述

这是一个基于Flask的Boss直聘后台服务系统，可以保持浏览器登录状态，提供API接口来获取候选人信息和执行各种操作。

## 架构

- **后台服务** (`boss_service.py`) - 保持浏览器登录状态，提供REST API
- **客户端** (`boss_client.py`) - 调用API的客户端工具
- **启动脚本** (`start_service.py`) - 一键启动服务

## 快速开始

### 1. 启动后台服务

```bash
# 方法1: 使用启动脚本（推荐）
python start_service.py

# 方法2: 直接启动
python boss_service.py
```

服务启动后会：
- 自动安装依赖
- 启动浏览器
- 检查登录状态（如需要会等待用户登录）
- 启动Flask API服务
- 开始代码监控（自动重启）

### 2. 使用客户端

```bash
# 检查服务状态
python boss_client.py status

# 获取候选人列表
python boss_client.py candidates --limit 10

# 获取消息列表
python boss_client.py messages --limit 5

# 发送打招呼消息
python boss_client.py greet --candidate-id 1 --message "您好，我对您的简历很感兴趣"

# 获取候选人简历
python boss_client.py resume --candidate-id 1
```

## API接口

### GET /status
获取服务状态
```json
{
  "status": "running",
  "logged_in": true,
  "timestamp": "2025-01-19T11:30:00"
}
```

### POST /login
登录接口
```json
{
  "success": true,
  "message": "登录成功",
  "timestamp": "2025-01-19T11:30:00"
}
```

### GET /candidates?limit=10
获取候选人列表
```json
{
  "success": true,
  "candidates": [
    {
      "id": 1,
      "raw_text": "候选人信息...",
      "age": "25岁",
      "education": "本科",
      "experience": "3年经验",
      "location": "北京市",
      "timestamp": "2025-01-19T11:30:00"
    }
  ],
  "count": 1,
  "timestamp": "2025-01-19T11:30:00"
}
```

### GET /messages?limit=10
获取消息列表（与候选人列表相同）

### POST /greet
发送打招呼消息
```json
{
  "candidate_id": 1,
  "message": "您好，我对您的简历很感兴趣"
}
```

### GET /resume?candidate_id=1
获取候选人简历

## 特性

### 1. 持久化登录
- 自动保存cookies和localStorage
- 服务重启后自动恢复登录状态
- 登录失效时自动提示重新登录

### 2. 代码热更新
- 监控代码文件变化
- 检测到更新时自动重启服务
- 无需手动重启

### 3. 智能等待
- 页面加载等待（最长10分钟）
- 登录状态检测
- 倒计时显示

### 4. 错误处理
- 完善的异常处理
- 详细的错误信息
- 自动重试机制

## 配置

可以通过环境变量或修改 `src/config.py` 来配置：

```python
BASE_URL = "https://www.zhipin.com"
HEADLESS = False  # 是否无头模式
SLOWMO_MS = 1000  # 操作延迟
```

## 开发

### 添加新功能

1. 在 `BossService` 类中添加新方法
2. 在 `setup_routes()` 中添加新的API路由
3. 在 `boss_client.py` 中添加对应的客户端方法

### 调试

```bash
# 启动调试模式
FLASK_DEBUG=1 python boss_service.py

# 查看日志
tail -f logs/boss_service.log
```

## 注意事项

1. **合规使用**: 请遵守Boss直聘服务条款，小流量、人工在环方式使用
2. **网络稳定**: 确保网络连接稳定，避免频繁断线
3. **资源管理**: 服务会保持浏览器进程，注意系统资源使用
4. **数据安全**: 登录状态文件包含敏感信息，请妥善保管

## 故障排除

### 服务无法启动
```bash
# 检查端口是否被占用
lsof -i :5000

# 检查依赖是否安装
pip install -r requirements.txt
```

### 登录失败
```bash
# 删除登录状态文件重新登录
rm data/state.json
python start_service.py
```

### 浏览器问题
```bash
# 重新安装Playwright浏览器
python -m playwright install
```

## 更新日志

- 2025-01-19: 初始版本，支持基本的候选人信息获取
- 计划: 添加打招呼、简历获取等功能

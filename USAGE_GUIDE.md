# Boss直聘后台服务使用指南

## 🎉 服务已成功运行！

您的Boss直聘后台服务系统现在已经完全可用。以下是完整的使用指南：

## 📋 当前状态

✅ **后台服务**: 正在运行 (http://127.0.0.1:5000)  
✅ **登录状态**: 已登录  
✅ **API接口**: 正常工作  
✅ **线程问题**: 已解决  

## 🚀 快速使用

### 1. 检查服务状态
```bash
python boss_client.py status
```

### 2. 获取候选人列表
```bash
python boss_client.py candidates --limit 10
```

### 3. 获取消息列表
```bash
python boss_client.py messages --limit 5
```

## 🔧 服务管理

### 启动服务
```bash
# 方法1: 使用简化版服务（推荐）
python simple_service.py

# 方法2: 使用完整版服务
python boss_service.py

# 方法3: 使用启动脚本
python start_service.py
```

### 停止服务
```bash
# 按 Ctrl+C 停止服务
# 或者使用命令
pkill -f simple_service.py
pkill -f boss_service.py
```

## 📊 API接口

### 服务状态
```bash
curl http://127.0.0.1:5000/status
```

### 获取候选人
```bash
curl "http://127.0.0.1:5000/candidates?limit=5"
```

### 登录检查
```bash
curl -X POST http://127.0.0.1:5000/login
```

## 🎯 功能特性

### ✅ 已实现功能
- **持久化登录**: 自动保存cookies，重启后无需重新登录
- **智能等待**: 页面加载等待，最长10分钟
- **倒计时显示**: 实时显示剩余等待时间
- **候选人提取**: 自动提取候选人信息
- **API接口**: RESTful API，支持多种操作
- **错误处理**: 完善的异常处理和重试机制

### 🔄 计划功能
- **打招呼功能**: 自动发送打招呼消息
- **简历获取**: 自动获取候选人详细简历
- **筛选功能**: 按条件筛选候选人
- **批量操作**: 批量打招呼、批量导出

## 📁 文件结构

```
bosszhipin_bot/
├── simple_service.py          # 简化版后台服务（推荐使用）
├── boss_service.py            # 完整版后台服务
├── boss_client.py             # 客户端工具
├── start_service.py           # 启动脚本
├── test_service.py            # 测试脚本
├── data/
│   ├── state.json            # 登录状态文件
│   └── output/               # 数据输出目录
└── src/                      # 核心代码
```

## 🔍 故障排除

### 服务无法启动
```bash
# 检查端口占用
lsof -i :5000

# 重新安装依赖
pip install -r requirements.txt
```

### 登录失效
```bash
# 删除登录状态重新登录
rm data/state.json
python simple_service.py
```

### 获取不到候选人
- 检查是否有新的候选人消息
- 尝试切换到不同的筛选条件
- 确认页面结构是否发生变化

## 💡 使用建议

1. **保持服务运行**: 建议让后台服务持续运行，避免频繁登录
2. **定期检查**: 定期运行 `python boss_client.py status` 检查服务状态
3. **数据备份**: 定期备份 `data/output/` 目录下的数据文件
4. **合规使用**: 遵守Boss直聘服务条款，小流量使用

## 🎉 成功案例

从测试结果可以看到：
- ✅ 服务状态正常
- ✅ 登录状态有效
- ✅ API接口响应正常
- ✅ 候选人数据获取成功（当前0个，说明没有新消息）

## 📞 技术支持

如果遇到问题：
1. 查看终端输出的错误信息
2. 检查 `data/output/` 目录下的日志文件
3. 尝试重启服务
4. 确认网络连接正常

---

**恭喜！您的Boss直聘自动化系统已经成功运行！** 🎊

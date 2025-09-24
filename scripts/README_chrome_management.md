# Chrome进程管理说明

## 问题解决

### 1. 避免重复启动Chrome

**问题**: 每次运行 `python start_service.py` 都会启动新的Chrome进程，导致多个Chrome实例运行。

**解决方案**:
- 启动前检查Chrome是否已在指定端口运行
- 如果已运行，跳过启动步骤
- 如果未运行，清理旧进程后启动新实例

### 2. 避免所有URL被测试Chrome打开

**问题**: 测试Chrome会拦截所有本地URL，影响正常浏览。

**解决方案**:
- 使用独立的用户数据目录 (`--user-data-dir`)
- 添加限制参数避免干扰正常浏览
- 设置默认页面为空白页

## 使用方法

### 自动管理 (推荐)

```bash
# 启动服务 (自动管理Chrome)
python start_service.py

# 环境变量配置
export CDP_PORT=9222                    # Chrome调试端口
export BOSSZP_USER_DATA=/tmp/bosszhipin_profile  # Chrome用户数据目录
export CLEANUP_CHROME_ON_EXIT=true     # 退出时清理Chrome (可选)
```

### 手动管理Chrome

```bash
# 检查Chrome状态
python scripts/manage_chrome.py status

# 启动Chrome
python scripts/manage_chrome.py start

# 停止Chrome
python scripts/manage_chrome.py stop

# 重启Chrome
python scripts/manage_chrome.py restart

# 自定义端口和用户数据目录
python scripts/manage_chrome.py start --port 9223 --user-data /tmp/my_profile
```

## Chrome配置说明

### 关键参数

- `--remote-debugging-port={port}`: 启用CDP调试端口
- `--user-data-dir={dir}`: 独立用户数据目录，避免与正常Chrome冲突
- `--no-first-run`: 跳过首次运行设置
- `--disable-extensions`: 禁用扩展，提高性能
- `--disable-sync`: 禁用同步，避免干扰
- `--disable-web-security`: 禁用Web安全限制（仅测试环境）
- `--no-sandbox`: 禁用沙盒（仅测试环境）

### 限制参数

- `--restrict-http-scheme`: 限制HTTP协议
- `--disable-background-timer-throttling`: 禁用后台定时器限制
- `--disable-renderer-backgrounding`: 禁用渲染器后台化
- `--disable-backgrounding-occluded-windows`: 禁用被遮挡窗口后台化

## 故障排除

### Chrome启动失败

1. 检查端口是否被占用:
   ```bash
   lsof -i :9222
   ```

2. 清理旧进程:
   ```bash
   python scripts/manage_chrome.py stop
   ```

3. 检查Chrome路径:
   ```bash
   which google-chrome  # Linux
   ls /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome  # macOS
   ```

### 服务连接失败

1. 检查Chrome状态:
   ```bash
   python scripts/manage_chrome.py status
   ```

2. 重启Chrome:
   ```bash
   python scripts/manage_chrome.py restart
   ```

3. 检查CDP连接:
   ```bash
   curl http://localhost:9222/json/version
   ```

## 最佳实践

1. **开发环境**: 使用默认配置，Chrome保持运行状态
2. **测试环境**: 设置 `CLEANUP_CHROME_ON_EXIT=true` 自动清理
3. **生产环境**: 使用独立的用户数据目录和端口
4. **调试**: 使用 `manage_chrome.py` 工具进行精细控制

## 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `CDP_PORT` | 9222 | Chrome调试端口 |
| `BOSSZP_USER_DATA` | /tmp/bosszhipin_profile | Chrome用户数据目录 |
| `CLEANUP_CHROME_ON_EXIT` | false | 退出时是否清理Chrome |
| `BOSS_SERVICE_HOST` | 127.0.0.1 | 服务监听地址 |
| `BOSS_SERVICE_PORT` | 5001 | 服务监听端口 |

# Client API 优化与迁移指南

## 🎯 概述

Boss Client API 已经过全面优化，提供了更强大、更易用的接口。本指南帮助用户从旧API迁移到新API。

## 🚀 新功能亮点

### 1. ResumeResult 结构化对象
- 替代原始的字典返回值
- 提供类型安全和智能提示
- 内置便利方法和属性

### 2. 便利方法
- `get_resume_text()` - 快速获取文本
- `get_resume_image()` - 快速获取图片
- `get_resume_with_fallback()` - 自动回退机制

### 3. 批量处理
- `batch_get_resumes()` - 并发批量获取
- `get_candidates_with_resumes()` - 候选人+简历组合

### 4. 改进的错误处理
- 统一的错误格式
- 网络超时和重试
- 详细的错误信息

### 5. 上下文管理器支持
- 自动资源清理
- 更好的连接管理

## 📋 API 迁移对照表

### 基础方法迁移

| 旧API | 新API | 说明 |
|-------|-------|------|
| `client.view_online_resume(chat_id)` | `client.get_resume(chat_id, "auto")` | 返回ResumeResult对象 |
| `client.get_online_resume_b64(chat_id)` | `client.get_resume(chat_id, "image")` | 专用图片捕获 |
| `client.get_messages_list()` | `client.get_messages()` | 保持兼容 |

### 新增capture_method参数

```python
# 旧API
result = client.view_online_resume(chat_id)

# 新API - 自动模式（推荐）
result = client.get_resume(chat_id, "auto")

# 新API - 仅WASM文本提取
result = client.get_resume(chat_id, "wasm")

# 新API - 仅截图方法
result = client.get_resume(chat_id, "image")
```

### 结果处理迁移

```python
# 旧API
response = client.view_online_resume(chat_id)
if response.get('success'):
    text = response.get('text')
    image_b64 = response.get('image_base64')
    if image_b64:
        with open('resume.png', 'wb') as f:
            f.write(base64.b64decode(image_b64))

# 新API
result = client.get_resume(chat_id)
if result.success:
    if result.has_text:
        result.save_text('resume.txt')
    if result.has_image:
        result.save_image('resume.png')
        # 或保存所有图片
        saved_files = result.save_all_images('./images')
```

### 便利方法示例

```python
# 快速获取文本
text = client.get_resume_text(chat_id)
if text:
    print(f"简历文本: {len(text)} 字符")

# 快速获取并保存图片
image_path = client.get_resume_image(chat_id, 'resume.png')
if image_path:
    print(f"图片保存到: {image_path}")

# 带回退的可靠获取
result = client.get_resume_with_fallback(chat_id, preferred_method="wasm")
```

### 批量处理示例

```python
# 批量获取简历
chat_ids = ['id1', 'id2', 'id3']
results = client.batch_get_resumes(chat_ids, capture_method="wasm", max_workers=3)

for chat_id, result in results.items():
    if result.success:
        print(f"{chat_id}: 成功")
    else:
        print(f"{chat_id}: 失败 - {result.error}")

# 候选人+简历组合
candidates = client.get_candidates_with_resumes(limit=5, capture_method="auto")
for candidate in candidates:
    name = candidate['candidate']
    resume = candidate['resume']
    print(f"{name}: {'有文本' if resume.has_text else '仅图片'}")
```

### 上下文管理器

```python
# 推荐用法
with BossClient() as client:
    if not client.is_service_healthy():
        print("服务不可用")
        return
    
    result = client.get_resume(chat_id)
    # 自动清理资源
```

## 🔄 command.ipynb 迁移

### 迁移步骤

1. **更新简历获取调用**
```python
# 旧代码
fetched = client.get_online_resume_b64(CHAT_ID)
if fetched.get('success'):
    img_b64 = fetched['image_base64']

# 新代码
fetched = client.get_resume(CHAT_ID, capture_method="auto")
if fetched.success:
    # 优先使用文本，回退到图片
    if fetched.has_text:
        text_data = fetched.text
    elif fetched.has_image:
        img_b64 = fetched.image_base64 or fetched.images_base64[0]
```

2. **更新错误处理**
```python
# 旧代码
if not fetched.get('success'):
    raise RuntimeError(f'拉取失败: {fetched}')

# 新代码
if not fetched.success:
    raise RuntimeError(f'拉取失败: {fetched.error}')
```

3. **利用新的便利方法**
```python
# 简化的决策函数
def run_decision_optimized(chat_id: str):
    # 优先获取文本数据
    text = client.get_resume_text(chat_id)
    
    if text:
        # 直接使用文本数据
        md_text = text
    else:
        # 回退到图片OCR
        image_path = client.get_resume_image(chat_id)
        if image_path:
            md_text = client.ocr_local_from_file(image_path)
        else:
            raise RuntimeError('无法获取简历数据')
    
    # 继续决策流程...
```

## 🛠️ 命令行接口

新版本提供了强大的命令行接口：

```bash
# 检查服务状态
python boss_client.py status

# 获取消息列表
python boss_client.py messages

# 获取简历（自动模式）
python boss_client.py resume --chat-id YOUR_CHAT_ID

# 获取简历（指定方法和保存目录）
python boss_client.py resume --chat-id YOUR_CHAT_ID --capture-method wasm --save-dir ./output
```

## 🔍 错误处理改进

### 网络错误
```python
# 自动处理超时、连接错误等
result = client.get_resume(chat_id)
if not result.success:
    if "timeout" in result.error.lower():
        print("请求超时，请重试")
    elif "connection" in result.error.lower():
        print("连接失败，请检查服务状态")
```

### 参数验证
```python
# 自动验证capture_method参数
result = client.get_resume(chat_id, "invalid_method")
# 返回: success=False, error="无效的capture_method: invalid_method"
```

## 📊 性能优化

1. **连接复用**: 使用session对象复用HTTP连接
2. **并发处理**: 批量操作支持多线程
3. **智能回退**: 自动选择最快的可用方法
4. **内存优化**: 结构化对象减少内存使用

## 🎯 最佳实践

1. **使用上下文管理器**确保资源清理
2. **优先使用便利方法**简化常见操作
3. **利用批量处理**提高效率
4. **使用回退机制**提高可靠性
5. **检查服务健康状态**确保可用性

## 🚨 注意事项

1. 旧的`get_online_resume_b64`方法在新版本中已移除
2. 返回格式从字典改为ResumeResult对象
3. 错误信息格式有所变化
4. 新增了capture_method参数，默认为"auto"

## 📚 更多资源

- [API文档](./api_reference.md)
- [示例代码](../examples/)
- [测试用例](../scripts/test_optimized_client.py)
- [性能基准](../benchmarks/)

---

通过这些改进，Boss Client API现在提供了更强大、更易用、更可靠的接口，同时保持了对现有代码的最大兼容性。

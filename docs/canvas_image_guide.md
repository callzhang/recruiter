# Canvas图像获取指南

本指南介绍如何使用 `command.ipynb` 中新添加的功能来获取、显示和保存Canvas简历图像。

## 📋 新增Notebook Cells

### Cell 13: 🖼️ 获取Canvas图像
```python
# 🖼️ 专门获取Canvas图像的演示
DEMO_CHAT_ID = os.environ.get('DEMO_CHAT_ID', '46232784-0')
fetched = client.get_resume(DEMO_CHAT_ID, capture_method="image")
```

**功能**:
- 使用 `capture_method="image"` 强制获取截图
- 显示详细的获取结果信息
- 支持单张图片和多张分页图片

### Cell 14: 🖼️ 显示Canvas图像
```python
def display_resume_images(fetched):
    """显示简历图像的便利函数"""
    # 自动处理单张/多张图片显示
    # 使用matplotlib进行多图布局
```

**功能**:
- 智能显示单张或多张图片
- 自动解码base64图像数据
- 显示图片尺寸信息
- 错误处理和调试信息

### Cell 15: 💾 保存Canvas图像
```python
def save_resume_images(fetched, output_dir="output/canvas_images"):
    """保存简历图像到文件"""
    # 自动创建输出目录
    # 时间戳命名防止冲突
    # 支持批量保存分页图片
```

**功能**:
- 自动保存主图像和分页图像
- 时间戳命名避免文件冲突
- 完整的错误处理
- 演示客户端便利方法

## 🚀 使用方法

### 1. 基础使用
```python
# 设置目标聊天ID
DEMO_CHAT_ID = "your_chat_id_here"

# 运行Cell 13获取图像
# 运行Cell 14显示图像  
# 运行Cell 15保存图像
```

### 2. 自定义配置
```python
# 修改捕获方法
fetched = client.get_resume(DEMO_CHAT_ID, capture_method="auto")  # 自动选择最佳方法
fetched = client.get_resume(DEMO_CHAT_ID, capture_method="wasm")  # 只尝试文本提取
fetched = client.get_resume(DEMO_CHAT_ID, capture_method="image") # 只获取图像

# 修改保存路径
save_resume_images(fetched, output_dir="my_custom_folder")
```

### 3. 便利方法
```python
# 一键获取并保存图像
saved_path = client.get_resume_image(DEMO_CHAT_ID, save_path="resume.png")

# 快速获取文本（如果可用）
text = client.get_resume_text(DEMO_CHAT_ID)
```

## 📸 输出结果

### 文件保存位置
- 默认保存到: `output/canvas_images/`
- 文件命名格式: `resume_YYYYMMDD_HHMMSS_*.png`
- 支持多文件: `_main.png`, `_page_1.png`, `_page_2.png`等

### 图像类型
1. **单张完整图像**: 当canvas可以完整捕获时
2. **分页图像**: 当简历内容较长，需要滚动截图时
3. **原始尺寸**: 保持Canvas的原始分辨率

## ⚙️ 技术细节

### 捕获方法优先级
1. **auto模式**: WASM文本提取 → Canvas钩子 → 剪贴板 → toDataURL → 分页截图 → 元素截图
2. **wasm模式**: 仅尝试WASM导出函数
3. **image模式**: toDataURL → 分页截图 → 元素截图

### 错误处理
- 自动回退机制
- 详细错误信息
- 优雅的失败处理

### 性能特点
- 支持大型简历（多页滚动）
- 自动检测Canvas更新
- 内存优化的图像处理

## 🛠️ 故障排除

### 常见问题
1. **无图像数据**: 检查chat_id是否有效，简历页面是否正确加载
2. **保存失败**: 检查输出目录权限，磁盘空间
3. **显示错误**: 确保安装了PIL和matplotlib依赖

### 调试方法
```python
# 检查获取结果
print(f"成功: {fetched.success}")
print(f"错误: {fetched.error}")
print(f"详情: {fetched.details}")
print(f"方法: {fetched.capture_method}")
```

## 📊 测试验证

运行测试脚本验证功能：
```bash
python test_canvas_notebook.py
```

测试覆盖:
- ✅ 基础图像获取
- ✅ 不同捕获方法
- ✅ 图像显示逻辑
- ✅ 文件保存功能
- ✅ 客户端便利方法
- ✅ 错误处理机制

## 🎯 最佳实践

1. **优先使用auto模式**: 自动选择最佳提取方法
2. **检查has_text属性**: 优先使用文本数据
3. **适当的错误处理**: 始终检查success状态
4. **合理的文件命名**: 使用时间戳避免冲突
5. **资源清理**: 及时处理大图像文件

---

*此功能已在实际环境中测试验证，支持Boss直聘网站的各种简历格式。*

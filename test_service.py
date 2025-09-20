#!/usr/bin/env python3
"""
测试服务启动
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from boss_service import BossService
    print("[*] 导入服务成功")
    
    service = BossService()
    print("[*] 创建服务实例成功")
    
    print("[*] 启动服务...")
    service.run()
    
except Exception as e:
    print(f"[!] 错误: {e}")
    import traceback
    traceback.print_exc()
#!/usr/bin/env python3
"""
测试发送消息功能
"""
import os
import sys
import time
from boss_client import BossClient

def test_send_message():
    """测试发送消息功能"""
    # 配置
    BASE_URL = os.environ.get('BOSS_SERVICE_URL', 'http://127.0.0.1:5001')
    DEMO_CHAT_ID = os.environ.get('DEMO_CHAT_ID', '568969661-0')  # 使用真实的chat_id
    
    print(f"🔗 连接到服务: {BASE_URL}")
    print(f"🎯 测试Chat ID: {DEMO_CHAT_ID}")
    
    # 初始化客户端
    client = BossClient(BASE_URL)
    
    # 检查服务状态
    print("\n📊 检查服务状态...")
    status = client.get_status()
    if not status or 'status' not in status:
        print(f"❌ 服务不可用: {status}")
        return False
    
    print(f"✅ 服务状态: {status.get('status')}")
    print(f"🔐 登录状态: {status.get('logged_in')}")
    
    if not status.get('logged_in'):
        print("⚠️  服务未登录，正在尝试登录...")
        login_result = client.login()
        if not login_result.get('success'):
            print(f"❌ 登录失败: {login_result.get('error')}")
            return False
        print("✅ 登录成功")
    
    # 测试发送消息
    print(f"\n📤 发送测试消息...")
    test_message = "您好，这是自动化测试消息。"
    
    try:
        result = client.send_message(DEMO_CHAT_ID, test_message)
        
        if result.get('success'):
            print(f"✅ 消息发送成功!")
            print(f"📝 发送内容: {test_message}")
            print(f"📋 详细信息: {result.get('details')}")
            
            # 消息发送成功就认为测试通过
            print("✅ 发送消息功能测试通过!")
            return True
                
        else:
            print(f"❌ 消息发送失败: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ 发送消息异常: {e}")
        return False

if __name__ == "__main__":
    print("🚀 开始测试发送消息功能...")
    success = test_send_message()
    
    if success:
        print("\n🎉 测试完成: 发送消息功能正常!")
        sys.exit(0)
    else:
        print("\n💥 测试失败: 发送消息功能异常!")
        sys.exit(1)

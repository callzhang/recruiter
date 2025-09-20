#!/usr/bin/env python3
"""
Boss直聘客户端 - 调用后台服务API
"""
import requests
import json
import argparse
import sys
from datetime import datetime

class BossClient:
    def __init__(self, base_url='http://127.0.0.1:5001'):
        self.base_url = base_url
    
    def get_status(self):
        """获取服务状态"""
        try:
            response = requests.get(f"{self.base_url}/status")
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_notifications(self, limit=10):
        """获取通知列表"""
        try:
            response = requests.get(f"{self.base_url}/notifications", params={'limit': limit})
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def login(self):
        """登录"""
        try:
            response = requests.post(f"{self.base_url}/login")
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_candidates(self, limit=10):
        """获取候选人列表"""
        try:
            response = requests.get(f"{self.base_url}/candidates", params={'limit': limit})
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_messages(self, limit=10):
        """获取消息列表"""
        try:
            response = requests.get(f"{self.base_url}/messages", params={'limit': limit})
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def send_greeting(self, candidate_id, message=None):
        """发送打招呼消息"""
        try:
            data = {
                'candidate_id': candidate_id,
                'message': message or '您好，我对您的简历很感兴趣，希望能进一步沟通。'
            }
            response = requests.post(f"{self.base_url}/greet", json=data)
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def get_resume(self, candidate_id):
        """获取候选人简历"""
        try:
            response = requests.get(f"{self.base_url}/resume", params={'candidate_id': candidate_id})
            return response.json()
        except Exception as e:
            return {"error": str(e)}

def print_json(data):
    """格式化打印JSON数据"""
    print(json.dumps(data, ensure_ascii=False, indent=2))

def main():
    parser = argparse.ArgumentParser(description='Boss直聘客户端')
    parser.add_argument('command', choices=['status', 'login', 'candidates', 'messages', 'greet', 'resume'], 
                       help='要执行的命令')
    parser.add_argument('--limit', type=int, default=10, help='限制数量')
    parser.add_argument('--candidate-id', type=int, help='候选人ID')
    parser.add_argument('--message', type=str, help='打招呼消息')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='服务地址')
    parser.add_argument('--port', type=int, default=5001, help='服务端口')
    
    args = parser.parse_args()
    
    client = BossClient(f"http://{args.host}:{args.port}")
    
    if args.command == 'status':
        result = client.get_status()
        print_json(result)
    
    elif args.command == 'login':
        result = client.login()
        print_json(result)
    
    elif args.command == 'candidates':
        result = client.get_candidates(args.limit)
        if result.get('success'):
            print(f"找到 {result['count']} 个候选人:")
            for i, candidate in enumerate(result['candidates'], 1):
                print(f"\n候选人 {i}:")
                print(f"  ID: {candidate.get('id')}")
                print(f"  原始文本: {candidate.get('raw_text', '')[:100]}...")
                if 'age' in candidate:
                    print(f"  年龄: {candidate['age']}")
                if 'education' in candidate:
                    print(f"  教育: {candidate['education']}")
                if 'experience' in candidate:
                    print(f"  经验: {candidate['experience']}")
                if 'location' in candidate:
                    print(f"  地点: {candidate['location']}")
        else:
            print_json(result)
    
    elif args.command == 'messages':
        result = client.get_messages(args.limit)
        if result.get('success'):
            print(f"找到 {result['count']} 条消息:")
            for i, message in enumerate(result['messages'], 1):
                print(f"\n消息 {i}:")
                print(f"  内容: {message.get('raw_text', '')[:100]}...")
        else:
            print_json(result)
    
    elif args.command == 'greet':
        if not args.candidate_id:
            print("错误: 需要指定 --candidate-id")
            sys.exit(1)
        result = client.send_greeting(args.candidate_id, args.message)
        print_json(result)
    
    elif args.command == 'resume':
        if not args.candidate_id:
            print("错误: 需要指定 --candidate-id")
            sys.exit(1)
        result = client.get_resume(args.candidate_id)
        print_json(result)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
优化的Boss直聘客户端 - 调用后台服务API
提供更简洁、强大的接口
"""
import requests
import os
import base64
import io
import subprocess
import yaml
import json
import argparse
import sys
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass


@dataclass
class ResumeResult:
    """简历捕获结果"""
    success: bool
    chat_id: str
    capture_method: str
    text: Optional[str] = None
    html: Optional[str] = None
    image_base64: Optional[str] = None
    images_base64: Optional[List[str]] = None
    data_url: Optional[str] = None
    width: int = 0
    height: int = 0
    details: str = ""
    timestamp: Optional[str] = None
    error: Optional[str] = None

    @property
    def has_text(self) -> bool:
        """是否包含文本数据"""
        return bool(self.text)
    
    @property
    def has_image(self) -> bool:
        """是否包含图片数据"""
        return bool(self.image_base64) or bool(self.images_base64)
    
    @property
    def image_count(self) -> int:
        """图片数量"""
        count = 0
        if self.image_base64:
            count += 1
        if self.images_base64:
            count += len(self.images_base64)
        return count
    
    def save_text(self, filepath: str) -> bool:
        """保存文本到文件"""
        try:
            if not self.text:
                return False
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(self.text)
            return True
        except Exception:
            return False
    
    def save_image(self, filepath: str, image_index: int = 0) -> bool:
        """保存指定索引的图片到文件"""
        try:
            if image_index == 0 and self.image_base64:
                image_data = base64.b64decode(self.image_base64)
            elif self.images_base64 and 0 < image_index <= len(self.images_base64):
                image_data = base64.b64decode(self.images_base64[image_index - 1])
            else:
                return False
            
            with open(filepath, 'wb') as f:
                f.write(image_data)
            return True
        except Exception:
            return False
    
    def save_all_images(self, directory: str, prefix: str = "resume") -> List[str]:
        """保存所有图片到目录"""
        saved_files = []
        os.makedirs(directory, exist_ok=True)
        
        # 保存主图片
        if self.image_base64:
            filepath = os.path.join(directory, f"{prefix}_main.png")
            if self.save_image(filepath, 0):
                saved_files.append(filepath)
        
        # 保存切片图片
        if self.images_base64:
            for i, _ in enumerate(self.images_base64):
                filepath = os.path.join(directory, f"{prefix}_slice_{i+1}.png")
                if self.save_image(filepath, i + 1):
                    saved_files.append(filepath)
        
        return saved_files


class BossClientOptimized:
    """优化的Boss直聘客户端"""
    
    def __init__(self, base_url: str = 'http://127.0.0.1:5001', timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        # 设置默认headers
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'BossClient/1.0'
        })
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     params: Optional[Dict] = None) -> Dict[str, Any]:
        """统一的请求方法"""
        try:
            url = f"{self.base_url}{endpoint}"
            
            if method.upper() == 'GET':
                response = self.session.get(url, params=params, timeout=self.timeout)
            elif method.upper() == 'POST':
                response = self.session.post(url, json=data, params=params, timeout=self.timeout)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            return {"success": False, "error": "Request timeout"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Connection error - service may be down"}
        except requests.exceptions.HTTPError as e:
            return {"success": False, "error": f"HTTP error: {e.response.status_code}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"Request error: {str(e)}"}
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON response"}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
    
    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return self._make_request('GET', '/status')
    
    def is_service_healthy(self) -> bool:
        """检查服务是否健康"""
        status = self.get_status()
        return status.get('status') == 'running'
    
    def get_notifications(self, limit: int = 10) -> Dict[str, Any]:
        """获取通知列表"""
        return self._make_request('GET', '/notifications', params={'limit': limit})
    
    def login(self) -> Dict[str, Any]:
        """登录"""
        return self._make_request('POST', '/login')
    
    def get_messages(self, limit: int = 10) -> Dict[str, Any]:
        """获取消息列表"""
        return self._make_request('GET', '/chat/dialogs', params={'limit': limit})
    
    def get_recommended_candidates(self, limit: int = 20) -> Dict[str, Any]:
        """获取推荐候选人列表"""
        return self._make_request('GET', '/recommend/candidates', params={'limit': limit})
    
    def get_chat_history(self, chat_id: str) -> Dict[str, Any]:
        """获取聊天历史"""
        return self._make_request('GET', f'/chat/{chat_id}/messages')
    
    def request_resume(self, chat_id: str) -> Dict[str, Any]:
        """请求简历"""
        return self._make_request('POST', '/resume/request', data={'chat_id': chat_id})
    
    def send_message(self, chat_id: str, message: str) -> Dict[str, Any]:
        """发送消息到指定对话"""
        return self._make_request('POST', f'/chat/{chat_id}/send', data={
            'message': message
        })
    
    def view_resume(self, chat_id: str) -> Dict[str, Any]:
        """查看候选人的附件简历"""
        return self._make_request('POST', '/resume/view', data={
            'chat_id': chat_id
        })
    
    def discard_candidate(self, chat_id: str) -> Dict[str, Any]:
        """丢弃候选人 - 点击"不合适"按钮"""
        return self._make_request('POST', '/candidate/discard', data={
            'chat_id': chat_id
        })
    
    def get_resume(self, chat_id: str) -> ResumeResult:
        """获取简历 - 返回结构化的ResumeResult对象
        
        Args:
            chat_id: 聊天ID
        
        Returns:
            ResumeResult: 结构化的简历结果对象
        """
        response = self._make_request('POST', '/resume/online', data={
            'chat_id': chat_id
        })
        
        if response.get('success'):
            return ResumeResult(
                success=True,
                chat_id=response.get('chat_id', chat_id),
                capture_method="auto",  # 固定为auto
                text=response.get('text'),
                html=response.get('html'),
                data_url=response.get('data_url'),
                width=response.get('width', 0),
                height=response.get('height', 0),
                details=response.get('details', ''),
                timestamp=response.get('timestamp')
            )
        else:
            return ResumeResult(
                success=False,
                chat_id=chat_id,
                capture_method="auto",  # 固定为auto
                error=response.get('error') or response.get('details', 'Unknown error')
            )
    
    def view_online_resume(self, chat_id: str) -> ResumeResult:
        """查看在线简历 - 与 get_resume 方法相同，提供向后兼容性"""
        return self.get_resume(chat_id)
    
    def restart(self) -> Dict[str, Any]:
        """重启服务"""
        return self._make_request('POST', '/restart')
    
    def cleanup(self):
        """清理资源"""
        self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    # OCR相关方法
    def ocr_local_from_b64(self, b64_image: str) -> str:
        """本地OCR处理base64图片"""
        try:
            import pytesseract
            from PIL import Image
            image_data = base64.b64decode(b64_image)
            image = Image.open(io.BytesIO(image_data))
            text = pytesseract.image_to_string(image, lang='chi_sim+eng')
            return text.strip()
        except Exception as e:
            return f"OCR失败: {str(e)}"
    
    def ocr_openai_from_b64(self, b64_image: str, api_key: Optional[str] = None) -> str:
        """使用OpenAI Vision API处理base64图片"""
        try:
            import openai
            if api_key:
                openai.api_key = api_key
            elif 'OPENAI_API_KEY' in os.environ:
                openai.api_key = os.environ['OPENAI_API_KEY']
            else:
                return "OCR失败: 未找到OpenAI API密钥"
            
            response = openai.ChatCompletion.create(
                model="gpt-4-vision-preview",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请将这张简历图片中的所有文字内容转换为markdown格式，保持原有的结构和格式。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
                    ]
                }],
                max_tokens=4000
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"OpenAI OCR失败: {str(e)}"


# 向后兼容的别名
BossClient = BossClientOptimized


def main():
    """命令行接口"""
    parser = argparse.ArgumentParser(description='Boss直聘客户端')
    parser.add_argument('--url', default='http://127.0.0.1:5001', help='API服务地址')
    parser.add_argument('command', choices=['status', 'login', 'messages', 'resume', 'discard'], help='命令')
    parser.add_argument('--chat-id', help='聊天ID')
    parser.add_argument('--capture-method', default='auto', choices=['auto', 'wasm', 'image'], help='捕获方法')
    parser.add_argument('--save-dir', help='保存目录')
    
    args = parser.parse_args()
    
    with BossClient(args.url) as client:
        if args.command == 'status':
            result = client.get_status()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        
        elif args.command == 'login':
            result = client.login()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        
        elif args.command == 'messages':
            result = client.get_messages()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        
        elif args.command == 'resume':
            if not args.chat_id:
                print("错误: 需要提供 --chat-id 参数")
                sys.exit(1)
            
            result = client.get_resume(args.chat_id)
            
            if result.success:
                print(f"✅ 简历获取成功!")
                print(f"方法: {result.capture_method}")
                print(f"详情: {result.details}")
                print(f"数据类型: 文本={'✓' if result.has_text else '✗'}, 图片={'✓' if result.has_image else '✗'}")
                
                if args.save_dir:
                    os.makedirs(args.save_dir, exist_ok=True)
                    
                    if result.has_text:
                        text_file = os.path.join(args.save_dir, f"{args.chat_id}_text.txt")
                        result.save_text(text_file)
                        print(f"文本保存到: {text_file}")
                    
                    if result.has_image:
                        saved_images = result.save_all_images(args.save_dir, f"{args.chat_id}")
                        print(f"图片保存到: {saved_images}")
            else:
                print(f"❌ 简历获取失败: {result.error}")
        
        elif args.command == 'discard':
            if not args.chat_id:
                print("错误: 需要提供 --chat-id 参数")
                sys.exit(1)
            
            result = client.discard_candidate(args.chat_id)
            print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
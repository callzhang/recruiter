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
        return self._make_request('GET', '/messages', params={'limit': limit})
    
    def get_chat_history(self, chat_id: str) -> Dict[str, Any]:
        """获取聊天历史"""
        return self._make_request('GET', '/messages/history', params={'chat_id': chat_id})
    
    def request_resume(self, chat_id: str) -> Dict[str, Any]:
        """请求简历"""
        return self._make_request('POST', '/resume/request', data={'chat_id': chat_id})
    
    def get_resume(self, chat_id: str, capture_method: str = "auto") -> ResumeResult:
        """获取简历 - 返回结构化的ResumeResult对象
        
        Args:
            chat_id: 聊天ID
            capture_method: 捕获方法 ("auto", "wasm", "image")
        
        Returns:
            ResumeResult: 结构化的简历结果对象
        """
        response = self._make_request('POST', '/resume/online', data={
            'chat_id': chat_id,
            'capture_method': capture_method
        })
        
        if response.get('success'):
            return ResumeResult(
                success=True,
                chat_id=response.get('chat_id', chat_id),
                capture_method=response.get('capture_method', capture_method),
                text=response.get('text'),
                html=response.get('html'),
                image_base64=response.get('image_base64'),
                images_base64=response.get('images_base64'),
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
                capture_method=capture_method,
                error=response.get('error') or response.get('details', 'Unknown error')
            )
    
    def get_resume_text(self, chat_id: str) -> Optional[str]:
        """快速获取简历文本 - 便利方法"""
        result = self.get_resume(chat_id, capture_method="wasm")
        if not result.success:
            # 回退到auto模式
            result = self.get_resume(chat_id, capture_method="auto")
        return result.text if result.success else None
    
    def get_resume_image(self, chat_id: str, save_path: Optional[str] = None) -> Optional[str]:
        """快速获取简历图片 - 便利方法
        
        Args:
            chat_id: 聊天ID
            save_path: 可选的保存路径
        
        Returns:
            base64编码的图片数据，如果保存到文件则返回文件路径
        """
        result = self.get_resume(chat_id, capture_method="image")
        if not result.success:
            # 回退到auto模式
            result = self.get_resume(chat_id, capture_method="auto")
        
        if result.success and result.has_image:
            if save_path:
                if result.save_image(save_path):
                    return save_path
                else:
                    return None
            else:
                return result.image_base64 or (result.images_base64[0] if result.images_base64 else None)
        return None
    
    def get_resume_with_fallback(self, chat_id: str, preferred_method: str = "auto") -> ResumeResult:
        """获取简历并自动回退 - 最可靠的方法
        
        Args:
            chat_id: 聊天ID
            preferred_method: 首选方法
        
        Returns:
            ResumeResult: 简历结果，会尝试所有方法直到成功
        """
        methods = ["auto", "wasm", "image"]
        
        # 首先尝试首选方法
        if preferred_method in methods:
            result = self.get_resume(chat_id, preferred_method)
            if result.success:
                return result
        
        # 尝试其他方法
        for method in methods:
            if method != preferred_method:
                result = self.get_resume(chat_id, method)
                if result.success:
                    return result
        
        # 所有方法都失败
        return ResumeResult(
            success=False,
            chat_id=chat_id,
            capture_method="fallback",
            error="All capture methods failed"
        )
    
    def batch_get_resumes(self, chat_ids: List[str], capture_method: str = "auto", 
                         max_workers: int = 3) -> Dict[str, ResumeResult]:
        """批量获取简历
        
        Args:
            chat_ids: 聊天ID列表
            capture_method: 捕获方法
            max_workers: 最大并发数
        
        Returns:
            Dict[chat_id, ResumeResult]: 结果字典
        """
        import concurrent.futures
        import time
        
        results = {}
        
        def get_single_resume(chat_id):
            time.sleep(0.1)  # 避免请求过快
            return chat_id, self.get_resume(chat_id, capture_method)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_chat = {executor.submit(get_single_resume, chat_id): chat_id for chat_id in chat_ids}
            
            for future in concurrent.futures.as_completed(future_to_chat):
                chat_id, result = future.result()
                results[chat_id] = result
        
        return results
    
    def get_candidates_with_resumes(self, limit: int = 10, capture_method: str = "auto") -> List[Dict[str, Any]]:
        """获取候选人列表并包含简历信息"""
        messages_response = self.get_messages(limit)
        if not messages_response.get('success'):
            return []
        
        messages = messages_response.get('messages', [])
        candidates = []
        
        for msg in messages:
            chat_id = msg.get('chat_id')
            if chat_id:
                resume_result = self.get_resume(chat_id, capture_method)
                candidate_info = {
                    'chat_id': chat_id,
                    'candidate': msg.get('candidate'),
                    'message': msg.get('message'),
                    'status': msg.get('status'),
                    'job_title': msg.get('job_title'),
                    'time': msg.get('time'),
                    'resume': resume_result
                }
                candidates.append(candidate_info)
        
        return candidates
    
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
    
    def ocr_resume(self, chat_id: str, method: str = "local", api_key: Optional[str] = None) -> str:
        """对简历图片进行OCR处理
        
        Args:
            chat_id: 聊天ID
            method: OCR方法 ("local", "openai")
            api_key: OpenAI API密钥（method="openai"时需要）
        
        Returns:
            OCR提取的文本
        """
        # 首先获取图片
        resume_result = self.get_resume(chat_id, capture_method="image")
        if not resume_result.success or not resume_result.has_image:
            return "OCR失败: 无法获取简历图片"
        
        # 选择主图片或第一张切片
        image_b64 = resume_result.image_base64 or (resume_result.images_base64[0] if resume_result.images_base64 else None)
        if not image_b64:
            return "OCR失败: 无有效图片数据"
        
        # 执行OCR
        if method == "local":
            return self.ocr_local_from_b64(image_b64)
        elif method == "openai":
            return self.ocr_openai_from_b64(image_b64, api_key)
        else:
            return f"OCR失败: 不支持的方法 {method}"


# 向后兼容的别名
BossClient = BossClientOptimized


def main():
    """命令行接口"""
    parser = argparse.ArgumentParser(description='Boss直聘客户端')
    parser.add_argument('--url', default='http://127.0.0.1:5001', help='API服务地址')
    parser.add_argument('command', choices=['status', 'login', 'messages', 'resume'], help='命令')
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
            
            result = client.get_resume(args.chat_id, args.capture_method)
            
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


if __name__ == "__main__":
    main()

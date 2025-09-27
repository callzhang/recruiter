#!/usr/bin/env python3
"""
Boss直聘后台服务（FastAPI版） - 保持登录状态，提供API接口
"""
from ast import pattern
import re
from playwright.sync_api import sync_playwright, expect
import sys
import os
import time
import json
import threading
import hashlib
from datetime import datetime
from fastapi import FastAPI, Query, Request, Body
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import signal
import tempfile # Import tempfile
import logging # Import logging
import shutil # Import shutil

from src.config import settings
from src.utils import export_records
from src.chat_utils import ensure_on_chat_page, find_chat_item
from src.extractors import extract_candidates, extract_messages, extract_chat_history
from src.chat_actions import (
    request_resume_action,
    send_message_action,
    view_full_resume_action,
    discard_candidate_action,
    get_candidates_list_action,
    get_messages_list_action,
    get_chat_history_action,
    view_online_resume_action,
)
from src.recommendation_actions import (
    list_recommended_candidates_action,
)
from src import page_selectors as sel
from src.blacklist import load_blacklist, NEGATIVE_HINTS
from src.events import EventManager
from src import mappings as mapx
from src.resume_capture import capture_resume_from_chat

class BossService:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(BossService, cls).__new__(cls)
        return cls._instance

    def _setup_logging(self):
        """Set up file and console logging."""
        # Correctly set the log file path to the project's root directory
        log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'service.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, mode='a'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def add_notification(self, message: str, level: str = "info"):
        """Add a notification and log it."""
        timestamp = datetime.now().isoformat()
        self.notifications.append({"timestamp": timestamp, "level": level, "message": message})
        
        # Log to file
        if hasattr(self, 'logger'):
            if level == "error":
                self.logger.error(message)
            elif level == "warning":
                self.logger.warning(message)
            else:
                self.logger.info(message)

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self._setup_logging()
            self.app = FastAPI(lifespan=self.lifespan)
            self.playwright = None
            self.context = None # The primary browser object
            self.page = None
            self.is_logged_in = False
            self.notifications = []
            self.shutdown_requested = False
            self.startup_complete = threading.Event() # Event to signal startup completion
            self.initialized = True
            self.setup_routes()
            # 事件驱动的消息缓存和响应监听器
            self.event_manager = EventManager(logger=logging.getLogger(__name__))
            
    def _startup_sync(self):
        """Synchronous startup tasks executed in a thread pool."""
        try:
            self.add_notification("正在初始化Playwright...", "info")
            self.playwright = sync_playwright().start()
            self.add_notification("Playwright初始化成功。", "success")
            self.start_browser()
            # Do NOT call ensure_login here. Let it be called lazily.
        except Exception as e:
            self.add_notification(f"同步启动任务失败: {e}", "error")
            import traceback
            self.add_notification(traceback.format_exc(), "error")
        finally:
            self.startup_complete.set() # Signal that startup is finished

    def _shutdown_sync(self):
        """Synchronous shutdown tasks executed in a thread pool."""
        self.add_notification("开始同步关闭任务...", "info")
        self._graceful_shutdown()
        self.add_notification("同步关闭任务完成。", "success")

    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Startup logic
        self.add_notification("FastAPI lifespan: Startup event triggered.", "info")
        await run_in_threadpool(self._startup_sync)
        
        yield
        # Shutdown logic
        self.add_notification("FastAPI lifespan: Shutdown event triggered.", "info")
        await run_in_threadpool(self._shutdown_sync)

    def setup_routes(self):
        """设置API路由"""
        
        # REMOVED the middleware that was causing race conditions.
        # Login will now be handled explicitly in each endpoint that needs it.

        @self.app.get('/status')
        def get_status():
            return JSONResponse({
                'status': 'running',
                'logged_in': self.is_logged_in,
                'timestamp': datetime.now().isoformat(),
                'notifications_count': len(self.notifications)
            })
        
        @self.app.get('/notifications')
        def get_notifications(limit: int = Query(20, ge=1, le=200)):
            return JSONResponse({
                'notifications': self.notifications[-limit:],
                'total': len(self.notifications)
            })
        
        @self.app.post('/login')
        def login():
            try:
                self._ensure_browser_session()
                return JSONResponse({
                    'success': self.is_logged_in,
                    'message': '登录成功' if self.is_logged_in else '登录失败',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        @self.app.get('/candidates')
        def get_candidates(limit: int = Query(10, ge=1, le=100)):
            try:
                # 确保浏览器会话正常
                self._ensure_browser_session()
                
                if not self.is_logged_in:
                    raise Exception("未登录")
                
                candidates = get_candidates_list_action(
                    self.page, 
                    limit, 
                    logger=self.add_notification,
                    black_companies=getattr(self, 'black_companies', None),
                    save_candidates_func=self.save_candidates_to_file
                )
                return JSONResponse({
                    'success': True,
                    'candidates': candidates,
                    'count': len(candidates),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.get('/candidates/recommended')
        def get_recommended_candidates(limit: int = Query(20, ge=1, le=100)):
            """获取推荐候选人列表"""
            self._ensure_browser_session()
            try:
                result = list_recommended_candidates_action(self.page, limit=limit)
            except Exception as e:
                self.add_notification(f"获取推荐候选人失败: {e}", "error")
                raise

                candidates = result.get('candidates', []) or []
                if result.get('success'):
                    self.add_notification(f"成功获取 {len(candidates)} 个推荐候选人", "success")
                else:
                    self.add_notification(result.get('details', '未找到推荐候选人'), "warning")

                candidates = result.get('candidates', [])
                return JSONResponse({
                    'success': result.get('success', False),
                    'candidates': candidates,
                    'count': len(candidates),
                    'details': result.get('details', ''),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.get('/messages')
        def get_messages(limit: int = Query(10, ge=1, le=100)):
            try:
                # 确保浏览器会话正常
                self._ensure_browser_session()

                messages = get_messages_list_action(
                    self.page, 
                    limit, 
                    logger=self.add_notification,
                    chat_cache=self.event_manager.chat_cache
                )
                return JSONResponse({
                    'success': True,
                    'messages': messages,
                    'count': len(messages),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.get('/search')
        def search_preview(
            city: str = Query('北京'),
            job_type: str = Query('全职'),
            salary: str = Query('不限'),
            experience: str = Query('不限'),
            degree: str = Query('不限'),
            industry: str = Query('不限')
        ):
            try:
                # 将人类可读配置映射为站点参数
                params = {
                    'city': mapx.map_value(city, mapx.CITY_CODE),
                    'jobType': mapx.map_value(job_type, mapx.JOB_TYPE),
                    'salary': mapx.map_value(salary, mapx.SALARY),
                    'experience': mapx.map_value(experience, mapx.EXPERIENCE),
                    'degree': mapx.map_value(degree, mapx.DEGREE),
                    'industry': mapx.map_value(industry, mapx.INDUSTRY),
                }
                # 仅返回参数与构造示例，实际搜索页URL以站点逻辑为准
                preview = {
                    'base': settings.BASE_URL.rstrip('/') + '/web/geek/job?',
                    'params': params,
                }
                return JSONResponse({'success': True, 'preview': preview, 'timestamp': datetime.now().isoformat()})
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        @self.app.post('/greet')
        def greet_candidate(candidate_id: int, message: str | None = None):
            try:
                result = self.send_greeting(candidate_id, message or '您好，我对您的简历很感兴趣，希望能进一步沟通。')
                return JSONResponse({
                    'success': result,
                    'message': '打招呼成功' if result else '打招呼失败',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        @self.app.get('/resume')
        def get_resume(candidate_id: int):
            try:
                resume = self.get_candidate_resume(candidate_id)
                return JSONResponse({
                    'success': True,
                    'resume': resume,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.post('/resume/request')
        def request_resume_api(chat_id: str = Body(..., embed=True)):
            try:
                # 确保浏览器会话和登录
                self._ensure_browser_session()

                result = request_resume_action(self.page, chat_id, logger=self.add_notification)
                return JSONResponse({
                    'success': result.get('success', False),
                    'chat_id': chat_id,
                    'already_sent': result.get('already_sent', False),
                    'details': result.get('details', ''),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.post('/messages/send')
        def send_message_api(chat_id: str = Body(..., embed=True), message: str = Body(..., embed=True)):
            """发送文本消息到指定对话"""
            try:
                # 确保浏览器会话和登录
                self._ensure_browser_session()

                result = send_message_action(self.page, chat_id, message, logger=self.add_notification)
                return JSONResponse({
                    'success': result.get('success', False),
                    'chat_id': chat_id,
                    'message': message,
                    'details': result.get('details', ''),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.get('/messages/history')
        def get_message_history(chat_id: str = Query(...)):
            """获取指定会话的聊天历史（右侧面板）"""
            try:
                # 确保会话
                self._ensure_browser_session()

                history = get_chat_history_action(self.page, chat_id, logger=self.add_notification)
                return JSONResponse({
                    'success': True,
                    'chat_id': chat_id,
                    'messages': history,
                    'count': len(history),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.post('/resume/view')
        def view_resume_api(chat_id: str = Body(..., embed=True)):
            """点击查看候选人的附件简历"""
            try:
                # 确保浏览器会话和登录
                self._ensure_browser_session()

                result = view_full_resume_action(self.page, chat_id, logger=self.add_notification)
                return result
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.post('/candidate/discard')
        def discard_candidate_api(chat_id: str = Body(..., embed=True)):
            """丢弃候选人 - 点击"不合适"按钮"""
            try:
                # 确保浏览器会话和登录
                self._ensure_browser_session()

                result = discard_candidate_action(self.page, chat_id, logger=self.add_notification)
                return JSONResponse({
                    'success': result.get('success', False),
                    'chat_id': chat_id,
                    'details': result.get('details', ''),
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })

        @self.app.post('/resume/online')
        def view_online_resume_api(chat_id: str = Body(..., embed=True)):
            """打开会话并查看在线简历，返回canvas图像base64等信息
            
            Args:
                chat_id: 聊天ID
            """
            # 会话与登录
            # self._ensure_browser_session()
            # if not self.is_logged_in and not self.ensure_login():
            #     raise Exception("未登录")

            result = view_online_resume_action(self.page, chat_id, logger=self.add_notification)
            return JSONResponse({
                'success': result.get('success', False),
                'chat_id': chat_id,
                'text': result.get('text'),
                'html': result.get('html'),
                'image_base64': result.get('image_base64'),
                'images_base64': result.get('images_base64'),
                'data_url': result.get('data_url'),
                'width': result.get('width'),
                'height': result.get('height'),
                'details': result.get('details', ''),
                'error': result.get('error'),
                'timestamp': datetime.now().isoformat(),
                'capture_method': result.get('capture_method'),
            })

        
        @self.app.post('/restart')
        def soft_restart():
            """软重启API服务，保持浏览器会话"""
            try:
                self.soft_restart()
                return JSONResponse({
                    'success': True,
                    'message': 'API服务已重启，浏览器会话保持',
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        @self.app.get('/debug/page')
        def debug_page():
            """调试接口 - 获取当前页面内容"""
            try:
                # 确保浏览器会话正常
                self._ensure_browser_session()
                
                # 等待页面完全渲染（事件驱动）
                try:
                    self.page.locator("body").wait_for(state="visible", timeout=5000)
                    self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                
                if not self.page or self.page.is_closed():
                    return JSONResponse({
                        'success': False,
                        'error': '页面未打开或已关闭',
                        'timestamp': datetime.now().isoformat()
                    })
                
                # 获取页面信息
                full_content = self.page.content()
                # 截取前5000个字符，避免返回过长的HTML
                readable_content = full_content[:5000] + "..." if len(full_content) > 5000 else full_content
                
                page_info = {
                    'url': self.page.url,
                    'title': self.page.title(),
                    'content': readable_content,
                    'content_length': len(full_content),
                    'screenshot': None,
                    'cookies': [],
                    'local_storage': {},
                    'session_storage': {}
                }
                
                # 尝试获取截图
                # try:
                #     screenshot = self.page.screenshot()
                #     import base64
                #     page_info['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                # except Exception as e:
                #     page_info['screenshot_error'] = str(e)
                
                # 获取cookies
                # try:
                #     page_info['cookies'] = self.page.context.cookies()
                # except Exception as e:
                #     page_info['cookies_error'] = str(e)
                
                # # 获取local storage
                # try:
                #     page_info['local_storage'] = self.page.evaluate("() => { return {...localStorage}; }")
                # except Exception as e:
                #     page_info['local_storage_error'] = str(e)
                
                # # 获取session storage
                # try:
                #     page_info['session_storage'] = self.page.evaluate("() => { return {...sessionStorage}; }")
                # except Exception as e:
                #     page_info['session_storage_error'] = str(e)
                
                return JSONResponse({
                    'success': True,
                    'page_info': page_info,
                    'timestamp': datetime.now().isoformat()
                })
                
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
        
        @self.app.get('/debug/cache')
        def get_cache_stats():
            """获取事件缓存统计信息"""
            try:
                stats = self.event_manager.get_cache_stats()
                return JSONResponse({
                    'success': True,
                    'cache_stats': stats,
                    'timestamp': datetime.now().isoformat()
                })
            except Exception as e:
                return JSONResponse({
                    'success': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                })
    
    def _resolve_storage_state_path(self):
        """优先从环境变量注入登录态。
        - BOSS_STORAGE_STATE_JSON: 直接提供storage_state JSON字符串
        - BOSS_STORAGE_STATE_FILE: 指定storage_state文件路径
        - 否则: 使用settings.STORAGE_STATE
        """
        try:
            env_json = os.environ.get("BOSS_STORAGE_STATE_JSON")
            if env_json:
                os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
                # 验证JSON
                _ = json.loads(env_json)
                with open(settings.STORAGE_STATE, "w", encoding="utf-8") as f:
                    f.write(env_json)
                self.add_notification("已从环境变量写入登录状态(JSON)", "success")
                return settings.STORAGE_STATE
        except Exception as e:
            self.add_notification(f"写入环境JSON登录状态失败: {e}", "warning")
        
        env_path = os.environ.get("BOSS_STORAGE_STATE_FILE")
        if env_path and os.path.exists(env_path):
            return env_path
        return settings.STORAGE_STATE
    
    def _get_user_data_dir(self):
        """Get the path to the user data directory."""
        # Use a temporary directory to store browser session data
        # This will persist across service restarts but be cleaned up on system reboot
        return os.path.join(tempfile.gettempdir(), "bosszhipin_playwright_user_data")
        

    def start_browser(self):
        """Launch a persistent browser context with recovery."""
        self.add_notification("正在启动持久化浏览器会话...", "info")
        user_data_dir = self._get_user_data_dir()
        self.add_notification(f"使用用户数据目录: {user_data_dir}", "info")

        try:
            # 确保 playwright 已启动
            if not getattr(self, 'playwright', None):
                self.add_notification("Playwright尚未初始化，正在启动...", "info")
                self.playwright = sync_playwright().start()

            # 仅通过 CDP 连接外部持久化浏览器，失败则直接中止（不再本地回退）
            browser = None
            try:
                self.add_notification(f"尝试通过CDP连接浏览器: {settings.CDP_URL}", "info")
                browser = self.playwright.chromium.connect_over_cdp(settings.CDP_URL)
                self.context = browser.contexts[0] if browser.contexts else browser.new_context()
            except Exception as e:
                self.add_notification(f"CDP连接失败，终止启动: {e}", "error")
                raise

            # （可选）本地存储态仅适用于本地持久化；CDP模式下依靠浏览器自身profile

            
            # 复用持久化上下文的初始页：若存在则使用第一个页面，否则新建
            try:
                pages = list(self.context.pages)
                if pages:
                    self.page = pages[0]
                else:
                    self.page = self.context.new_page()
            except Exception:
                self.page = self.context.new_page()

            # 设置事件管理器（事件驱动的消息列表获取）
            try:
                if self.context:
                    self.event_manager.setup(self.context)
                    self.add_notification("事件管理器设置成功", "success")
            except Exception as e:
                self.add_notification(f"事件管理器设置失败: {e}", "error")

            # 导航到聊天页面
            try:
                if settings.BASE_URL not in getattr(self.page, 'url', ''):
                    self.add_notification("导航到聊天页面...", "info")
                    self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=3000)
                else:
                    self.add_notification("已导航到聊天页面", "info")
            except Exception:
                # 忽略短暂错误，后续请求会再次校验
                pass


            self.add_notification("持久化浏览器会话启动成功！", "success")
            
            # 文件监控已禁用（使用 uvicorn --reload）

        except Exception as e:
            self.add_notification(f"启动持久化浏览器失败: {e}", "error")
            import traceback
            self.add_notification(traceback.format_exc(), "error")
            # Do not raise here, allow startup to complete so logs can be seen
            
    def _load_saved_login_state(self):
        """尝试加载已保存的登录状态"""
        try:
            if os.path.exists(settings.STORAGE_STATE):
                # 检查保存的登录状态文件
                with open(settings.STORAGE_STATE, 'r') as f:
                    storage_state = json.load(f)
                
                # 如果有cookies，说明可能已经登录过
                if storage_state.get('cookies'):
                    self.add_notification("发现已保存的登录状态", "info")
                    # 注意：这里不直接设置 is_logged_in = True，因为需要验证
                    # 实际的登录状态会在 ensure_login 中验证
        except Exception as e:
            self.add_notification(f"加载保存的登录状态失败: {e}", "warning")

    def save_login_state(self):
        """保存登录状态"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(settings.STORAGE_STATE), exist_ok=True)
            
            # 保存当前上下文状态
            context = self.page.context
            context.storage_state(path=settings.STORAGE_STATE)
            
            self.add_notification(f"登录状态已保存到: {settings.STORAGE_STATE}", "success")
            
            # 标记为已登录
            self.is_logged_in = True
            self.add_notification("用户登录状态已确认并保存", "success")
            return True
        except Exception as e:
            self.add_notification(f"保存登录状态失败: {e}", "error")
            return False
    
    def check_login_status(self):
        """检查登录状态"""
        try:
            # 访问聊天页面
            self.page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index",
                             wait_until="domcontentloaded", timeout=10000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
                
            page_text = self.page.locator("body").inner_text()
            current_url = self.page.url
            # 滑块验证检测与提示
            if "/web/user/safe/verify-slider" in current_url:
                self.add_notification("检测到滑块验证页面，请在浏览器中完成验证...", "warning")
                # 等待验证通过或超时（最多5分钟）
                start = time.time()
                while time.time() - start < 300:
                    try:
                        self.page.wait_for_timeout(1000)
                        current_url = self.page.url
                        if "/web/user/safe/verify-slider" not in current_url:
                            break
                    except Exception:
                        break
                
                # 检查是否在登录页面
                if ("登录" in page_text and ("立即登录" in page_text or "登录/注册" in page_text)) or "login" in current_url.lower():
                    self.add_notification("检测到需要登录", "warning")
                    return False
                
                # 检查是否有聊天相关元素
                if any(keyword in page_text for keyword in ["消息", "沟通", "聊天", "候选人", "简历"]):
                    self.add_notification("登录状态正常", "success")
                    return True
                
                self.add_notification("登录状态不明确", "warning")
                return False
                
        except Exception as e:
            self.add_notification(f"检查登录状态失败: {e}", "error")
            return False
    
    
    
    def _graceful_shutdown(self):
        """Gracefully shut down Playwright resources."""
        self.add_notification("执行优雅关闭...", "info")
        # For external CDP-attached browser, do not close the shared context; just detach listeners.
        try:
            if hasattr(self, 'context') and self.context:
                # Best effort: remove response listeners if needed
                pass
        except Exception as e:
            self.add_notification(f"清理CDP监听时出错: {e}", "warning")
        
        if self.playwright:
            try:
                self.playwright.stop()
                self.add_notification("Playwright已停止。", "success")
            except Exception as e:
                self.add_notification(f"停止Playwright时出错: {e}", "warning")
        
        self.context = None
        self.page = None
        self.playwright = None
        self.add_notification("Playwright资源已清理", "success")
    

    def _ensure_browser_session(self, max_wait_time=600):
        """确保浏览器会话和登录状态"""
        # Context present?
        if not self.context:
            self.add_notification("浏览器Context不存在，将重新启动。", "warning")
            self.start_browser()
            return

        # Page present?
        if not self.page or self.page.is_closed():
            try:
                pages = list(self.context.pages)
                # First, try to find a page that already has CHAT_URL
                for page in pages:
                    if settings.CHAT_URL in getattr(page, 'url', ''):
                        self.page = page
                        break
                else:
                    # If no page with CHAT_URL found, use first available page or create new one
                    self.page = pages[0] if pages else self.context.new_page()
                    if settings.CHAT_URL not in getattr(self.page, 'url', ''):
                        try:
                            self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=10000)
                            try:
                                self.page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass
                        except Exception:
                            pass
            except Exception:
                self.start_browser()
                return

        # Lightweight liveness check
        try:
            _ = self.page.title()
        except Exception as title_error:
            self.add_notification(f"页面标题检查失败: {title_error}，将重新启动。", "warning")
            self.start_browser()
            return

        # Login verification - merged from ensure_login
        if not self.is_logged_in:
            self.add_notification("正在检查登录状态...", "info")
            
            try:
                # If the current page is on chat URL, check login status
                if settings.CHAT_URL in self.page.url and "加载中" not in self.page.content():
                    page_text = self.page.locator("body").inner_text()
                    # More comprehensive login detection
                    login_indicators = ["消息", "聊天", "对话", "沟通", "候选人", "简历", "打招呼"]
                    if any(indicator in page_text for indicator in login_indicators):
                        self.is_logged_in = True
                        self.save_login_state()
                        self.add_notification("已在聊天页面，登录状态确认。", "success")
                        return
                    
                    # Also check for the presence of conversation list elements
                    try:
                        conversation_elements = self.page.locator("xpath=//li[contains(@class, 'conversation') or contains(@class, 'chat') or contains(@class, 'item')]")
                        if conversation_elements.count() > 0:
                            self.is_logged_in = True
                            self.save_login_state()
                            self.add_notification("检测到对话列表，登录状态确认。", "success")
                            return
                    except Exception:
                        pass
                
                # Wait for page to load and check if we were redirected to login page
                try:
                    self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                current_url = self.page.url
                
                # Check if we were redirected to login page
                if settings.LOGIN_URL in current_url or "web/user" in current_url or "login" in current_url.lower() or "bticket" in current_url:
                    self.add_notification("检测到登录页面，请手动完成登录...", "warning")
                    self.add_notification("等待用户登录，最多等待10分钟...", "info")
                    
                    # Wait for user to complete login with countdown display
                    start_time = time.time()
                    while time.time() - start_time < max_wait_time:
                        try:
                            current_url = self.page.url
                            page_text = self.page.locator("body").inner_text()
                            
                            # Check if user has logged in
                            if (settings.CHAT_URL in current_url or 
                                any(keyword in page_text for keyword in ["消息", "沟通", "聊天", "候选人", "简历"])):
                                self.add_notification("检测到用户已登录！", "success")
                                break
                            
                            # Check if still on login page
                            if "登录" in page_text and ("立即登录" in page_text or "登录/注册" in page_text):
                                self.add_notification("请在浏览器中完成登录...", "info")
                            
                            # Display countdown
                            elapsed = time.time() - start_time
                            remaining = max_wait_time - elapsed
                            minutes = int(remaining // 60)
                            seconds = int(remaining % 60)
                            print(f"\r⏰ 等待登录中... 剩余时间: {minutes:02d}:{seconds:02d}", end="", flush=True)
                            
                        except Exception as e:
                            self.add_notification(f"检查登录状态时出错: {e}", "warning")
                        
                        time.sleep(3)
                    
                    # Clear the countdown line
                    print("\r" + " " * 50 + "\r", end="", flush=True)
                    
                    if not self.is_logged_in:
                        raise Exception("等待登录超时，请手动登录后重试")
                else:
                    # If we reached the chat page directly, wait for it to load
                    self.add_notification("等待聊天页面加载...", "info")
                    self.page.wait_for_url(
                        lambda url: settings.CHAT_URL in url,
                        timeout=6000, # 10 minutes
                    )
                
                # Final verification after navigation/login
                self.page.wait_for_function(
                    "() => !document.body.innerText.includes('加载中，请稍候')",
                    timeout=30000
                )
                self.is_logged_in = True
                self.save_login_state()
                self.add_notification("登录成功并已在聊天页面。", "success")

            except Exception as e:
                self.is_logged_in = False
                self.add_notification(f"登录检查或等待超时失败: {e}", "error")
                import traceback
                self.add_notification(traceback.format_exc(), "error")
                raise Exception("登录失败")

    
    def send_greeting(self, candidate_id, message):
        """发送打招呼消息"""
        print(f"[*] 向候选人 {candidate_id} 发送打招呼消息")
        # TODO: 实现打招呼逻辑
        return True
    
    def get_candidate_resume(self, candidate_id):
        """获取候选人简历"""
        # 确保浏览器会话正常
        self._ensure_browser_session()
        
        if not self.is_logged_in:
            raise Exception("未登录")
        
        self.add_notification(f"获取候选人 {candidate_id} 的简历", "info")
        
        try:
            # 访问聊天页面
            self.page.goto(
                settings.BASE_URL.rstrip('/') + "/web/chat/index",
                wait_until="domcontentloaded",
                timeout=60000
            )
            
            # 等待页面加载
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            try:
                self.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            
            # 查找指定候选人的对话项
            candidates = get_candidates_list_action(
                self.page, 
                limit=50, 
                logger=self.add_notification,
                black_companies=getattr(self, 'black_companies', None),
                save_candidates_func=self.save_candidates_to_file
            )  # 获取更多候选人
            target_candidate = None
            
            for candidate in candidates:
                if candidate.get('id') == candidate_id:
                    target_candidate = candidate
                    break
            
            if not target_candidate:
                raise Exception(f"未找到候选人 {candidate_id}")
            
            # 点击候选人对话项
            selectors = sel.conversation_list_items()
            clicked = False
            
            for selector in selectors:
                try:
                    elements = self.page.locator(selector).all()
                    if elements and len(elements) >= candidate_id:
                        # 点击对应的候选人
                        elements[candidate_id - 1].click()
                        clicked = True
                        self.add_notification(f"已点击候选人 {candidate_id}", "info")
                        break
                except Exception as e:
                    self.add_notification(f"选择器 {selector} 点击失败: {e}", "warning")
                    continue
            
            if not clicked:
                raise Exception("无法点击候选人对话项")
            
            # 等待聊天窗口加载
            try:
                self.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            
            # 查找简历相关按钮或链接
            resume_data = {}
            
            # 尝试多种简历获取方式
            resume_selectors = [
                "xpath=//button[contains(., '简历') or contains(., '查看简历')]",
                "xpath=//a[contains(., '简历') or contains(., '查看简历')]",
                "xpath=//span[contains(., '简历') or contains(., '查看简历')]",
                "button[title*='简历']",
                "a[href*='resume']",
                "div[class*='resume'] button",
                "div[class*='profile'] button"
            ]
            
            resume_found = False
            for selector in resume_selectors:
                try:
                    resume_btn = self.page.locator(selector).first
                    if resume_btn.count() > 0:
                        resume_btn.click()
                        self.add_notification("已点击简历按钮", "info")
                        time.sleep(2)
                        resume_found = True
                        break
                except Exception:
                    continue
            
            if not resume_found:
                # 尝试右键菜单或其他方式
                try:
                    # 在候选人头像或姓名区域右键
                    candidate_area = self.page.locator("xpath=//div[contains(@class, 'chat') or contains(@class, 'conversation')]").first
                    if candidate_area.count() > 0:
                        candidate_area.click(button="right")
                        try:
                            self.page.wait_for_timeout(1000)
                        except Exception:
                            pass
                        
                        # 查找右键菜单中的简历选项
                        menu_selectors = [
                            "xpath=//div[contains(@class, 'menu')]//span[contains(., '简历')]",
                            "xpath=//div[contains(@class, 'context')]//span[contains(., '简历')]",
                            "xpath=//li[contains(., '简历')]"
                        ]
                        
                        for menu_selector in menu_selectors:
                            try:
                                menu_item = self.page.locator(menu_selector).first
                                if menu_item.count() > 0:
                                    menu_item.click()
                                    self.add_notification("已通过右键菜单访问简历", "info")
                                    try:
                                        self.page.wait_for_timeout(2000)
                                    except Exception:
                                        pass
                                    resume_found = True
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
            
            if resume_found:
                    # 等待简历页面或弹窗加载
                    try:
                        self.page.wait_for_timeout(3000)
                    except Exception:
                        pass
                    
                    # 提取简历信息
                    resume_info = {}
                    
                    # 基本信息
                    basic_info_selectors = [
                        "xpath=//div[contains(@class, 'resume') or contains(@class, 'profile')]//text()",
                        "xpath=//div[contains(@class, 'info')]//text()",
                        "xpath=//div[contains(@class, 'detail')]//text()"
                    ]
                    
                    for selector in basic_info_selectors:
                        try:
                            elements = self.page.locator(selector).all()
                            if elements:
                                for elem in elements:
                                    text = elem.inner_text().strip()
                                    if text and len(text) > 5:
                                        resume_info['basic_info'] = text
                                        break
                                if 'basic_info' in resume_info:
                                    break
                        except Exception:
                            continue
                    
                    # 工作经历
                    work_exp_selectors = [
                        "xpath=//div[contains(., '工作经历') or contains(., '经验')]//following-sibling::*",
                        "xpath=//div[contains(@class, 'experience')]//text()",
                        "xpath=//div[contains(@class, 'work')]//text()"
                    ]
                    
                    for selector in work_exp_selectors:
                        try:
                            elements = self.page.locator(selector).all()
                            if elements:
                                work_text = []
                                for elem in elements:
                                    text = elem.inner_text().strip()
                                    if text and len(text) > 10:
                                        work_text.append(text)
                                if work_text:
                                    resume_info['work_experience'] = work_text
                                    break
                        except Exception:
                            continue
                    
                    # 教育背景
                    education_selectors = [
                        "xpath=//div[contains(., '教育') or contains(., '学历')]//following-sibling::*",
                        "xpath=//div[contains(@class, 'education')]//text()",
                        "xpath=//div[contains(@class, 'school')]//text()"
                    ]
                    
                    for selector in education_selectors:
                        try:
                            elements = self.page.locator(selector).all()
                            if elements:
                                edu_text = []
                                for elem in elements:
                                    text = elem.inner_text().strip()
                                    if text and len(text) > 5:
                                        edu_text.append(text)
                                if edu_text:
                                    resume_info['education'] = edu_text
                                    break
                        except Exception:
                            continue
                    
                    # 技能标签
                    skill_selectors = [
                        "xpath=//div[contains(., '技能') or contains(., '标签')]//span",
                        "xpath=//div[contains(@class, 'skill')]//span",
                        "xpath=//div[contains(@class, 'tag')]//span"
                    ]
                    
                    for selector in skill_selectors:
                        try:
                            elements = self.page.locator(selector).all()
                            if elements:
                                skills = []
                                for elem in elements:
                                    text = elem.inner_text().strip()
                                    if text and len(text) > 1:
                                        skills.append(text)
                                if skills:
                                    resume_info['skills'] = skills
                                    break
                        except Exception:
                            continue
                    
                    resume_data = {
                        'candidate_id': candidate_id,
                        'candidate_info': target_candidate,
                        'resume_info': resume_info,
                        'timestamp': datetime.now().isoformat(),
                        'success': True
                    }
                    
                    self.add_notification(f"成功获取候选人 {candidate_id} 的简历", "success")
                    
                    # 保存简历数据
                    self.save_resume_to_file(resume_data)
                    
                else:
                    # 如果找不到简历按钮，返回基本信息
                    resume_data = {
                        'candidate_id': candidate_id,
                        'candidate_info': target_candidate,
                        'resume_info': {'message': '无法访问详细简历，仅获取到基本信息'},
                        'timestamp': datetime.now().isoformat(),
                        'success': False
                    }
                    
                    self.add_notification(f"未找到简历按钮，返回候选人基本信息", "warning")
                
                return resume_data
                
            except Exception as e:
                self.add_notification(f"获取简历失败: {e}", "error")
                raise Exception(f"获取简历失败: {e}")
    
    def save_resume_to_file(self, resume_data):
        """保存简历数据到文件"""
        try:
            os.makedirs("data/output", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            json_path = f"data/output/resume_{timestamp}.json"
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(resume_data, f, ensure_ascii=False, indent=2)
            
            self.add_notification(f"简历数据已保存到: {json_path}", "success")
            
        except Exception as e:
            self.add_notification(f"保存简历数据失败: {e}", "error")
    
    def _shutdown_thread(self, keep_browser=False):
        """Run graceful shutdown in a separate thread to avoid blocking."""
        self.add_notification(f"在单独的线程中执行关闭(keep_browser={keep_browser})...", "info")
        self._graceful_shutdown()

    def _handle_signal(self, signum, frame):
        """处理信号"""
        self.add_notification(f"收到信号: {signum}", "info")
        # Run shutdown in a separate thread to avoid greenlet/asyncio conflicts
        keep_browser = (signum == signal.SIGTERM)
        shutdown_thread = threading.Thread(target=self._shutdown_thread, args=(keep_browser,))
        shutdown_thread.start()

    def run(self, host='127.0.0.1', port=5001):
        """运行服务 (使用uvicorn由外部启动)"""
        import uvicorn
        self.add_notification("启动Boss直聘后台服务(FastAPI)...", "info")
        # 禁用自动重载，避免 WatchFiles 导致浏览器上下文被反复重启
        uvicorn.run("boss_service:app", host=host, port=port, reload=True, log_level="info")

service = BossService()
app = service.app

if __name__ == "__main__":
    # host = os.environ.get("BOSS_SERVICE_HOST", "127.0.0.1")
    # try:
    #     port = int(os.environ.get("BOSS_SERVICE_PORT", "5001"))
    # except Exception:
    #     port = 5001
    # service.run(host=host, port=port)
    print('不应该从这里启动服务，请运行start_service.py')

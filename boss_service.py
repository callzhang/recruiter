#!/usr/bin/env python3
"""
Boss直聘后台服务（FastAPI版） - 保持登录状态，提供API接口
"""
from playwright.sync_api import sync_playwright
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
from src import page_selectors as sel
from src.blacklist import load_blacklist, NEGATIVE_HINTS
from src import mappings as mapx

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
            self.lock = threading.Lock()
            self.is_logged_in = False
            self.notifications = []
            self.shutdown_requested = False
            self.startup_complete = threading.Event() # Event to signal startup completion
            self.initialized = True
            self.setup_routes()
            # 事件驱动的消息缓存（来自网络响应）
            self.chat_cache = {}
            
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
                result = self.ensure_login()
                return JSONResponse({
                    'success': result,
                    'message': '登录成功' if result else '登录失败',
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
                candidates = self.get_candidates_list(limit)
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
        
        @self.app.get('/messages')
        def get_messages(limit: int = Query(10, ge=1, le=100)):
            try:
                # Explicitly ensure login before getting messages
                if not self.ensure_login():
                    return JSONResponse(status_code=401, content={"error": "Not logged in"})

                messages = self.get_messages_list(limit)
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
                result = self.request_resume(chat_id)
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
                
                # 等待页面完全渲染
                import time
                time.sleep(3)
                
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
                try:
                    screenshot = self.page.screenshot()
                    import base64
                    page_info['screenshot'] = base64.b64encode(screenshot).decode('utf-8')
                except Exception as e:
                    page_info['screenshot_error'] = str(e)
                
                # 获取cookies
                try:
                    page_info['cookies'] = self.page.context.cookies()
                except Exception as e:
                    page_info['cookies_error'] = str(e)
                
                # 获取local storage
                try:
                    page_info['local_storage'] = self.page.evaluate("() => { return {...localStorage}; }")
                except Exception as e:
                    page_info['local_storage_error'] = str(e)
                
                # 获取session storage
                try:
                    page_info['session_storage'] = self.page.evaluate("() => { return {...sessionStorage}; }")
                except Exception as e:
                    page_info['session_storage_error'] = str(e)
                
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

            # 设置事件驱动监听器：抓取包含会话/消息的网络响应，用于提取 BOSS 内部 chat_id
            try:
                def _on_response(resp):
                    try:
                        url = resp.url
                        if "/web/chat" in url or "/wapi/zpgeek/chat" in url or "/wapi/zpgeek/message" in url:
                            if resp.request.resource_type == "xhr" or resp.request.resource_type == "fetch":
                                body = None
                                try:
                                    body = resp.text()
                                except Exception:
                                    return
                                if not body:
                                    return
                                # 简单提取可能的会话 id 字段（如 conversationId / uid / chatId 等）
                                # 为了稳健性，做多种键名匹配
                                import json as _json
                                try:
                                    data = _json.loads(body)
                                except Exception:
                                    return
                                def _extract_items(obj):
                                    if isinstance(obj, dict):
                                        for k, v in obj.items():
                                            if isinstance(v, (dict, list)):
                                                yield from _extract_items(v)
                                            else:
            
                                                yield (k, v)
                                    elif isinstance(obj, list):
                                        for it in obj:
                                            yield from _extract_items(it)
                                found = {}
                                for k, v in _extract_items(data):
                                    lk = str(k).lower()
                                    if lk in ("chatid", "conversationid", "conv_id", "uid", "sid"):
                                        found["chat_id"] = v
                                    elif lk in ("name", "nickname", "geekname", "candidatename"):
                                        found.setdefault("candidate", v)
                                    elif lk in ("jobtitle", "job", "job_name"):
                                        found.setdefault("job_title", v)
                                    elif lk in ("msg", "message", "lastmsg", "last_message"):
                                        found.setdefault("message", v)
                                    elif lk in ("status", "unread", "unread_count"):
                                        found.setdefault("status", v)
                                if found.get("chat_id"):
                                    # 用 chat_id 作为 key 缓存
                                    self.chat_cache[str(found["chat_id"]) ] = found
                    except Exception:
                        return
                if self.context:
                    self.context.on("response", _on_response)
            except Exception:
                pass

            # 导航到聊天页面
            self.add_notification("导航到聊天页面...", "info")
            try:
                if settings.CHAT_URL not in getattr(self.page, 'url', ''):
                    self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=3000)
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
            with self.lock:
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
            with self.lock:
                # 访问聊天页面
                self.page.goto(settings.BASE_URL.rstrip('/') + "/web/chat/index", 
                             wait_until="domcontentloaded", timeout=10000)
                time.sleep(3)
                
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
    
    def ensure_login(self, max_wait_time=600):
        """确保登录状态"""
        self.add_notification("正在检查登录状态...", "info")
        self._ensure_browser_session()

        try:
            # If the current page is blank, we must navigate.
            # Otherwise, check if we are already on the correct chat page.
            if settings.CHAT_URL in self.page.url and "加载中" not in self.page.content():
                page_text = self.page.locator("body").inner_text()
                # More comprehensive login detection
                login_indicators = ["消息", "聊天", "对话", "沟通", "候选人", "简历", "打招呼"]
                if any(indicator in page_text for indicator in login_indicators):
                    self.is_logged_in = True
                    self.save_login_state()
                    self.add_notification("已在聊天页面，登录状态确认。", "success")
                    return True
                
                # Also check for the presence of conversation list elements
                try:
                    conversation_elements = self.page.locator("xpath=//li[contains(@class, 'conversation') or contains(@class, 'chat') or contains(@class, 'item')]")
                    if conversation_elements.count() > 0:
                        self.is_logged_in = True
                        self.save_login_state()
                        self.add_notification("检测到对话列表，登录状态确认。", "success")
                        return True
                except Exception:
                    pass
            
            # If blank, or not on the chat page, navigate and wait for login.
            self.add_notification("导航到聊天页面...", "info")
            self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for page to load and check if we were redirected to login page
            time.sleep(3)
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
                        
                        # Check if user has logged in (URL contains chat page or page content contains chat keywords)
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
            return True

        except Exception as e:
            self.is_logged_in = False
            self.add_notification(f"登录检查或等待超时失败: {e}", "error")
            import traceback
            self.add_notification(traceback.format_exc(), "error")
            return False
    
    def get_candidates_list(self, limit=10):
        """获取候选人列表"""
        with self.lock:
            # 确保浏览器会话正常
            self._ensure_browser_session()
            
            if not self.is_logged_in:
                raise Exception("未登录")
            
            self.add_notification(f"获取候选人列表 (限制: {limit})", "info")
            
            try:
                # 访问聊天页面并充分等待
                self.page.goto(
                    settings.CHAT_URL,
                    wait_until="domcontentloaded",
                    timeout=6000 
                )
                
                # 等待页面完全加载，特别是等待"加载中"消失
                self.add_notification("等待聊天页面加载完成...", "info")
                
                # 等待"加载中"文本消失
                try:
                    self.page.wait_for_function(
                        "() => !document.body.innerText.includes('加载中，请稍候')",
                        timeout=30000
                    )
                    self.add_notification("页面加载完成", "success")
                except Exception as e:
                    self.add_notification(f"等待页面加载超时: {e}", "warning")
                
                # 额外等待确保内容渲染
                time.sleep(3)
                
                # 调试：检查当前页面URL和内容
                current_url = self.page.url
                page_title = self.page.title()
                self.add_notification(f"当前页面URL: {current_url}", "info")
                self.add_notification(f"页面标题: {page_title}", "info")
                
                # 检查页面内容
                page_text = self.page.locator("body").inner_text()
                if "消息" in page_text or "聊天" in page_text or "全部" in page_text:
                    self.add_notification("检测到聊天页面内容", "success")
                else:
                    self.add_notification("未检测到聊天页面内容", "warning")
                    self.add_notification(f"页面内容预览: {page_text[:200]}...", "info")

                # 尝试点击“全部”标签以触发列表渲染
                try:
                    tab_all = self.page.locator(
                        "xpath=//span[contains(., '全部')]/ancestor::a | xpath=//a[contains(., '全部')]"
                    )
                    if tab_all.count() > 0:
                        tab_all.first.click()
                        time.sleep(0.5)
                except Exception:
                    pass

                # 等待会话列表元素出现（最多20秒），并尝试轻微滚动促使懒加载
                selectors_wait = sel.conversation_list_items()
                start_wait = time.time()
                while time.time() - start_wait < 20:
                    has_any = False
                    for s in selectors_wait:
                        try:
                            if self.page.locator(s).count() > 0:
                                has_any = True
                                break
                        except Exception:
                            continue
                    if has_any:
                        break
                    try:
                        self.page.mouse.wheel(0, 800)
                    except Exception:
                        pass
                    time.sleep(0.3)
            except Exception as e:
                self.add_notification(f"访问聊天页面失败: {e}", "error")
                raise Exception(f"访问聊天页面失败: {e}")
            
            candidates = []
        
        # 对齐 get_jobs 的聊天列表选择器
        selectors = sel.conversation_list_items()
        
        for selector in selectors:
            try:
                elements = self.page.locator(selector).all()
                if elements:
                    self.add_notification(f"使用选择器 {selector} 找到 {len(elements)} 个元素", "info")
                    
                    for i, elem in enumerate(elements[:limit]):
                        try:
                            text = elem.inner_text().strip()
                            if (text and len(text) > 10 and 
                                "未选中联系人" not in text and
                                "全部" not in text and
                                "新招呼" not in text and
                                "沟通中" not in text and
                                "已约面" not in text and
                                "已获取简历" not in text and
                                "已交换电话" not in text and
                                "已交换微信" not in text and
                                "收藏" not in text and
                                "更多" not in text):
                                
                                candidate = {
                                    'id': i + 1,
                                    'raw_text': text,
                                    'timestamp': datetime.now().isoformat()
                                }
                                
                                # 尝试提取结构化信息
                                lines = text.split('\n')
                                for line in lines:
                                    line = line.strip()
                                    if '岁' in line:
                                        candidate['age'] = line
                                    elif any(edu in line for edu in ['本科', '硕士', '大专', '博士']):
                                        candidate['education'] = line
                                    elif '年' in line and '经验' in line:
                                        candidate['experience'] = line
                                    elif any(city in line for city in ['市', '区', '省']):
                                        candidate['location'] = line
                                    elif any(job in line for job in ['工程师', '开发', '算法', '产品', '运营', '销售']):
                                        candidate['position'] = line
                                
                                # 读取公司名与最后一条消息（提升结构化程度）
                                try:
                                    comp_sels = sel.chat_company_name_items()
                                    for cs in comp_sels:
                                        loc = elem.locator(cs)
                                        if loc.count() > 0:
                                            candidate['company'] = (loc.first.inner_text() or '').strip()
                                            break
                                except Exception:
                                    pass
                                try:
                                    last_sels = sel.chat_last_message_items()
                                    for ls in last_sels:
                                        loc2 = elem.locator(ls)
                                        if loc2.count() > 0:
                                            candidate['last_message'] = (loc2.first.inner_text() or '').strip()
                                            break
                                except Exception:
                                    pass
                                
                                # 黑名单过滤：公司名命中则跳过
                                comp = candidate.get('company', '')
                                if comp and any(b in comp for b in self.black_companies):
                                    continue
                                candidates.append(candidate)
                                
                        except Exception as e:
                            print(f"[!] 提取第 {i+1} 个候选人信息失败: {e}")
                            continue
                    
                    if candidates:
                        break
                        
            except Exception as e:
                print(f"[!] 选择器 {selector} 失败: {e}")
                continue
        
        if not candidates:
            # 输出各选择器的命中统计，便于调试
            try:
                counts = {}
                for s in selectors:
                    try:
                        counts[s] = self.page.locator(s).count()
                    except Exception:
                        counts[s] = -1
                self.add_notification(f"候选人列表为空，命中统计: {counts}", "warning")
            except Exception:
                pass
        self.add_notification(f"成功获取 {len(candidates)} 个候选人", "success")
        
        # 保存候选人数据到文件
        if candidates:
            self.save_candidates_to_file(candidates)
        
        return candidates
    
    def save_candidates_to_file(self, candidates):
        """保存候选人数据到文件"""
        try:
            # 使用现有的导出功能
            json_path, csv_path = export_records(candidates, prefix="candidates")
            self.add_notification(f"候选人数据已保存到: {json_path}", "success")
            
        except Exception as e:
            self.add_notification(f"保存候选人数据失败: {e}", "error")
    
    def get_messages_list(self, limit: int = 10):
        """获取消息列表"""
        with self.lock:
            # 确保浏览器会话正常
            self._ensure_browser_session()
            
            # 复用统一的登录逻辑
            if not self.is_logged_in:
                if not self.ensure_login():
                    raise Exception("未登录")
            
            self.add_notification(f"获取消息列表 (限制: {limit})", "info")
            
            try:
                # Single-pass DOM snapshot first (no sleeps/clicks); fallback to cache
                messages = []
                # 轻量确保在聊天页
                try:
                    if settings.CHAT_URL not in self.page.url:
                        self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=3000)
                except Exception:
                    pass

                item_selectors = [
                    "div.geek-item",
                    "[role='listitem']"
                ]

                def _text_safe(loc):
                    try:
                        return loc.inner_text()
                    except Exception:
                        return ""

                def _attr_safe(loc, name):
                    try:
                        return loc.get_attribute(name)
                    except Exception:
                        return None

                for sel in item_selectors:
                    try:
                        elems = self.page.locator(sel).all()
                    except Exception:
                        elems = []
                    for elem in elems:
                        try:
                            chat_id = _attr_safe(elem, 'data-id') or _attr_safe(elem, 'id')
                            name_loc = elem.locator('.geek-name').first
                            job_loc = elem.locator('.source-job').first
                            time_loc = elem.locator('.time-shadow').first
                            msg_loc = elem.locator('.push-text').first

                            candidate = _text_safe(name_loc).strip()
                            job_title = _text_safe(job_loc).strip() or '未知'
                            time_info = _text_safe(time_loc).strip() or '未知'
                            last_message = _text_safe(msg_loc).strip()

                            if not candidate:
                                block = _text_safe(elem)
                                if not block:
                                    continue
                                if job_title == '未知':
                                    job_title = '算法工程师' if '算法工程师' in block else '未知'
                                if not last_message:
                                    last_message = block[:120]

                            status = '—'
                            if self.chat_cache:
                                for _, cached in self.chat_cache.items():
                                    cname = cached.get('candidate')
                                    if cname and candidate and cname in candidate:
                                        chat_id = chat_id or cached.get('chat_id')
                                        last_message = cached.get('message') or last_message
                                        job_title = cached.get('job_title') or job_title
                                        status = cached.get('status') or status
                                        break

                            item = {
                                'chat_id': chat_id,
                                'candidate': candidate,
                                'message': last_message,
                                'status': status,
                                'job_title': job_title,
                                'time': time_info
                            }
                            if item['candidate']:
                                messages.append(item)
                                if len(messages) >= limit:
                                    break
                        except Exception:
                            continue
                    if len(messages) >= limit:
                        break

                if not messages and self.chat_cache:
                    for _, cached in list(self.chat_cache.items())[:limit]:
                        messages.append({
                            'chat_id': cached.get('chat_id'),
                            'candidate': cached.get('candidate'),
                            'message': cached.get('message'),
                            'status': cached.get('status') or '—',
                            'job_title': cached.get('job_title') or '未知',
                            'time': cached.get('time') or '未知'
                        })

                if not messages:
                    self.add_notification("消息列表为空（DOM+缓存均无）", "warning")

                self.add_notification(f"成功获取 {len(messages)} 条消息", "success")
                return messages

                # 检查当前页面状态
                current_url = self.page.url
                self.add_notification(f"当前页面: {current_url}", "info")
                
                # 如果不在聊天页面，导航到聊天页面
                if settings.CHAT_URL not in current_url:
                    self.add_notification("导航到聊天页面...", "info")
                    self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)  # 等待页面稳定

                self.add_notification("等待聊天页面加载完成...", "info")
                try:
                    self.page.wait_for_function(
                        "() => !document.body.innerText.includes('加载中，请稍候')",
                        timeout=30000
                    )
                    self.add_notification("页面加载完成", "success")
                except Exception as e:
                    self.add_notification(f"等待页面加载超时: {e}", "warning")
                
                # 事件驱动为主，尽量不阻塞。仅做极短让步
                time.sleep(0.3)
                
                # 尝试点击"全部"标签以触发列表渲染
                try:
                    # 依次尝试两个 XPath，避免并集表达式兼容性问题
                    tab1 = self.page.locator("xpath=//span[contains(., '全部')]/ancestor::a")
                    tab2 = self.page.locator("xpath=//a[contains(., '全部')]")
                    clicked = False
                    if tab1.count() > 0:
                        tab1.first.click()
                        clicked = True
                    elif tab2.count() > 0:
                        tab2.first.click()
                        clicked = True
                    if clicked:
                        time.sleep(1)
                        self.add_notification("已点击'全部'标签", "info")
                except Exception as e:
                    self.add_notification(f"点击'全部'标签失败: {e}", "warning")
                
                # 等待"加载中，请稍候"文本消失
                try:
                    self.page.wait_for_function(
                        "() => !document.body.innerText.includes('加载中，请稍候')",
                        timeout=30000
                    )
                    self.add_notification("页面加载完成", "success")
                except Exception as e:
                    self.add_notification(f"等待页面加载超时: {e}", "warning")
                
                # 尝试等待对话列表加载
                try:
                    # 等待可能的对话列表元素出现
                    self.page.wait_for_selector("li, .conversation, .chat-item, [class*='conversation'], [class*='chat']", timeout=10000)
                    self.add_notification("检测到对话列表元素", "info")
                except Exception as e:
                    self.add_notification(f"等待对话列表元素超时: {e}", "warning")
                
                # 尝试滚动页面以触发懒加载
                try:
                    self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    self.page.evaluate("window.scrollTo(0, 0)")
                    time.sleep(2)
                    self.add_notification("已滚动页面以触发懒加载", "info")
                except Exception as e:
                    self.add_notification(f"滚动页面失败: {e}", "warning")
                
                # 等待网络请求完成
                try:
                    self.page.wait_for_load_state("networkidle", timeout=15000)
                    self.add_notification("网络请求已完成", "info")
                except Exception as e:
                    self.add_notification(f"等待网络请求超时: {e}", "warning")
                
                messages = []
                
                # 调试：输出页面内容以了解结构
                try:
                    page_text = self.page.locator("body").inner_text()
                    self.add_notification(f"页面内容长度: {len(page_text)}", "info")
                    # 查找是否包含候选人姓名
                    if any(name in page_text for name in ['易飞', '孙朋', 'Khalil', '牛小林', '林雪', '李卓书']):
                        self.add_notification("页面包含候选人姓名", "success")
                    else:
                        self.add_notification("页面不包含候选人姓名", "warning")
                    
                except Exception as e:
                    self.add_notification(f"调试页面内容失败: {e}", "warning")
                
                # 先获取当前页面HTML内容进行调试
                self.add_notification("开始分析页面HTML结构...", "info")
                
                try:
                    # 等待页面完全加载
                    time.sleep(3)
                    
                    # 获取页面所有文本内容
                    page_text = self.page.locator("body").inner_text()
                    self.add_notification(f"页面文本长度: {len(page_text)}", "info")
                    
                    # 检查是否包含候选人姓名
                    candidate_names = ["易飞", "孙朋", "Khalil", "牛小林", "林雪", "李卓书"]
                    found_candidates = []
                    
                    for name in candidate_names:
                        if name in page_text:
                            found_candidates.append(name)
                    
                    self.add_notification(f"在页面中找到候选人: {found_candidates}", "info")
                    
                    if not found_candidates:
                        self.add_notification("页面中未找到任何候选人姓名，可能需要滚动或等待页面加载", "warning")
                        
                        # 尝试点击"全部"选项卡确保显示所有对话
                        try:
                            all_tab = self.page.locator("text=全部").first
                            if all_tab.count() > 0:
                                all_tab.click()
                                self.add_notification("点击了'全部'选项卡", "info")
                                time.sleep(2)
                        except Exception as e:
                            self.add_notification(f"点击'全部'选项卡失败: {e}", "warning")
                        
                        # 尝试滚动页面
                        try:
                            self.page.keyboard.press("PageDown")
                            time.sleep(1)
                            self.page.keyboard.press("PageUp")
                            time.sleep(1)
                            self.add_notification("已滚动页面", "info")
                        except Exception as e:
                            self.add_notification(f"滚动页面失败: {e}", "warning")
                    
                # 尝试查找对话列表的容器
                    conversation_selectors = [
                        "[role='listitem']",
                        ".geek-item",
                        "[class*='conversation']",
                        "[class*='chat']",
                        "[class*='message']",
                        "li[class*='item']",
                        "[class*='dialog']"
                    ]
                    
                    for selector in conversation_selectors:
                        try:
                            elements = self.page.locator(selector).all()
                            element_count = len(elements)
                            self.add_notification(f"选择器 '{selector}' 找到 {element_count} 个元素", "info")
                            
                            if element_count > 0 and element_count < 50:  # 合理的数量范围
                                for i, elem in enumerate(elements[:20]):  # 限制处理前20个
                                    try:
                                        elem_text = elem.inner_text()
                                        
                                        # 检查是否包含候选人姓名且不是菜单项
                                        menu_keywords = [
                                            "个人中心", "账号设置", "钱包/发票", "桌面客户端", 
                                            "最佳招聘官", "退出登录", "星尘纪元", "首充优惠", 
                                            "直豆", "道具来源", "不合适", "牛人发起", "我发起"
                                        ]
                                        
                                        # 排除菜单项
                                        if any(keyword in elem_text for keyword in menu_keywords):
                                            continue
                                        
                                        # 检查是否包含候选人姓名
                                        found_candidate = None
                                        for name in candidate_names:
                                            if name in elem_text:
                                                found_candidate = name
                                                break
                                        
                                        if found_candidate and len(elem_text.strip()) > 15:
                                            # 提取职位信息
                                            job_title = "未知"
                                            job_keywords = ["算法工程师", "工程师", "开发", "程序员", "技术"]
                                            for job_keyword in job_keywords:
                                                if job_keyword in elem_text:
                                                    job_title = job_keyword
                                                    break
                                            
                                            # 提取时间信息
                                            time_info = "未知"
                                            time_keywords = ["分钟前", "小时前", "昨天", "月", "日", ":"]
                                            lines = elem_text.split('\n')
                                            for line in lines:
                                                line = line.strip()
                                                for time_keyword in time_keywords:
                                                    if time_keyword in line and len(line) < 50:
                                                        time_info = line
                                                        break
                                                if time_info != "未知":
                                                    break
                                            
                                            # 提取最后消息内容（通常是最长的一行文本）
                                            last_message = ""
                                            max_len = 0
                                            for line in lines:
                                                line = line.strip()
                                                if (len(line) > max_len and 
                                                    len(line) < 200 and 
                                                    found_candidate not in line and
                                                    not any(keyword in line for keyword in menu_keywords)):
                                                    max_len = len(line)
                                                    last_message = line
                                            
                                            if not last_message:
                                                last_message = elem_text.strip()[:100] + "..."
                                            
                                            # 优先从DOM属性提取 chat_id（data-id 或 id）
                                            chat_id = None
                                            try:
                                                dom_data_id = None
                                                try:
                                                    dom_data_id = elem.get_attribute('data-id')
                                                except Exception:
                                                    dom_data_id = None
                                                if not dom_data_id:
                                                    try:
                                                        dom_data_id = elem.get_attribute('id')
                                                    except Exception:
                                                        dom_data_id = None
                                                if dom_data_id:
                                                    chat_id = dom_data_id
                                            except Exception:
                                                pass

                                            # 其次使用事件缓存的 chat_id
                                            for cid, cached in self.chat_cache.items():
                                                cname = cached.get('candidate')
                                                if cname and cname in elem_text:
                                                    if chat_id is None:
                                                        chat_id = cached.get('chat_id')
                                                    # 回填 message/job_title/status
                                                    if cached.get('message'): last_message = cached['message']
                                                    if cached.get('job_title'): job_title = cached['job_title']
                                                    status = cached.get('status')
                                                    break
                                            item = {
                                                'chat_id': chat_id if chat_id is not None else len(messages) + 1,
                                                'candidate': found_candidate,
                                                'message': last_message,
                                                'status': status if 'status' in locals() else '—',
                                                'job_title': job_title,
                                                'time': time_info
                                            }
                                            messages.append(item)
                                            
                                            self.add_notification(f"从选择器 '{selector}' 找到对话: {found_candidate} - {job_title}", "success")
                                            
                                            if len(messages) >= limit:
                                                break
                                    
                                    except Exception as e:
                                        self.add_notification(f"处理元素 {i} 失败: {e}", "warning")
                                        continue
                            
                            if len(messages) >= limit:
                                break
                                
                        except Exception as e:
                            self.add_notification(f"使用选择器 '{selector}' 失败: {e}", "warning")
                            continue
                
                except Exception as e:
                    self.add_notification(f"搜索对话列表时发生错误: {e}", "error")
                
                if not messages:
                    self.add_notification(f"消息列表为空，请检查页面或选择器。", "warning")
                
                self.add_notification(f"成功获取 {len(messages)} 条消息", "success")
                return messages
                
            except Exception as e:
                self.add_notification(f"获取消息列表失败: {e}", "error")
                raise

    def _recreate_page(self):
        """重新创建页面"""
        try:
            if self.page and not self.page.is_closed():
                self.page.close()
        except Exception:
            pass
        
        try:
            # 重新创建页面
            self.page = self.context.new_page() # Changed from self.browser.context to self.context
            # 立即导航到聊天页面
            try:
                if settings.CHAT_URL not in self.page.url:
                    self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
            # 不再处理空白页，统一复用初始页
            self.add_notification("页面已重新创建", "info")
        except Exception as e:
            self.add_notification(f"重新创建页面失败: {e}", "error")
            raise Exception(f"重新创建页面失败: {e}")

    def request_resume(self, chat_id: str) -> dict:
        """对某个对话发送求简历请求。如果已存在“简历请求已发送”，则不重复发送。
        返回: { success: bool, already_sent: bool, details: str }
        """
        with self.lock:
            # 确保浏览器会话和登录
            self._ensure_browser_session()
            if not self.is_logged_in and not self.ensure_login():
                raise Exception("未登录")

            try:
                # 确保在聊天页面
                try:
                    if settings.CHAT_URL not in self.page.url:
                        self.page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=3000)
                except Exception:
                    pass

                # 选中指定 chat_id 的列表项
                target = None
                for sel in ["div.geek-item", "[role='listitem']"]:
                    try:
                        items = self.page.locator(sel).all()
                    except Exception:
                        items = []
                    for it in items:
                        try:
                            did = it.get_attribute('data-id') or it.get_attribute('id')
                            if did and chat_id and did == chat_id:
                                target = it
                                break
                        except Exception:
                            continue
                    if target:
                        break

                if not target:
                    return { 'success': False, 'already_sent': False, 'details': '未找到指定对话项' }

                # 点击打开右侧对话面板
                try:
                    target.click()
                except Exception as e:
                    return { 'success': False, 'already_sent': False, 'details': f'点击对话失败: {e}' }

                # 检查是否已发送过“简历请求已发送”
                try:
                    panel_text = self.page.locator("body").inner_text()
                    if "简历请求已发送" in panel_text:
                        return { 'success': True, 'already_sent': True, 'details': '已存在简历请求' }
                except Exception:
                    pass

                # 查找“求简历”按钮并点击
                clicked = False
                resume_btn_selectors = [
                    "xpath=//button[contains(., '求简历')]",
                    "xpath=//a[contains(., '求简历')]",
                    "text=求简历"
                ]
                for bsel in resume_btn_selectors:
                    try:
                        btn = self.page.locator(bsel).first
                        if btn and btn.count() > 0:
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        continue

                if not clicked:
                    return { 'success': False, 'already_sent': False, 'details': '未找到“求简历”按钮' }

                # 验证是否出现“简历请求已发送”
                try:
                    # 用短等待避免长阻塞
                    self.page.wait_for_function(
                        "() => document.body.innerText.includes('简历请求已发送')",
                        timeout=2000
                    )
                    return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }
                except Exception:
                    # 再做一次快照检查
                    try:
                        panel_text = self.page.locator("body").inner_text()
                        if "简历请求已发送" in panel_text:
                            return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }
                    except Exception:
                        pass
                    return { 'success': False, 'already_sent': False, 'details': '未检测到发送成功提示' }

            except Exception as e:
                self.add_notification(f"求简历操作失败: {e}", "error")
                raise
    
    def _graceful_shutdown(self):
        """Gracefully shut down Playwright resources."""
        self.add_notification("执行优雅关闭...", "info")
        # For a persistent context, we just need to close the context.
        # The data is saved on disk.
        if hasattr(self, 'context') and self.context:
            try:
                self.context.close()
                self.add_notification("浏览器Context已关闭。", "success")
            except Exception as e:
                self.add_notification(f"关闭浏览器Context时出错: {e}", "warning")
        
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
    
    def start_file_watcher(self):
        """已禁用：使用 uvicorn --reload 实现热重载"""
        return
    
    def _file_watcher_loop(self):
        """已禁用"""
        return
    
    def _get_file_hash(self, file_path):
        """已禁用"""
        return None
    
    def _soft_restart(self):
        """已禁用（uvicorn --reload 负责重载）"""
        return

    def _ensure_browser_session(self):
        # Context present?
        if not self.context:
            self.add_notification("浏览器Context不存在，将重新启动。", "warning")
            self.start_browser()
            return

        # Page present?
        if not self.page or self.page.is_closed():
            try:
                pages = list(self.context.pages)
                assert any(settings.BASE_URL in p.url for p in pages)
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

    
    def send_greeting(self, candidate_id, message):
        """发送打招呼消息"""
        print(f"[*] 向候选人 {candidate_id} 发送打招呼消息")
        # TODO: 实现打招呼逻辑
        return True
    
    def get_candidate_resume(self, candidate_id):
        """获取候选人简历"""
        with self.lock:
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
                time.sleep(2)
                
                # 查找指定候选人的对话项
                candidates = self.get_candidates_list(limit=50)  # 获取更多候选人
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
                time.sleep(3)
                
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
                            time.sleep(1)
                            
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
                                        time.sleep(2)
                                        resume_found = True
                                        break
                                except Exception:
                                    continue
                    except Exception:
                        pass
                
                if resume_found:
                    # 等待简历页面或弹窗加载
                    time.sleep(3)
                    
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
    
    # def check_code_updates(self):
    #     """检查代码更新"""
    #     current_hash = self.get_code_hash()
    #     if self.last_code_hash and current_hash != self.last_code_hash:
    #         # 触发热更新（不重启，不关闭浏览器）
    #         try:
    #             self.reload_code()
    #             self.add_notification("代码已热更新(无需重启)", "success")
    #         except Exception as e:
    #             self.add_notification(f"热更新失败: {e}", "error")
    #         return True
    #     self.last_code_hash = current_hash
    #     return False
    
    # def get_code_hash(self):
    #     """获取代码文件哈希值"""
    #     hash_md5 = hashlib.md5()
    #     # 仅监控 src 目录的变更，避免自身文件热更新复杂度
    #     for root, dirs, files in os.walk("src"):
    #         for file in files:
    #             if file.endswith('.py'):
    #                 filepath = os.path.join(root, file)
    #                 try:
    #                     with open(filepath, "rb") as f:
    #                         hash_md5.update(f.read())
    #                 except:
    #                     pass
    #     return hash_md5.hexdigest()
    

    # def reload_code(self):
    #     """热更新配置/工具模块，不关闭浏览器和Flask。"""
    #     import importlib
    #     with self.lock:
    #         # 重新加载配置与工具模块
    #         try:
    #             import src.config as cfg_mod
    #             cfg_mod = importlib.reload(cfg_mod)
    #             # 更新全局 settings 引用
    #             globals()['settings'] = cfg_mod.settings
    #             self.add_notification("配置已热更新", "success")
    #         except Exception as e:
    #             self.add_notification(f"配置热更新失败: {e}", "error")
            
    #         try:
    #             import src.utils as utils_mod
    #             importlib.reload(utils_mod)
    #             self.add_notification("工具模块已热更新", "success")
    #         except Exception as e:
    #             self.add_notification(f"工具模块热更新失败: {e}", "warning")
            
    #         try:
    #             import src.page_selectors as sel_mod
    #             importlib.reload(sel_mod)
    #             self.add_notification("选择器模块已热更新", "success")
    #         except Exception as e:
    #             self.add_notification(f"选择器模块热更新失败: {e}", "warning")
    
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
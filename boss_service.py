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
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import signal
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import settings
from src.utils import export_records
from src import page_selectors as sel
from src.blacklist import load_blacklist, NEGATIVE_HINTS
from src import mappings as mapx

class BossService:
    def __init__(self):
        @asynccontextmanager
        async def lifespan(app):
            # 应用启动时启动浏览器并尝试登录
            if self.browser is None:
                await run_in_threadpool(self.start_browser)
            try:
                ok = await run_in_threadpool(self.ensure_login)
                if ok:
                    self.is_logged_in = True
            except Exception:
                pass
            yield
            # 应用关闭时优雅释放资源
            await run_in_threadpool(self._graceful_shutdown)

        self.app = FastAPI(title="BossZhipin Service", lifespan=lifespan)
        self.browser = None
        self.page = None
        self.is_logged_in = False
        self.last_code_hash = None
        self.playwright = None
        self.lock = threading.Lock()
        self.notifications = []  # 通知列表
        self.shutdown_requested = False
        # 读取黑名单
        bl = load_blacklist()
        self.black_companies = bl.get('blackCompanies', set())
        self.black_jobs = bl.get('blackJobs', set())
        self.black_recruiters = bl.get('blackRecruiters', set())
        self.setup_routes()
        # 注册优雅退出信号
        try:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except Exception:
            pass
    
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
    
    def add_notification(self, message, level="info"):
        """添加通知"""
        notification = {
            'id': len(self.notifications) + 1,
            'message': message,
            'level': level,  # info, success, warning, error
            'timestamp': datetime.now().isoformat()
        }
        self.notifications.append(notification)
        print(f"[{level.upper()}] {message}")
        
        # 保持最近100条通知
        if len(self.notifications) > 100:
            self.notifications = self.notifications[-100:]
        
    def setup_routes(self):
        """设置API路由 (FastAPI)"""
        
        @self.app.middleware("http")
        async def _ensure_browser_and_login(request, call_next):
            # 懒加载浏览器并确保登录；在线程池运行同步逻辑
            try:
                if self.browser is None:
                    await run_in_threadpool(self.start_browser)
                if not self.is_logged_in:
                    ok = await run_in_threadpool(self.ensure_login)
                    if ok:
                        self.is_logged_in = True
            except Exception:
                pass
            response = await call_next(request)
            return response

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
    
    def start_browser(self):
        """启动浏览器"""
        with self.lock:
            self.add_notification("启动浏览器...", "info")
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=settings.HEADLESS, 
                slow_mo=settings.SLOWMO_MS
            )
            
            # 尝试加载保存的登录状态
            storage_state_path = self._resolve_storage_state_path()
            if os.path.exists(storage_state_path):
                self.add_notification("加载保存的登录状态...", "info")
                try:
                    context = self.browser.new_context(storage_state=storage_state_path)
                    self.add_notification("登录状态加载成功", "success")
                except Exception as e:
                    self.add_notification(f"加载登录状态失败: {e}", "warning")
                    context = self.browser.new_context()
            else:
                self.add_notification("未找到保存的登录状态，创建新会话", "info")
                context = self.browser.new_context()
            
            self.page = context.new_page()
            self.add_notification("浏览器启动成功", "success")
    
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
        if self.is_logged_in and self.check_login_status():
            return True
        
        self.add_notification("开始登录流程...", "info")
        
        try:
            # 访问首页
            self.page.goto(settings.BASE_URL, wait_until="domcontentloaded", timeout=10000)
            time.sleep(2)
            
            page_text = self.page.locator("body").inner_text()
            
            # 检查是否有登录按钮
            if "登录" in page_text and ("立即登录" in page_text or "登录/注册" in page_text):
                self.add_notification("需要手动登录，请在浏览器中完成登录...", "warning")
                self.add_notification(f"最大等待时间: {max_wait_time} 秒", "info")
                
                start_time = time.time()
                while time.time() - start_time < max_wait_time:
                    remaining_time = max_wait_time - (time.time() - start_time)
                    remaining_minutes = int(remaining_time // 60)
                    remaining_seconds = int(remaining_time % 60)
                    
                    self.add_notification(f"等待登录中... 剩余时间: {remaining_minutes}分{remaining_seconds}秒", "info")
                    
                    # 检查登录状态
                    if self.check_login_status():
                        self.is_logged_in = True
                        self.save_login_state()
                        self.add_notification("登录成功！", "success")
                        return True
                    
                    time.sleep(10)
                
                self.add_notification("登录超时", "error")
                return False
            else:
                # 已经登录
                self.is_logged_in = True
                self.save_login_state()
                self.add_notification("已处于登录状态", "success")
                return True
                
        except Exception as e:
            print(f"[!] 登录检查失败: {e}")
            return False
    
    def get_candidates_list(self, limit=10):
        """获取候选人列表"""
        with self.lock:
            if not self.is_logged_in:
                raise Exception("未登录")
            
            self.add_notification(f"获取候选人列表 (限制: {limit})", "info")
            
            # 检查页面是否有效，如果无效则重新创建
            try:
                if not self.page or self.page.is_closed():
                    self.add_notification("页面已关闭，重新创建页面", "warning")
                    self._recreate_page()
            except Exception:
                self.add_notification("页面状态异常，重新创建页面", "warning")
                self._recreate_page()
            
            try:
                # 访问聊天页面并充分等待
                self.page.goto(
                    settings.BASE_URL.rstrip('/') + "/web/chat/index",
                    wait_until="domcontentloaded",
                    timeout=60000  # 增加到60秒
                )
                try:
                    self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                time.sleep(1)

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
    
    def get_messages_list(self, limit=10):
        """获取消息列表"""
        # 复用候选人列表逻辑，因为消息和候选人在同一页面
        return self.get_candidates_list(limit)

    def _recreate_page(self):
        """重新创建页面"""
        try:
            if self.page and not self.page.is_closed():
                self.page.close()
        except Exception:
            pass
        
        try:
            # 重新创建页面
            self.page = self.context.new_page()
            self.add_notification("页面已重新创建", "info")
        except Exception as e:
            self.add_notification(f"重新创建页面失败: {e}", "error")
            raise Exception(f"重新创建页面失败: {e}")

    def _graceful_shutdown(self):
        try:
            if self.page is not None:
                try:
                    ctx = self.page.context
                    self.page.close()
                    ctx.close()
                except Exception:
                    pass
            if self.browser is not None:
                try:
                    self.browser.close()
                except Exception:
                    pass
            if self.playwright is not None:
                try:
                    self.playwright.stop()
                except Exception:
                    pass
        except Exception:
            pass
    
    def send_greeting(self, candidate_id, message):
        """发送打招呼消息"""
        print(f"[*] 向候选人 {candidate_id} 发送打招呼消息")
        # TODO: 实现打招呼逻辑
        return True
    
    def get_candidate_resume(self, candidate_id):
        """获取候选人简历"""
        with self.lock:
            if not self.is_logged_in:
                raise Exception("未登录")
            
            self.add_notification(f"获取候选人 {candidate_id} 的简历", "info")
            
            # 检查页面是否有效
            try:
                if not self.page or self.page.is_closed():
                    self.add_notification("页面已关闭，重新创建页面", "warning")
                    self._recreate_page()
            except Exception:
                self.add_notification("页面状态异常，重新创建页面", "warning")
                self._recreate_page()
            
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
    
    def check_code_updates(self):
        """检查代码更新"""
        current_hash = self.get_code_hash()
        if self.last_code_hash and current_hash != self.last_code_hash:
            # 触发热更新（不重启，不关闭浏览器）
            try:
                self.reload_code()
                self.add_notification("代码已热更新(无需重启)", "success")
            except Exception as e:
                self.add_notification(f"热更新失败: {e}", "error")
            return True
        self.last_code_hash = current_hash
        return False
    
    def get_code_hash(self):
        """获取代码文件哈希值"""
        hash_md5 = hashlib.md5()
        # 仅监控 src 目录的变更，避免自身文件热更新复杂度
        for root, dirs, files in os.walk("src"):
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "rb") as f:
                            hash_md5.update(f.read())
                    except:
                        pass
        return hash_md5.hexdigest()
    
    def start_monitoring(self):
        """(已禁用) 启动代码监控"""
        return

    def reload_code(self):
        """热更新配置/工具模块，不关闭浏览器和Flask。"""
        import importlib
        with self.lock:
            # 重新加载配置与工具模块
            try:
                import src.config as cfg_mod
                cfg_mod = importlib.reload(cfg_mod)
                # 更新全局 settings 引用
                globals()['settings'] = cfg_mod.settings
                self.add_notification("配置已热更新", "success")
            except Exception as e:
                self.add_notification(f"配置热更新失败: {e}", "error")
            
            try:
                import src.utils as utils_mod
                importlib.reload(utils_mod)
                self.add_notification("工具模块已热更新", "success")
            except Exception as e:
                self.add_notification(f"工具模块热更新失败: {e}", "warning")
            
            try:
                import src.page_selectors as sel_mod
                importlib.reload(sel_mod)
                self.add_notification("选择器模块已热更新", "success")
            except Exception as e:
                self.add_notification(f"选择器模块热更新失败: {e}", "warning")
    
    def _handle_signal(self, signum, frame):
        if self.shutdown_requested:
            return
        self.shutdown_requested = True
        self.add_notification("收到停止信号，正在优雅退出...", "info")
        self._graceful_shutdown()
    
    def _graceful_shutdown(self):
        with self.lock:
            try:
                if self.page is not None:
                    try:
                        ctx = self.page.context
                        self.page.close()
                        ctx.close()
                    except Exception:
                        pass
                if self.browser is not None:
                    try:
                        self.browser.close()
                    except Exception:
                        pass
                if self.playwright is not None:
                    try:
                        self.playwright.stop()
                    except Exception:
                        pass
                self.add_notification("浏览器与Playwright已关闭", "success")
            finally:
                try:
                    import sys
                    sys.exit(0)
                except SystemExit:
                    pass
    
    def run(self, host='127.0.0.1', port=5001):
        """运行服务 (使用uvicorn由外部启动)"""
        import uvicorn
        self.add_notification("启动Boss直聘后台服务(FastAPI)...", "info")
        reload_flag = os.environ.get("FLASK_DEBUG", "1") in ("1", "true", "yes", "on")
        if reload_flag:
            # 使用可导入字符串以启用 reload
            uvicorn.run("boss_service:app", host=host, port=port, reload=True, log_level="info")
        else:
            uvicorn.run(self.app, host=host, port=port, reload=False, log_level="info")

service = BossService()
app = service.app

if __name__ == "__main__":
    host = os.environ.get("BOSS_SERVICE_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("BOSS_SERVICE_PORT", "5001"))
    except Exception:
        port = 5001
    service.run(host=host, port=port)

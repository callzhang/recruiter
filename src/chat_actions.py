"""Common high-level chat actions used by automation flows."""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import Locator
from .resume_capture import extract_pdf_viewer_text, capture_resume_from_chat
from .extractors import extract_candidates, extract_messages, extract_chat_history
from src.config import settings
from .chat_utils import close_overlay_dialogs
CHAT_ITEM_SELECTORS = ("div.geek-item", "[role='listitem']")
CONVERSATION_SELECTOR = "div.conversation-message"
MESSAGE_INPUT_SELECTOR = "#boss-chat-editor-input"
RESUME_BUTTON_SELECTOR = "div.resume-btn-file, a.resume-btn-file"
RESUME_IFRAME_SELECTOR = "iframe.attachment-box"
PDF_VIEWER_SELECTOR = "div.pdfViewer"



def _prepare_chat_page(page, chat_id: str = None, *, wait_timeout: int = 5000) -> tuple[Optional[Locator], Optional[Dict[str, Any]]]:
    # Ensure we are on the chat page; if not, click the chat menu
    # If current URL is not the chat page, click the chat menu to navigate
    close_overlay_dialogs(page)
    if not settings.CHAT_URL in page.url:
        menu_chat = page.locator("dl.menu-chat").first
        menu_chat.click()
        # Wait for chat list to appear
        page.wait_for_selector("div.geek-item, [role='listitem']", timeout=wait_timeout)
    """Ensure the chat is focused and the conversation panel is ready."""

    if not chat_id:
        return None, None
    direct_selectors = [
        f"div.geek-item[data-id=\"{chat_id}\"]",
        # f"div[role='listitem'][key=\"{chat_id}\"]",
    ]
    for selector in direct_selectors:
        locator = page.locator(selector)
        if locator.count():
            target = locator.first

    # move to chat target
    if target:
        target.scroll_into_view_if_needed(timeout=1000)
    if target is None:
        return None, { 'success': False, 'details': '未找到指定对话项' }
    # 如果已经选中，直接返回
    if 'selected' in target.get_attribute('class'):
        return target, None
    # click chat target
    target.click()

    page.wait_for_selector(CONVERSATION_SELECTOR, timeout=wait_timeout)

    return target, None



def request_resume_action(page, chat_id: str, *, logger=lambda msg, level: None) -> Dict[str, Any]:
    """Send a resume request in the open chat panel for the given chat_id"""
    _, error = _prepare_chat_page(page, chat_id)
    if error:
        error.setdefault('already_sent', False)
        return error

    # Find the resume request button
    btn = page.locator("span.operate-btn:has-text('求简历')").first
    btn.wait_for(state="visible", timeout=3000)

    # Check if button is disabled (already sent)
    is_disabled = btn.evaluate("el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null")
    if is_disabled:
        return { 'success': True, 'already_sent': True, 'details': '简历请求已发送（按钮已禁用）' }


    # Click the resume request button
    btn.click()
    # Confirm
    btn0 = page.locator('button:has-text("继续交换")')
    if btn0.count():
        btn0.click()
    confirm = page.locator("span.boss-btn-primary:has-text('确定')").first
    confirm.click()

    # Verify
    try:
        page.wait_for_function(
            "() => (document.body && document.body.innerText && document.body.innerText.includes('简历请求已发送'))",
            timeout=5000
        )
        return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }
    except Exception:
        try:
            is_disabled = btn.evaluate("el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null")
            if is_disabled:
                return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }
        except Exception:
            pass
        return { 'success': False, 'already_sent': False, 'details': '未检测到发送成功提示' }


def send_message_action(page, chat_id: str, message: str, *, logger=lambda msg, level: None) -> Dict[str, Any]:
    """Send a text message in the open chat panel for the given chat_id"""
    _, error = _prepare_chat_page(page, chat_id)
    if error:
        return error

    # Find the message input field
    input_field = page.locator(MESSAGE_INPUT_SELECTOR).first
    if not input_field.count():
        return { 'success': False, 'details': '未找到消息输入框' }
    
    try:
        input_field.wait_for(state="visible", timeout=3000)
    except Exception:
        return { 'success': False, 'details': '消息输入框未显示' }

    # Clear existing content and type the message
    try:
        input_field.click()
        input_field.fill("")  # Clear existing content
        input_field.type(message)
    except Exception as e:
        return { 'success': False, 'details': f'输入消息失败: {e}' }

    # Find and click the send button
    send_button = page.locator("div.submit:has-text('发送')").first
    if not send_button.count():
        return { 'success': False, 'details': '未找到发送按钮' }
    
    try:
        send_button.wait_for(state="visible", timeout=3000)
        send_button.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击发送按钮失败: {e}' }

    # Wait a moment for the message to be sent
    page.wait_for_timeout(1000)

    # Verify the message was sent by checking if input field is cleared
    remaining = input_field.evaluate("el => (el.value || el.innerText || '').trim()") or input_field.inner_text() or ''
    if not remaining:
        return { 'success': True, 'details': '消息发送成功' }
    return { 'success': False, 'details': '消息可能未发送成功，输入框仍有内容' }


def view_full_resume_action(page, chat_id: str, *, logger=lambda msg, level: None) -> Dict[str, Any]:
    """点击查看候选人的附件简历"""

    _, error = _prepare_chat_page(page, chat_id, wait_timeout=5000)
    if error:
        return error
    # close existing overlay if present
    try:
        close_locator = 'div.boss-popup__close'
        page.locator(close_locator).click(timeout=100)
    except Exception:
        pass

    # Find and click the resume file button
    resume_button = page.locator(RESUME_BUTTON_SELECTOR).first
    if not resume_button.count():
        return { 'success': False, 'details': '未找到简历按钮' }
    # Check if the resume button is disabled
    t0 = time.time()
    while is_disabled := "disabled" in resume_button.get_attribute("class"):
        time.sleep(0.1)
        print(f'简历按钮已禁用，等待0.1秒后重试: {time.time() - t0}')
        if time.time() - t0 > 2:
            return { 'success': False, 'details': '简历按钮未启用，请先请求简历' }
    if is_disabled:
        return { 'success': False, 'details': '暂无离线简历，请先请求简历' }
    resume_button.click()

    # Wait for resume viewer to appear
    try:
        # Wait for iframe to appear first
        iframe_handle = page.wait_for_selector(RESUME_IFRAME_SELECTOR, timeout=8000)
        frame = iframe_handle.content_frame()
        if frame is None:
            raise RuntimeError('attachment iframe 无法获取到 frame 对象')
        frame.wait_for_selector(PDF_VIEWER_SELECTOR, timeout=5000)
    except Exception as e:
        page.locator(close_locator).click(timeout=100)
        return { 'success': False, 'details': '简历查看器未出现', 'error': str(e) }

    try:
        content = extract_pdf_viewer_text(frame)
    finally:
        page.locator(close_locator).click(timeout=500)
    
    return {
        'success': True,
        'details': '简历查看器已打开',
        'content': content.get('text', ''),
        'pages': content.get('pages', []),
    }



def discard_candidate_action(page, chat_id: str, *, logger=lambda msg, level: None) -> Dict[str, Any]:
    """丢弃候选人 - 点击"不合适"按钮"""
    _, error = _prepare_chat_page(page, chat_id)
    if error:
        return error

    # 查找"不合适"按钮
    not_fit_button = page.locator("div.not-fit-wrap").first
    if not not_fit_button.count():
        return { 'success': False, 'details': '未找到"不合适"按钮' }
    
    try:
        not_fit_button.wait_for(state="visible", timeout=3000)
        not_fit_button.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击"不合适"按钮失败: {e}' }

    # 等待确认对话框
    try:
        confirm_button = page.locator("button:has-text('确定'), span:has-text('确定'), a:has-text('确定')").first
        confirm_button.wait_for(state="visible", timeout=3000)
        confirm_button.click()
    except Exception as e:
        return { 'success': False, 'details': f'确认丢弃失败: {e}' }

    # 验证操作成功
    page.wait_for_timeout(1000)
    return { 'success': True, 'details': '候选人已丢弃' }


def get_candidates_list_action(page, limit: int = 10, *, logger=lambda msg, level: None, black_companies=None, save_candidates_func=None):
    """获取候选人列表"""
    logger(f"获取候选人列表 (限制: {limit})", "info")
    _prepare_chat_page(page)
    # DOM 提取
    candidates = extract_candidates(page, limit=limit, logger=logger)
    
    # 黑名单过滤（如果存在）
    if candidates and black_companies:
        candidates = [c for c in candidates if not (c.get('company') and any(b in c.get('company') for b in black_companies))]

    logger(f"成功获取 {len(candidates)} 个候选人", "success")
    
    # 保存候选人数据到文件
    if candidates and save_candidates_func:
        save_candidates_func(candidates)
    
    return candidates


def get_messages_list_action(page, limit: int = 10, *, logger=lambda msg, level: None, chat_cache=None):
    """获取消息列表"""
    logger(f"获取消息列表 (限制: {limit})", "info")
    _prepare_chat_page(page)
    messages = extract_messages(page, limit=limit, chat_cache=chat_cache.get_all() if chat_cache else None)
    if not messages and chat_cache:
        # 使用事件管理器获取缓存的消息
        messages = chat_cache.get_all()
    if not messages:
        logger("消息列表为空（DOM+缓存均无）", "warning")
    logger(f"成功获取 {len(messages)} 条消息", "success")
    return messages


def get_chat_history_action(page, chat_id: str, *, logger=lambda msg, level: None) -> List[Dict[str, Any]]:
    """读取右侧聊天历史，返回结构化消息列表"""
    _, error = _prepare_chat_page(page, chat_id)
    if error:
        return []
    
    history = extract_chat_history(page, chat_id)
    return history




def view_online_resume_action(page, chat_id: str, *, logger=lambda msg, level: None) -> Dict[str, Any]:
    """点击会话 -> 点击"在线简历" -> 使用多级回退链条输出文本或图像"""
    _, error = _prepare_chat_page(page, chat_id)
    if error:
        return error

    result = capture_resume_from_chat(page, chat_id, logger=logger)
    close_overlay_dialogs(page, logger)
    # 统一加上success存在性
    if not isinstance(result, dict):
        return { 'success': False, 'details': '未知错误: 结果类型异常' }
    if 'success' not in result:
        result['success'] = bool(result.get('text') or result.get('image_base64') or result.get('data_url'))
    return result




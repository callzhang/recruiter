"""
User actions such as requesting a resume from a chat.
These functions encapsulate DOM actions and simple verifications.
"""

from __future__ import annotations
import time
from typing import Any, Dict, final


def request_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """Send a resume request in the open chat panel for the given chat_id."""
    # Locate target chat item
    target = None
    for sel in ["div.geek-item", "[role='listitem']"]:
        try:
            items = page.locator(sel).all()
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

    try:
        target.click()
    except Exception as e:
        return { 'success': False, 'already_sent': False, 'details': f'点击对话失败: {e}' }

    # Wait for conversation panel to load
    try:
        page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return { 'success': False, 'already_sent': False, 'details': '对话面板未加载' }

    # Find the resume request button
    btn = page.locator("span.operate-btn:has-text('求简历')").first
    if not btn or btn.count() == 0:
        return { 'success': False, 'already_sent': False, 'details': '未找到“求简历”按钮' }
    
    btn.wait_for(state="visible", timeout=3000)

    # Check if button is disabled (already sent)
    try:
        is_disabled = btn.evaluate("el => el.classList.contains('disabled') || el.disabled || el.getAttribute('disabled') !== null")
        if is_disabled:
            return { 'success': True, 'already_sent': True, 'details': '简历请求已发送（按钮已禁用）' }
    except Exception:
        pass

    # Click the resume request button
    try:
        btn.click()
    except Exception as e:
        return { 'success': False, 'already_sent': False, 'details': f'点击“求简历”失败: {e}' }

    # Confirm
    confirm = page.locator("span:has-text('确定'), button:has-text('确定'), a:has-text('确定')").first
    try:
        confirm.wait_for(state="visible", timeout=3000)
        confirm.click()
    except Exception:
        return { 'success': False, 'already_sent': False, 'details': '未找到“确定”按钮' }

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


def send_message_action(page, chat_id: str, message: str) -> Dict[str, Any]:
    """Send a text message in the open chat panel for the given chat_id."""
    # Locate target chat item
    target = None
    for sel in ["div.geek-item", "[role='listitem']"]:
        try:
            items = page.locator(sel).all()
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
        return { 'success': False, 'details': '未找到指定对话项' }

    try:
        target.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击对话失败: {e}' }

    # Wait for conversation panel to load
    try:
        page.wait_for_selector("div.conversation-message", timeout=5000)
    except Exception:
        return { 'success': False, 'details': '对话面板未加载' }

    # Find the message input field
    input_field = page.locator("#boss-chat-editor-input").first
    if not input_field or input_field.count() == 0:
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
    if not send_button or send_button.count() == 0:
        return { 'success': False, 'details': '未找到发送按钮' }
    
    try:
        send_button.wait_for(state="visible", timeout=3000)
        send_button.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击发送按钮失败: {e}' }

    # Wait a moment for the message to be sent
    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass

    # Verify the message was sent by checking if input field is cleared
    try:
        current_content = input_field.inner_text()
        if not current_content.strip():
            return { 'success': True, 'details': '消息发送成功' }
        else:
            return { 'success': False, 'details': '消息可能未发送成功，输入框仍有内容' }
    except Exception:
        return { 'success': True, 'details': '消息发送完成（无法验证）' }


def view_resume_action(page, chat_id: str) -> Dict[str, Any]:
    """点击查看候选人的附件简历"""
    # Locate target chat item
    try:
        page.locator('div.boss-popup__close', timeout=100).click()
    except Exception:
        pass
    target = None
    try:
        items = page.locator("div.geek-item").all()
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

    if not target:
        return { 'success': False, 'details': '未找到指定对话项' }

    try:
        target.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击对话失败: {e}' }

    # Wait for conversation panel to load
    try:
        page.wait_for_selector("div.conversation-message", timeout=500)
    except Exception:
        return { 'success': False, 'details': '对话面板未加载' }

    # Find and click the resume file button
    resume_button = page.locator("a.btn.resume-btn-file").first
    
    try:
        resume_button.click()
    except Exception as e:
        return { 'success': False, 'details': f'点击附件简历按钮失败: {e}' }

    # Wait for resume viewer to appear
    try:
        page.wait_for_selector("div.new-resume-online-main-ui", timeout=5000)
    except Exception:
        page.locator('div.boss-popup__close').click()
        return { 'success': False, 'details': '简历查看器未出现' }

    # Wait a moment for the viewer to fully load
    time.sleep(1)

    # get the content of the viewer
    try:
        content = page.locator('div.new-resume-online-main-ui').inner_text()
    except Exception as e:
        return { 'success': False, 'details': f'简历查看器未出现: {e}' }
    finally:
        page.locator('div.boss-popup__close').click()
    return { 'success': True, 'details': '简历查看器已打开', 'content': content }




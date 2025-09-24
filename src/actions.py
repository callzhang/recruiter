"""
User actions such as requesting a resume from a chat.
These functions encapsulate DOM actions and simple verifications.
"""

from __future__ import annotations

from typing import Any, Dict


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



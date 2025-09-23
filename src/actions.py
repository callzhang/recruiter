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

    # If already sent
    try:
        conv = page.locator("div.conversation-message").first
        if conv.count() > 0:
            text_now = conv.inner_text()
            if "简历请求已发送" in text_now:
                return { 'success': True, 'already_sent': True, 'details': '已存在简历请求' }
    except Exception:
        pass

    # Click request resume
    btn = page.locator("a:has-text('求简历'), button:has-text('求简历'), span:has-text('求简历')").first
    if not btn or btn.count() == 0:
        return { 'success': False, 'already_sent': False, 'details': '未找到“求简历”按钮' }
    try:
        btn.wait_for(state="visible", timeout=3000)
    except Exception:
        pass
    try:
        btn.click()
    except Exception as e:
        return { 'success': False, 'already_sent': False, 'details': f'点击“求简历”失败: {e}' }

    # Confirm
    confirm = page.locator("span:has-text('确定')").first
    try:
        confirm.wait_for(state="visible", timeout=3000)
        confirm.click()
    except Exception:
        confirm_btn = page.locator("button:has-text('确定'), a:has-text('确定')").first
        if confirm_btn and confirm_btn.count() > 0:
            try:
                confirm_btn.click()
            except Exception:
                return { 'success': False, 'already_sent': False, 'details': '点击“确定”失败' }
        else:
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
            panel_text = page.locator("div.conversation-message").first.inner_text()
            if "简历请求已发送" in panel_text:
                return { 'success': True, 'already_sent': False, 'details': '简历请求已发送' }
        except Exception:
            pass
        return { 'success': False, 'already_sent': False, 'details': '未检测到发送成功提示' }



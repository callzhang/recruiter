"""
User actions such as requesting a resume from a chat.
These functions encapsulate DOM actions and simple verifications.
"""

from __future__ import annotations
import time
from typing import Any, Dict, final

from playwright.sync_api import Frame


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
    close_locator = 'div.boss-popup__close'
    try:
        page.locator(close_locator).click(timeout=100)
    except Exception:
        pass

    # Locate target chat item
    target = None
    items = page.locator("div.geek-item").all()
    for it in items:
        did = it.get_attribute('data-id') or it.get_attribute('id')
        if did and chat_id and did == chat_id:
            target = it
            break
    if not target:
        return { 'success': False, 'details': '未找到指定对话项' }
    
    target.click()

    # Wait for conversation panel to load
    page.wait_for_selector("div.conversation-message", timeout=500)

    # Find and click the resume file button
    resume_button = page.locator("a.btn.resume-btn-file").first
    resume_button.click()

    # Wait for resume viewer to appear
    try:
        # Wait for iframe to appear first
        iframe_handle = page.wait_for_selector("iframe.attachment-box", timeout=8000)
        frame = iframe_handle.content_frame()
        if frame is None:
            raise RuntimeError('attachment iframe 无法获取到 frame 对象')
        frame.wait_for_selector("div.pdfViewer", timeout=5000)
    except Exception as e:
        page.locator(close_locator).click(timeout=100)
        return { 'success': False, 'details': '简历查看器未出现', 'error': str(e) }

    try:
        content = _scrape_pdf_viewer(frame)
    finally:
        page.locator(close_locator).click(timeout=100)
    
    return {
        'success': True,
        'details': '简历查看器已打开',
        'content': content.get('text', ''),
        'pages': content.get('pages', []),
    }



def _scrape_pdf_viewer(frame: Frame) -> Dict[str, Any]:
    """Extract text from the PDF viewer by walking its text layers."""
    try:
        # Wait for at least one page textLayer to stabilize
        frame.locator("div.textLayer").first.wait_for(state="visible", timeout=5000)
    except Exception:
        pass

    def _collect_text() -> Dict[str, Any]:
        return frame.evaluate(
            """
            async () => {
              const app = window.PDFViewerApplication;
              if (!app || !app.pdfDocument) {
                return { __error: 'pdfDocument not ready' };
              }

              const doc = app.pdfDocument;
              const viewer = app.pdfViewer;
              const scale = viewer && viewer._currentScale ? viewer._currentScale : 1;
              const results = [];

              for (let pageIndex = 1; pageIndex <= doc.numPages; pageIndex++) {
                const page = await doc.getPage(pageIndex);
                const viewport = page.getViewport({ scale });
                const textContent = await page.getTextContent();

                const items = textContent.items.map(item => {
                  const [x, y] = viewport.convertToViewportPoint(item.transform[4], item.transform[5]);
                  const height = item.height || Math.abs(item.transform[3]) || 1;
                  const width = item.width || Math.abs(item.transform[0]) || 1;
                  return {
                    text: item.str,
                    x,
                    y,
                    height,
                    width,
                  };
                }).filter(item => item.text && item.text.trim());

                items.sort((a, b) => {
                  if (Math.abs(a.y - b.y) > 2) {
                    return a.y - b.y;
                  }
                  return a.x - b.x;
                });

                const lines = [];
                let currentY = null;
                let buffer = [];
                let tolerance = 6;
                if (items.length) {
                  const heights = items.map(s => s.height).filter(Boolean);
                  const avg = heights.reduce((acc, val) => acc + val, 0) / heights.length;
                  tolerance = Math.max(6, avg * 0.8);
                }

                const flush = () => {
                  if (!buffer.length) return;
                  const joined = buffer
                    .join(' ')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim();
                  if (joined) {
                    lines.push(joined);
                  }
                  buffer = [];
                };

                for (const item of items) {
                  if (currentY === null) {
                    currentY = item.y;
                  }
                  if (Math.abs(item.y - currentY) > tolerance) {
                    flush();
                    currentY = item.y;
                  }
                  buffer.push(item.text);
                }
                flush();

                results.push({ page: pageIndex, lines, text: lines.join('\n') });
              }

              return results;
            }
            """
        )

    try:
        pages = _collect_text() or []
    except Exception:
        pages = []

    if isinstance(pages, dict):
        if '__error' in pages:
            # Fall back to DOM-based extraction if pdf.js API is unavailable
            pages = []
        else:
            pages = [pages]

    if not pages:
        try:
            fallback = frame.evaluate("() => document.body.innerText || ''")
        except Exception:
            fallback = ''
        return {'pages': [], 'text': fallback if isinstance(fallback, str) else ''}

    combined_lines = []
    for page in pages:
        lines = page.get('lines') or []
        if not lines:
            continue
        combined_lines.extend(lines)

    text = '\n'.join(line for line in combined_lines if line)
    return {'pages': pages, 'text': text}

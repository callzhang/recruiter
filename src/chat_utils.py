"""
Shared chat utilities for navigation and element discovery.
These helpers are side-effect free (except for Playwright interactions)
and do not depend on BossService internals.
"""

from __future__ import annotations

from typing import Any, Optional


def _notify(add_notification, message: str, level: str = "info") -> None:
    try:
        if callable(add_notification):
            add_notification(message, level)
    except Exception:
        pass


def ensure_on_chat_page(page, settings, add_notification=None, timeout_ms: int = 6000) -> bool:
    """Ensure we are on the chat page; navigate if necessary. Returns True if ok."""
    try:
        if settings.CHAT_URL not in getattr(page, 'url', ''):
            try:
                page.goto(settings.CHAT_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
            except Exception as e:
                _notify(add_notification, f"导航聊天页面失败: {e}", "warning")
                return False
        return True
    except Exception:
        return False


def find_chat_item(page, chat_id: str):
    """Return a locator to the chat list item for chat_id, or None if not found."""
    try:
        precise = page.locator(
            f"div.geek-item[id='{chat_id}'], div.geek-item[data-id='{chat_id}'], "
            f"[role='listitem'][id='{chat_id}'], [role='listitem'][data-id='{chat_id}']"
        ).first
        if precise and precise.count() > 0:
            return precise
    except Exception:
        pass
    # Fallback scan
    try:
        for sel in ["div.geek-item", "[role='listitem']"]:
            try:
                items = page.locator(sel).all()
            except Exception:
                items = []
            for it in items:
                try:
                    did = it.get_attribute('data-id') or it.get_attribute('id')
                    if did and chat_id and did == chat_id:
                        return it
                except Exception:
                    continue
    except Exception:
        pass
    return None


def close_overlay_dialogs(page, add_notification=None, timeout_ms: int = 1000) -> bool:
    """Close any overlay dialogs that might be blocking the page.
    
    Args:
        page: Playwright page object
        add_notification: Optional notification callback
        timeout_ms: Timeout for close operations
        
    Returns:
        bool: True if any overlay was closed, False otherwise
    """
    closed_any = False
    
    # Close boss-layer__wrapper overlays (like resume dialogs)
    try:
        overlay_resume = page.locator("div.boss-layer__wrapper")
        if overlay_resume.count() > 0:
            _notify(add_notification, "检测到在线简历对话框，正在关闭", "info")
            try:
                # Try the close button first
                close_btn = page.locator('div.boss-popup__close')
                if close_btn.count() > 0:
                    close_btn.click(timeout=timeout_ms)
                    closed_any = True
                else:
                    # Fallback: try clicking outside the dialog
                    overlay_resume.click(position={"x": 10, "y": 10}, timeout=timeout_ms)
                    closed_any = True
            except Exception:
                pass
    except Exception:
        pass
    
    # Close other common overlay types
    overlay_selectors = [
        "div.boss-popup",
        "div.popup-overlay", 
        "div.modal-overlay",
        "div.dialog-overlay",
        "[role='dialog']",
        ".ant-modal-mask",
        ".el-dialog__wrapper"
    ]
    
    for selector in overlay_selectors:
        try:
            overlay = page.locator(selector)
            if overlay.count() > 0:
                _notify(add_notification, f"检测到弹出层 {selector}，正在关闭", "info")
                try:
                    # Try close button variations
                    close_selectors = [
                        f"{selector} .close",
                        f"{selector} .popup-close", 
                        f"{selector} .dialog-close",
                        f"{selector} [aria-label='Close']",
                        f"{selector} .ant-modal-close",
                        f"{selector} .el-dialog__close"
                    ]
                    
                    closed = False
                    for close_sel in close_selectors:
                        try:
                            close_btn = page.locator(close_sel)
                            if close_btn.count() > 0:
                                close_btn.click(timeout=timeout_ms)
                                closed = True
                                break
                        except Exception:
                            continue
                    
                    if not closed:
                        # Fallback: press Escape key
                        page.keyboard.press("Escape")
                        closed = True
                    
                    if closed:
                        closed_any = True
                        
                except Exception:
                    pass
        except Exception:
            pass
    
    # Wait a bit for overlays to close
    if closed_any:
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass
    
    return closed_any



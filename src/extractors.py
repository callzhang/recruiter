"""
DOM extractors for candidates list, messages list, and chat history.
These functions rely only on Playwright page/frame and selectors module.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src import page_selectors as sel


def extract_candidates(page, limit: int, logger=lambda msg, level: None) -> List[Dict[str, Any]]:
    candidates = []

    selectors = sel.conversation_list_items()

    for selector in selectors:
        try:
            elements = page.locator(selector).all()
            if elements:
                logger(f"使用选择器 {selector} 找到 {len(elements)} 个元素", "info")
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
                            }

                            # 轻量结构化
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
                            candidates.append(candidate)
                    except Exception:
                        continue
                if candidates:
                    break
        except Exception:
            continue

    return candidates


def extract_messages(page, limit: int, chat_cache: dict | None = None) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
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

    for sel_ in item_selectors:
        try:
            elems = page.locator(sel_).all()
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
                if chat_cache:
                    for _, cached in chat_cache.items():
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

    return messages


def extract_chat_history(page, chat_id: str) -> List[Dict[str, Any]]:
    # Click target chat item first
    target = None
    for sel_ in ["div.geek-item", "[role='listitem']"]:
        try:
            items = page.locator(sel_).all()
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
    try:
        if target:
            target.click()
    except Exception:
        pass

    history: List[Dict[str, Any]] = []
    try:
        container = page.locator("div.conversation-message").first
        lst = container.locator("div.chat-message-list").first
        items = lst.locator("div.message-item").all()
    except Exception:
        items = []

    def _t(loc):
        try:
            return loc.inner_text().strip()
        except Exception:
            return ""

    for it in items:
        try:
            ts = _t(it.locator(".message-time .time").first)
            text = _t(it.locator(".item-friend .text span").first)
            if not text:
                sys_text = _t(it.locator(".item-system").first)
                text = sys_text or _t(it)
            history.append({
                'time': ts or '',
                'text': text,
            })
        except Exception:
            continue

    return history



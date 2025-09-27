"""Recommendation page actions for Boss Zhipin automation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from playwright.sync_api import Locator


def _prepare_recommendation_page(page, *, wait_timeout: int = 8000) -> tuple[Optional[Locator], Optional[Dict[str, Any]]]:
    """Ensure the recommendation panel is opened and ready."""
    # Click the recommendation menu
    if not page.url.startswith("https://www.zhipin.com/web/chat/recommend"):
        menu_locator = page.locator("dl.menu-recommend").first
        menu_locator.scroll_into_view_if_needed(timeout=2000)
        menu_locator.click()

    # Wait for the iframe to appear and get its frame
    try:
        iframe = page.wait_for_selector('iframe[name="recommendFrame"]', timeout=wait_timeout)
        frame = iframe.content_frame()
        if frame is None:
            return None, { 'success': False, 'details': '推荐iframe无法获取到frame对象' }
        
        frame.wait_for_selector("li.card-item", timeout=5000)
        return frame, None
    except Exception as e:
        return None, { 'success': False, 'details': f'推荐列表未加载: {e}' }


def list_recommended_candidates_action(page, *, limit: int = 20) -> Dict[str, Any]:
    """Click the recommended panel and return structured card information."""
    frame, error = _prepare_recommendation_page(page)
    if error:
        return error

    # Use the frame to locate card items
    card_locators: List[Locator] = frame.locator("li.card-item").all()

    candidates: List[Dict[str, Any]] = []
    for idx, card in enumerate(card_locators[:limit]):

        candidate: Dict[str, Any] = { 'index': idx + 1 }

        cand_id = card.get_attribute('data-id') or card.get_attribute('data-geekid') or card.get_attribute('data-uid')
        if cand_id:
            candidate['id'] = cand_id

        href = ''
        link_locator = card.locator("a").first
        href = link_locator.get_attribute('href') or ''
        candidate['link'] = href

        raw_text = card.inner_text().strip()
        if raw_text:
            candidate['raw_text'] = raw_text

        name = ''
        for selector in ('.name', '.user-name', '.geek-name', '.card-name', '.recommend-card__user-name', '.info-name', '.title'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    name = text
                    break
        if name:
            candidate['name'] = name

        job_title = ''
        for selector in ('.job-name', '.job-title', '.recommend-card__job', '.position', '.card-job-name', '.job-text'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    job_title = text
                    break
        if job_title:
            candidate['job_title'] = job_title

        company = ''
        for selector in ('.company', '.company-name', '.recommend-card__company', '.card-company', '.job-company'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    company = text
                    break
        if company:
            candidate['company'] = company

        salary = ''
        for selector in ('.salary', '.salary-text', '.job-salary', '.recommend-card__salary'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    salary = text
                    break
        if salary:
            candidate['salary'] = salary

        location = ''
        for selector in ('.location', '.job-area', '.job-city', '.recommend-card__city'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    location = text
                    break
        if location:
            candidate['location'] = location

        experience = ''
        for selector in ('.experience', '.exp', '.work-exp', '.resume-item-exp'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    experience = text
                    break
        if experience:
            candidate['experience'] = experience

        education = ''
        for selector in ('.education', '.edu', '.resume-item-edu', '.card-edu'):
            sub = card.locator(selector).first
            if sub.count():
                text = sub.inner_text().strip()
                if text:
                    education = text
                    break
        if education:
            candidate['education'] = education

        tags: List[str] = []
        for selector in ('.tag', '.tag-item', '.label', '.skill-tag', '.job-tag'):
            for tag_node in card.locator(selector).all():
                text = tag_node.inner_text().strip()
                if text and text not in tags:
                    tags.append(text)
        if tags:
            candidate['tags'] = tags

        if candidate.get('raw_text') or candidate.get('name'):
            candidates.append(candidate)

    success = bool(candidates)
    details = f"成功获取 {len(candidates)} 个推荐候选人" if success else '未找到推荐候选人'
    return { 'success': success, 'details': details, 'candidates': candidates }

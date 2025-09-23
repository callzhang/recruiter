#!/usr/bin/env python3
import types
import json

from boss_client import BossClient


class DummyResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_client_api_workflow_monkeypatch(monkeypatch):
    """Test the main workflow using the optimized client API"""
    client = BossClient('http://127.0.0.1:5001')

    # Mock get_messages -> one message with chat_id
    def fake_get_messages(limit=10):
        return {
            'success': True,
            'messages': [
                {
                    'chat_id': 'demo-chat-1',
                    'candidate': '张三',
                    'message': '你好',
                    'job_title': 'Python工程师'
                }
            ],
            'count': 1
        }

    # Mock the new get_resume API to return ResumeResult-like response
    def fake_get_resume(chat_id: str, capture_method: str = "auto"):
        from boss_client import ResumeResult
        # Mock successful text extraction
        return ResumeResult(
            success=True,
            chat_id=chat_id,
            capture_method="wasm",
            text="候选人有5年Python经验，熟悉FastAPI和Playwright。",
            html=None,
            image_base64=None,
            images_base64=[],
            data_url=None,
            width=0,
            height=0,
            details="来自WASM导出(get_export_geek_detail_info) - 方法:auto",
            error=None
        )

    # Mock OCR method
    def fake_ocr_local_from_b64(image_b64: str):
        return "候选人有5年Python经验，熟悉FastAPI和Playwright。"

    monkeypatch.setattr(client, 'get_messages', fake_get_messages)
    monkeypatch.setattr(client, 'get_resume', fake_get_resume)
    monkeypatch.setattr(client, 'ocr_local_from_b64', fake_ocr_local_from_b64)

    # Test workflow: get messages -> get resume -> check text extraction
    messages_response = client.get_messages(limit=1)
    assert messages_response['success'] == True
    assert len(messages_response['messages']) == 1
    
    chat_id = messages_response['messages'][0]['chat_id']
    assert chat_id == 'demo-chat-1'
    
    # Test resume extraction
    resume_result = client.get_resume(chat_id)
    assert resume_result.success == True
    assert resume_result.has_text == True
    assert "Python经验" in resume_result.text
    assert resume_result.capture_method == "wasm"
    
    # Test convenience method
    text = client.get_resume_text(chat_id)
    assert text is not None
    assert "Python经验" in text



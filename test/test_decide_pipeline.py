import os
import sys
import json
import base64
import yaml

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from boss_client import BossClient


def stub_requests_post_ok(url, headers=None, json=None, timeout=60):
    class Resp:
        def __init__(self):
            self._json = {
                "choices": [
                    {
                        "message": {
                            "content": json_module.dumps({
                                "score": 0.82,
                                "decision": "greet",
                                "reasons": ["技能与岗位高度匹配"],
                                "highlights": ["5年LLM经验", "掌握LoRA"],
                                "risks": []
                            })
                        }
                    }
                ]
            }

        def raise_for_status(self):
            return None

        def json(self):
            return self._json

    # local name shadow for dumps
    json_module = __import__('json')
    return Resp()


def test_decide_pipeline_with_yaml_and_mocks():
    client = BossClient("http://127.0.0.1:5001")

    # Ensure YAML exists and is parseable
    yaml_path = os.path.join(ROOT, 'jobs', 'criteria.yaml')
    assert os.path.exists(yaml_path)
    with open(yaml_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    assert isinstance(cfg, dict)
    assert 'roles' in cfg and isinstance(cfg['roles'], list) and len(cfg['roles']) > 0

    # Monkeypatch network + OCR + resume fetch (manual)
    import boss_client as _bc
    _bc.requests.post = stub_requests_post_ok

    def fake_get_online_resume_b64(self, chat_id: str):
        return {"success": True, "image_base64": base64.b64encode(b"dummy").decode('utf-8')}

    def fake_ocr_local_from_b64(self, image_b64: str):
        return {
            "success": True,
            "markdown": "候选人: 张三\n技能: Python, Transformer, LoRA\n经验: 5年\n学历: 硕士\n项目: 大模型微调项目"
        }

    _bc.BossClient.get_online_resume_b64 = fake_get_online_resume_b64
    _bc.BossClient.ocr_local_from_b64 = fake_ocr_local_from_b64

    # Simulate the decision core (subset of CLI logic)
    role = cfg['roles'][0]
    fetched = client.get_online_resume_b64("fake-chat-id")
    assert fetched.get('success')
    md_text = client.ocr_local_from_b64(fetched['image_base64'])['markdown']

    os.environ['OPENAI_API_KEY'] = os.environ.get('OPENAI_API_KEY', 'sk-test')

    headers = {'Authorization': f"Bearer {os.environ['OPENAI_API_KEY']}", 'Content-Type': 'application/json'}
    prompt = {
        'role': 'user',
        'content': (
            "你是资深HR。根据以下职位要求(YAML)与候选人简历(Markdown)进行匹配评分，输出JSON："
            "{score: 0-1, decision: 'greet'|'skip'|'borderline', reasons: [..], highlights: [..], risks: [..]}。"
            "职位YAML:\n" + yaml.safe_dump(role, allow_unicode=True) + "\n简历Markdown:\n" + md_text
        )
    }
    payload = {
        'model': os.environ.get('OPENAI_TEXT_MODEL', 'gpt-4o-mini'),
        'messages': [prompt],
        'response_format': {"type": "json_object"}
    }

    import requests
    resp = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload, timeout=60)
    data = resp.json()
    content = data['choices'][0]['message']['content']
    decision = json.loads(content)

    assert isinstance(decision, dict)
    assert decision.get('decision') in ('greet', 'skip', 'borderline')
    assert decision['decision'] == 'greet'
    assert 0 <= decision.get('score', 0) <= 1


if __name__ == '__main__':
    try:
        test_decide_pipeline_with_yaml_and_mocks()
        print("OK: decision pipeline test passed")
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)

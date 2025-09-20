import json
import os
from typing import Set, Dict

DEFAULT_PATH = os.path.join(os.getcwd(), 'data', 'blacklist.json')

NEGATIVE_HINTS = [
    '不合适', '感谢', '遗憾', '需要本', '对不', '不匹配', '暂不', '不考虑'
]

def load_blacklist(path: str = DEFAULT_PATH) -> Dict[str, Set[str]]:
    try:
        if not os.path.exists(path):
            return { 'blackCompanies': set(), 'blackJobs': set(), 'blackRecruiters': set() }
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return {
            'blackCompanies': set(data.get('blackCompanies', [])),
            'blackJobs': set(data.get('blackJobs', [])),
            'blackRecruiters': set(data.get('blackRecruiters', [])),
        }
    except Exception:
        return { 'blackCompanies': set(), 'blackJobs': set(), 'blackRecruiters': set() }

def save_blacklist(data: Dict[str, Set[str]], path: str = DEFAULT_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        'blackCompanies': sorted(list(data.get('blackCompanies', set()))),
        'blackJobs': sorted(list(data.get('blackJobs', set()))),
        'blackRecruiters': sorted(list(data.get('blackRecruiters', set()))),
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)



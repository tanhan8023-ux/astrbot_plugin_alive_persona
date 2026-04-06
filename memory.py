"""
记忆系统 - 短期记忆 / 长期记忆 / 用户画像

短期记忆: 每个会话最近 N 条消息 (内存)
长期记忆: 重要事件摘要 (JSON 持久化)
用户画像: 好感度/标签/备注 (JSON 持久化)
"""
import os, json, time, math, re
from typing import Optional

IMPORTANT_PATTERNS = [
    re.compile(r'我(叫|是|名字).{1,10}'),
    re.compile(r'我(喜欢|讨厌|爱|恨).{1,20}'),
    re.compile(r'我(在|住).{1,15}'),
    re.compile(r'我(的|)(生日|年龄|工作|学校|专业)'),
    re.compile(r'记住|别忘了|记得'),
    re.compile(r'(以后|下次|明天|后天).{0,10}(要|得|必须)'),
]


class MemorySystem:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.memory_file = os.path.join(data_dir, 'memory.json')
        self.short_term: dict[str, list] = {}  # session_id -> messages
        self.short_term_limit = 50
        self.long_term: list[dict] = []
        self.user_profiles: dict[str, dict] = {}
        self._load()

    # ===== 短期记忆 =====
    def add_message(self, session_id: str, user_id: str, nickname: str, content: str, is_bot: bool = False):
        if session_id not in self.short_term:
            self.short_term[session_id] = []
        msgs = self.short_term[session_id]
        msgs.append({
            'time': time.time(), 'user_id': user_id,
            'nickname': nickname, 'content': content, 'is_bot': is_bot,
        })
        while len(msgs) > self.short_term_limit:
            msgs.pop(0)

    def get_recent(self, session_id: str, limit: int = 20) -> list[dict]:
        return (self.short_term.get(session_id) or [])[-limit:]

    # ===== 长期记忆 =====
    def add_long_term(self, session_id: str, user_id: str, summary: str, importance: float = 0.5):
        self.long_term.append({
            'time': time.time(), 'session_id': session_id,
            'user_id': user_id, 'summary': summary, 'importance': importance,
        })
        if len(self.long_term) > 500:
            self.long_term.sort(key=lambda m: m['importance'], reverse=True)
            self.long_term = self.long_term[:400]
        self._save()

    def search_memories(self, keywords: list[str], user_id: str = None, limit: int = 5) -> list[dict]:
        pool = self.long_term
        if user_id:
            pool = [m for m in pool if m['user_id'] == user_id]
        scored = []
        for m in pool:
            score = m['importance']
            for kw in keywords:
                if kw in m['summary']: score += 0.3
            days = (time.time() - m['time']) / 86400
            score *= math.exp(-days / 30)
            scored.append({**m, 'score': score})
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]

    def should_remember(self, message: str) -> bool:
        return any(p.search(message) for p in IMPORTANT_PATTERNS)

    # ===== 用户画像 =====
    def get_profile(self, user_id: str) -> dict:
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'nickname': None, 'tags': [], 'favorability': 50,
                'notes': [], 'last_seen': time.time(),
                'message_count': 0, 'first_seen': time.time(),
            }
        return self.user_profiles[user_id]

    def update_profile(self, user_id: str, **kwargs):
        p = self.get_profile(user_id)
        p.update(kwargs)
        p['last_seen'] = time.time()
        p['message_count'] = p.get('message_count', 0) + 1
        self._save()

    def adjust_favorability(self, user_id: str, delta: float) -> float:
        p = self.get_profile(user_id)
        p['favorability'] = max(0, min(100, p['favorability'] + delta))
        self._save()
        return p['favorability']

    def add_tag(self, user_id: str, tag: str):
        p = self.get_profile(user_id)
        if tag not in p['tags']:
            p['tags'].append(tag)
            self._save()

    def add_note(self, user_id: str, note: str):
        p = self.get_profile(user_id)
        p['notes'].append({'time': time.time(), 'content': note})
        if len(p['notes']) > 20: p['notes'].pop(0)
        self._save()

    def get_relation(self, user_id: str) -> str:
        fav = self.get_profile(user_id)['favorability']
        if fav >= 80: return 'close_friend'
        if fav >= 60: return 'friend'
        if fav >= 40: return 'acquaintance'
        return 'stranger'

    def get_profile_description(self, user_id: str) -> str:
        p = self.get_profile(user_id)
        parts = []
        if p['nickname']: parts.append(f'这个人叫"{p["nickname"]}"')
        if p['tags']: parts.append(f'你对ta的印象标签: {"、".join(p["tags"])}')
        rel = self.get_relation(user_id)
        rel_desc = {
            'close_friend': '你和ta关系很好，是好朋友',
            'friend': '你和ta比较熟了，算是朋友',
            'acquaintance': '你和ta认识但不太熟',
            'stranger': '你和ta不太熟，还比较陌生',
        }
        parts.append(rel_desc.get(rel, ''))
        if p['favorability'] < 30: parts.append('你对ta印象不太好')
        if p['favorability'] > 70: parts.append('你挺喜欢ta的')
        recent_notes = p['notes'][-3:]
        if recent_notes:
            parts.append(f'你记得关于ta的一些事: {"；".join(n["content"] for n in recent_notes)}')
        return '。'.join(parts) or '你对这个人还没什么印象'

    # ===== 持久化 =====
    def _save(self):
        try:
            data = {'long_term': self.long_term, 'user_profiles': self.user_profiles}
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f'[Memory] 保存失败: {e}')

    def _load(self):
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.long_term = data.get('long_term', [])
                self.user_profiles = data.get('user_profiles', {})
        except Exception as e:
            print(f'[Memory] 加载失败: {e}')

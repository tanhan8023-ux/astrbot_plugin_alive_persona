"""
记忆系统 - 短期记忆 / 长期记忆 / 用户画像

短期记忆: 每个会话最近 N 条消息 (内存)
长期记忆: 重要事件摘要 (JSON 持久化)
用户画像: 好感度/标签/备注 (JSON 持久化)
"""
import json
import math
import os
import re
import time


IMPORTANT_PATTERNS = [
    re.compile(r'我(叫|是|名字).{1,10}'),
    re.compile(r'我(喜欢|讨厌|爱|恨).{1,20}'),
    re.compile(r'我(在|住).{1,15}'),
    re.compile(r'我(的|)(生日|年龄|工作|学校|专业)'),
    re.compile(r'(累|困|睡|熬夜|失眠|不舒服|难受|生病|发烧|头疼|胃疼)'),
    re.compile(r'(开心|难过|伤心|烦|焦虑|崩溃|委屈|压力|emo)'),
    re.compile(r'谢谢|感谢|对不起|抱歉|辛苦了'),
    re.compile(r'记住|别忘了|记得'),
    re.compile(r'(以后|下次|明天|后天).{0,10}(要|得|必须)'),
]

STATUS_PATTERNS = [
    (re.compile(r'(累|疲惫|困|熬夜|没睡|失眠)'), '状态'),
    (re.compile(r'(不舒服|难受|生病|发烧|头疼|胃疼|疼)'), '身体'),
    (re.compile(r'(开心|高兴|难过|伤心|烦|焦虑|崩溃|委屈|压力|emo)'), '心情'),
]

THANKS_PATTERN = re.compile(r'谢谢|感谢|辛苦了')
APOLOGY_PATTERN = re.compile(r'对不起|抱歉|不好意思')


class MemorySystem:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.memory_file = os.path.join(data_dir, 'memory.json')
        self.short_term: dict[str, list] = {}
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
            'time': time.time(),
            'user_id': user_id,
            'nickname': nickname,
            'content': content,
            'is_bot': is_bot,
        })
        while len(msgs) > self.short_term_limit:
            msgs.pop(0)

    def get_recent(self, session_id: str, limit: int = 20) -> list[dict]:
        return (self.short_term.get(session_id) or [])[-limit:]

    def get_recent_context(self, session_id: str, limit: int = 12, exclude_latest: bool = False) -> str:
        messages = self.get_recent(session_id, limit)
        if exclude_latest and messages:
            messages = messages[:-1]
        if not messages:
            return ''

        lines = []
        for msg in messages:
            name = self._safe_name(msg.get('nickname') or msg.get('user_id') or '某人')
            content = self._compact_text(msg.get('content') or '', 80)
            if not content:
                continue
            if msg.get('is_bot'):
                lines.append(f'{name}: {content}')
            else:
                lines.append(f'{name}说: {content}')
        return '\n'.join(lines[-limit:])

    def get_session_atmosphere(self, session_id: str) -> dict:
        messages = self.short_term.get(session_id) or []
        now = time.time()
        recent = [m for m in messages if now - m.get('time', now) <= 60]
        active_users = {
            m.get('user_id') for m in messages
            if not m.get('is_bot') and now - m.get('time', now) <= 300
        }
        message_rate = len(recent)
        latest_text = ''.join(m.get('content', '') for m in messages[-5:])

        if message_rate >= 12:
            mood = '热闹'
            desc = '群里现在比较热闹，别抢话，短一点接住重点就好'
        elif message_rate <= 1:
            mood = '安静'
            desc = '群里比较安静，可以自然回应，但不要硬找话题'
        elif re.search(r'哈哈|笑死|草|绷|乐|hhh|233', latest_text, re.I):
            mood = '轻松'
            desc = '群里气氛比较轻松，能接梗但别刻意'
        else:
            mood = '正常'
            desc = '群里聊天节奏正常'

        return {
            'mood': mood,
            'description': desc,
            'message_rate': message_rate,
            'active_users': len(active_users),
        }

    # ===== 长期记忆 =====
    def add_long_term(self, session_id: str, user_id: str, summary: str, importance: float = 0.5):
        self.long_term.append({
            'time': time.time(),
            'session_id': session_id,
            'user_id': user_id,
            'summary': summary,
            'importance': importance,
        })
        if len(self.long_term) > 500:
            self.long_term.sort(key=lambda m: m['importance'], reverse=True)
            self.long_term = self.long_term[:400]
        self._save()

    def remember_from_message(self, session_id: str, user_id: str, nickname: str, message: str) -> list[str]:
        summaries = self.extract_memory_summaries(nickname, message)
        for item in summaries:
            self.add_long_term(session_id, user_id, item['summary'], item['importance'])
            if item.get('note'):
                self.add_note(user_id, item['note'])
        return [item['summary'] for item in summaries]

    def extract_memory_summaries(self, nickname: str, message: str) -> list[dict]:
        text = self._compact_text(message, 90)
        if not text:
            return []

        who = self._safe_name(nickname) or '对方'
        summaries = []

        name_match = re.search(r'我(叫|是|名字是|名字叫)\s*([^，。！？、；,.!?;\s]{1,10})', message)
        if name_match:
            name = self._clean_value(name_match.group(2))
            if name:
                summaries.append({
                    'summary': f'{who}自我介绍说叫{name}',
                    'importance': 0.85,
                    'note': f'自我介绍说叫"{name}"',
                })

        pref_match = re.search(r'我(喜欢|讨厌|爱|恨)\s*([^，。！？、；,.!?;]{1,24})', message)
        if pref_match:
            action = pref_match.group(1)
            value = self._clean_value(pref_match.group(2))
            if value:
                summaries.append({
                    'summary': f'{who}{action}{value}',
                    'importance': 0.75,
                    'note': f'{action}{value}',
                })

        info_match = re.search(r'我(?:的)?(生日|年龄|工作|学校|专业)[是叫:]?\s*(.{0,24})', message)
        if info_match:
            field = info_match.group(1)
            value = self._clean_value(info_match.group(2))
            content = f'{field}{("是" + value) if value else ""}'
            summaries.append({
                'summary': f'{who}提到自己的{content}',
                'importance': 0.8,
                'note': f'提到自己的{content}',
            })

        for pattern, label in STATUS_PATTERNS:
            if pattern.search(message):
                summaries.append({
                    'summary': f'{who}刚才说自己{label}不太好: {text}',
                    'importance': 0.65,
                    'note': f'最近{label}: {text}',
                })
                break

        if THANKS_PATTERN.search(message):
            summaries.append({
                'summary': f'{who}刚才表达了感谢',
                'importance': 0.45,
                'note': '表达过感谢',
            })
        elif APOLOGY_PATTERN.search(message):
            summaries.append({
                'summary': f'{who}刚才道歉了',
                'importance': 0.5,
                'note': '刚才道歉了',
            })

        if re.search(r'记住|别忘了|记得', message):
            summaries.append({
                'summary': f'{who}希望你记住: {text}',
                'importance': 0.9,
                'note': f'希望记住: {text}',
            })
        elif re.search(r'(以后|下次|明天|后天).{0,10}(要|得|必须)', message):
            summaries.append({
                'summary': f'{who}提到一个之后要注意的事: {text}',
                'importance': 0.75,
                'note': f'之后要注意: {text}',
            })

        deduped = []
        seen = set()
        for item in summaries:
            if item['summary'] not in seen:
                deduped.append(item)
                seen.add(item['summary'])
        return deduped

    def search_memories(self, keywords: list[str], user_id: str = None, limit: int = 5) -> list[dict]:
        pool = self.long_term
        if user_id:
            pool = [m for m in pool if m.get('user_id') == user_id]
        scored = []
        for m in pool:
            score = m.get('importance', 0.5)
            for kw in keywords:
                if kw and kw in m.get('summary', ''):
                    score += 0.3
            days = (time.time() - m.get('time', time.time())) / 86400
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
                'nickname': None,
                'tags': [],
                'favorability': 50,
                'notes': [],
                'last_seen': time.time(),
                'message_count': 0,
                'first_seen': time.time(),
            }
        p = self.user_profiles[user_id]
        p.setdefault('nickname', None)
        p.setdefault('tags', [])
        p.setdefault('favorability', 50)
        p.setdefault('notes', [])
        p.setdefault('last_seen', time.time())
        p.setdefault('message_count', 0)
        p.setdefault('first_seen', time.time())
        return p

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
        if len(p['notes']) > 20:
            p['notes'].pop(0)
        self._save()

    def get_relation(self, user_id: str, is_special: bool = False) -> str:
        if is_special:
            return 'close_friend'
        profile = self.get_profile(user_id)
        fav = profile['favorability']
        if profile.get('message_count', 0) >= 80 and fav >= 50:
            return 'friend'
        if fav >= 80:
            return 'close_friend'
        if fav >= 60:
            return 'friend'
        if fav >= 40:
            return 'acquaintance'
        return 'stranger'

    def get_profile_description(self, user_id: str, special_prompt: str = None) -> str:
        p = self.get_profile(user_id)
        parts = []
        if p['nickname']:
            parts.append(f'这个人叫"{p["nickname"]}"')
        if p['tags']:
            parts.append(f'你对ta的印象标签: {"、".join(p["tags"])}')

        rel = self.get_relation(user_id, bool(special_prompt))
        rel_desc = {
            'close_friend': '你和ta关系很近，说话可以更放松直接',
            'friend': '你和ta比较熟了，算是朋友',
            'acquaintance': '你和ta认识但不太熟',
            'stranger': '你和ta不太熟，还比较陌生',
        }
        parts.append(rel_desc.get(rel, ''))

        count = p.get('message_count', 0)
        if count >= 100:
            parts.append('你们已经聊过很多次，不用像第一次见面那样客气')
        elif count < 5:
            parts.append('你们还没聊过几次，保持一点距离感')

        if p['favorability'] < 30:
            parts.append('你对ta印象不太好')
        if p['favorability'] > 70:
            parts.append('你挺喜欢ta的')

        recent_notes = p['notes'][-3:]
        if recent_notes:
            parts.append(f'你记得关于ta的一些事: {"；".join(n["content"] for n in recent_notes)}')
        if special_prompt:
            parts.append(f'特殊关系: {special_prompt}')

        return '。'.join(parts) or '你对这个人还没什么印象'

    def get_recent_notes_text(self, user_id: str, limit: int = 3) -> str:
        notes = self.get_profile(user_id).get('notes', [])[-limit:]
        return '；'.join(n.get('content', '') for n in notes if n.get('content'))

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
                self.long_term = data.get('long_term', data.get('longTerm', []))
                self.user_profiles = data.get('user_profiles', data.get('userProfiles', {}))
        except Exception as e:
            print(f'[Memory] 加载失败: {e}')

    @staticmethod
    def _safe_name(name: str) -> str:
        return str(name or '').strip().replace('\n', ' ')[:20]

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        text = re.sub(r'\s+', ' ', str(text or '')).strip()
        if len(text) <= limit:
            return text
        return text[:limit - 1] + '…'

    @staticmethod
    def _clean_value(text: str) -> str:
        text = re.sub(r'[，。！？、；：,.!?;:\s]+$', '', str(text or '').strip())
        return text[:24]

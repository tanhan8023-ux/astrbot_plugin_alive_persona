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
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone


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
        self.legacy_backup_file = self.memory_file + '.legacy.bak'
        self._lock = threading.RLock()
        self.short_term: dict[str, list] = {}
        self.short_term_limit = 50
        self.long_term: list[dict] = []
        self.user_profiles: dict[str, dict] = {}
        self._load()

    # ===== 短期记忆 =====
    def add_message(self, session_id: str, user_id: str, nickname: str, content: str, is_bot: bool = False):
        with self._lock:
            if session_id not in self.short_term:
                self.short_term[session_id] = []
            msgs = self.short_term[session_id]
            msgs.append({
                'time': time.time(),
                'user_id': str(user_id),
                'nickname': nickname,
                'content': content,
                'is_bot': is_bot,
            })
            while len(msgs) > self.short_term_limit:
                msgs.pop(0)

    def get_recent(self, session_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            return [dict(item) for item in (self.short_term.get(session_id) or [])[-limit:]]

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
    def add_long_term(
        self,
        session_id: str,
        user_id: str,
        summary: str,
        importance: float = 0.5,
        *,
        keywords: list[str] | None = None,
        source: str = 'astrbot',
    ) -> dict | None:
        """Add or refresh a durable memory and return the canonical record."""
        summary = self._compact_text(summary, 1000)
        if not summary:
            return None
        user_id = str(user_id)
        now = time.time()
        now_iso = self._iso_from_epoch(now)
        normalized = self._normalize_memory_text(summary)
        with self._lock:
            for item in reversed(self.long_term):
                if (
                    str(item.get('user_id')) == user_id
                    and self._normalize_memory_text(item.get('summary', '')) == normalized
                ):
                    item['time'] = now
                    item['updated_at'] = now_iso
                    item['importance'] = max(float(item.get('importance', 0.5)), float(importance))
                    item['keywords'] = self._merge_keywords(item.get('keywords'), keywords)
                    item['revision'] = max(1, int(item.get('revision', 1))) + 1
                    item['source'] = self._normalize_source(source, 'astrbot')
                    self._save()
                    return dict(item)

            record = {
                'id': str(uuid.uuid4()),
                'time': now,
                'created_at': now_iso,
                'updated_at': now_iso,
                'session_id': session_id,
                'user_id': user_id,
                'summary': summary,
                'importance': max(0.0, min(1.0, float(importance))),
                'keywords': self._merge_keywords([], keywords),
                'revision': 1,
                'source': self._normalize_source(source, 'astrbot'),
            }
            self.long_term.append(record)
            if len(self.long_term) > 500:
                self.long_term.sort(key=lambda m: float(m.get('importance', 0.5)), reverse=True)
                self.long_term = self.long_term[:400]
            self._save()
            return dict(record)

    def list_shared(self, user_id: str) -> list[dict]:
        """Return bridge-safe records for one user only."""
        user_id = str(user_id)
        with self._lock:
            return [
                self._record_to_shared(item)
                for item in self.long_term
                if str(item.get('user_id')) == user_id
            ]

    def upsert_shared(self, user_id: str, record: dict) -> tuple[dict | None, bool]:
        """Merge a phone-side record by UUID, then by normalized content."""
        if not isinstance(record, dict):
            return None, False
        user_id = str(user_id)
        incoming_id = str(record.get('id') or '').strip() or str(uuid.uuid4())
        content = self._compact_text(record.get('content') or record.get('summary') or '', 1000)
        if not content:
            return None, False
        normalized = self._normalize_memory_text(content)
        created_iso = self._normalize_iso(record.get('createdAt') or record.get('created_at'))
        updated_iso = self._normalize_iso(record.get('updatedAt') or record.get('updated_at'))
        if not created_iso:
            created_iso = self._iso_from_epoch(time.time())
        if not updated_iso:
            updated_iso = created_iso
        importance = max(0.0, min(1.0, float(record.get('importance', 0.5))))
        incoming_revision = max(1, int(record.get('revision', 1)))
        incoming_source = self._normalize_source(record.get('source'), 'sheshe')
        incoming_keywords = self._merge_keywords([], record.get('keywords'))

        with self._lock:
            existing = next((m for m in self.long_term if str(m.get('user_id')) == user_id and str(m.get('id')) == incoming_id), None)
            if existing is None:
                existing = next((
                    m for m in self.long_term
                    if str(m.get('user_id')) == user_id
                    and self._normalize_memory_text(m.get('summary', '')) == normalized
                ), None)

            if existing is None:
                item = {
                    'id': incoming_id,
                    'time': self._epoch_from_iso(updated_iso),
                    'created_at': created_iso,
                    'updated_at': updated_iso,
                    'session_id': 'sheshe_bridge',
                    'user_id': user_id,
                    'summary': content,
                    'importance': importance,
                    'keywords': incoming_keywords,
                    'revision': incoming_revision,
                    'source': incoming_source,
                }
                self.long_term.append(item)
                self._save()
                return self._record_to_shared(item), True

            before = json.dumps(existing, ensure_ascii=False, sort_keys=True)
            existing_revision = max(1, int(existing.get('revision', 1)))
            if incoming_revision >= existing_revision:
                existing['summary'] = content
                existing['updated_at'] = updated_iso
                existing['time'] = max(float(existing.get('time', 0)), self._epoch_from_iso(updated_iso))
                existing['source'] = incoming_source
            existing.setdefault('created_at', created_iso)
            existing['importance'] = max(float(existing.get('importance', 0.5)), importance)
            existing['keywords'] = self._merge_keywords(existing.get('keywords'), incoming_keywords)
            existing['revision'] = max(existing_revision, incoming_revision)
            after = json.dumps(existing, ensure_ascii=False, sort_keys=True)
            changed = before != after
            if changed:
                self._save()
            return self._record_to_shared(existing), changed

    def delete_shared(self, user_id: str, memory_id: str) -> dict | None:
        user_id = str(user_id)
        memory_id = str(memory_id)
        with self._lock:
            for index, item in enumerate(self.long_term):
                if str(item.get('user_id')) == user_id and str(item.get('id')) == memory_id:
                    removed = self.long_term.pop(index)
                    self._save()
                    return self._record_to_shared(removed)
        return None

    def remember_from_message(self, session_id: str, user_id: str, nickname: str, message: str) -> list[str]:
        summaries = self.extract_memory_summaries(nickname, message)
        for item in summaries:
            self.add_long_term(session_id, user_id, item['summary'], item['importance'])
            if item.get('note'):
                self.add_note(user_id, item['note'])
            if item.get('status_label'):
                self.update_recent_status(user_id, item['status_label'], item.get('status_text') or message)
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
            # 只有出现明确的第一人称时才记录为用户自己的状态。
            if '我' in message and pattern.search(message):
                summaries.append({
                    'summary': f'{who}刚才说自己{label}不太好: {text}',
                    'importance': 0.65,
                    'note': f'最近{label}: {text}',
                    'status_label': label,
                    'status_text': text,
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
        if re.search(r'(以后|下次|明天|后天).{0,10}(要|得|必须)', message):
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
                'recent_status': {},
            }
        p = self.user_profiles[user_id]
        p.setdefault('nickname', None)
        p.setdefault('tags', [])
        p.setdefault('favorability', 50)
        p.setdefault('notes', [])
        p.setdefault('last_seen', time.time())
        p.setdefault('message_count', 0)
        p.setdefault('first_seen', time.time())
        p.setdefault('recent_status', {})
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
        if not note:
            return
        if any(n.get('content') == note for n in p['notes'][-5:]):
            return
        p['notes'].append({'time': time.time(), 'content': note})
        if len(p['notes']) > 20:
            p['notes'].pop(0)
        self._save()

    def update_recent_status(self, user_id: str, label: str, text: str):
        p = self.get_profile(user_id)
        content = self._compact_text(text, 80)
        old = p['recent_status'].get(label, {})
        if old.get('content') == content and time.time() - old.get('time', 0) < 6 * 3600:
            return
        p['recent_status'][label] = {
            'time': time.time(),
            'content': content,
        }
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
        status_text = self.get_recent_status_text(user_id)
        if status_text:
            parts.append(f'ta最近的状态: {status_text}')
        if special_prompt:
            parts.append(f'特殊关系: {special_prompt}')

        return '。'.join(parts) or '你对这个人还没什么印象'

    def get_recent_notes_text(self, user_id: str, limit: int = 3) -> str:
        notes = self.get_profile(user_id).get('notes', [])[-limit:]
        return '；'.join(n.get('content', '') for n in notes if n.get('content'))

    def get_recent_status_text(self, user_id: str, max_age_hours: int = 24) -> str:
        statuses = self.get_profile(user_id).get('recent_status', {})
        now = time.time()
        parts = []
        for label, item in statuses.items():
            if now - item.get('time', 0) <= max_age_hours * 3600:
                parts.append(f'{label}: {item.get("content", "")}')
        return '；'.join(parts)

    def forget_user(self, user_id: str) -> list[str]:
        """删除一个用户的长期记忆、画像和短期消息，并返回被删 UUID。"""
        user_id = str(user_id)
        with self._lock:
            removed_ids = [
                str(m.get('id')) for m in self.long_term
                if str(m.get('user_id')) == user_id and m.get('id')
            ]
            self.long_term = [m for m in self.long_term if str(m.get('user_id')) != user_id]
            self.user_profiles.pop(user_id, None)
            for session_id, messages in list(self.short_term.items()):
                kept = [m for m in messages if str(m.get('user_id')) != user_id]
                if kept:
                    self.short_term[session_id] = kept
                else:
                    self.short_term.pop(session_id, None)
            self._save()
            return removed_ids

    # ===== 持久化 =====
    def _save(self):
        with self._lock:
            try:
                data = {'long_term': self.long_term, 'user_profiles': self.user_profiles}
                temp_file = self.memory_file + '.tmp'
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_file, self.memory_file)
            except Exception as e:
                print(f'[Memory] 保存失败: {type(e).__name__}')

    def _load(self):
        with self._lock:
            try:
                if not os.path.exists(self.memory_file):
                    return
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.long_term = data.get('long_term', data.get('longTerm', []))
                self.user_profiles = data.get('user_profiles', data.get('userProfiles', {}))
                migrated = False
                for item in self.long_term:
                    if not isinstance(item, dict):
                        continue
                    if not item.get('id'):
                        item['id'] = str(uuid.uuid4())
                        migrated = True
                    epoch = float(item.get('time') or time.time())
                    if not item.get('created_at'):
                        item['created_at'] = self._iso_from_epoch(epoch)
                        migrated = True
                    if not item.get('updated_at'):
                        item['updated_at'] = item['created_at']
                        migrated = True
                    if not item.get('revision'):
                        item['revision'] = 1
                        migrated = True
                    if not item.get('source'):
                        item['source'] = 'astrbot'
                        migrated = True
                    if not isinstance(item.get('keywords'), list):
                        item['keywords'] = []
                        migrated = True
                    item['user_id'] = str(item.get('user_id') or '')
                if migrated:
                    if not os.path.exists(self.legacy_backup_file):
                        shutil.copy2(self.memory_file, self.legacy_backup_file)
                    self._save()
            except Exception as e:
                print(f'[Memory] 加载失败: {type(e).__name__}')

    @staticmethod
    def _normalize_memory_text(text: str) -> str:
        return re.sub(r'[\s，。！？、；：,.!?;:]+', '', str(text or '')).lower()

    @staticmethod
    def _normalize_source(value, fallback: str) -> str:
        value = str(value or '').strip().lower()
        return value if value in {'astrbot', 'sheshe'} else fallback

    @staticmethod
    def _merge_keywords(existing, incoming) -> list[str]:
        values = []
        for collection in (existing or [], incoming or []):
            if isinstance(collection, str):
                collection = [collection]
            for value in collection:
                value = re.sub(r'\s+', ' ', str(value or '')).strip()[:40]
                if value and value not in values:
                    values.append(value)
        return values[:30]

    @staticmethod
    def _iso_from_epoch(value: float) -> str:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace('+00:00', 'Z')

    @staticmethod
    def _normalize_iso(value) -> str:
        if value is None:
            return ''
        if isinstance(value, (int, float)):
            return MemorySystem._iso_from_epoch(float(value))
        text = str(value).strip()
        if not text:
            return ''
        try:
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
        except ValueError:
            return ''

    @staticmethod
    def _epoch_from_iso(value: str) -> float:
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except (TypeError, ValueError):
            return time.time()

    def _record_to_shared(self, item: dict) -> dict:
        created = self._normalize_iso(item.get('created_at')) or self._iso_from_epoch(item.get('time', time.time()))
        updated = self._normalize_iso(item.get('updated_at')) or created
        return {
            'id': str(item.get('id') or ''),
            'content': str(item.get('summary') or ''),
            'createdAt': created,
            'updatedAt': updated,
            'importance': max(0.0, min(1.0, float(item.get('importance', 0.5)))),
            'keywords': self._merge_keywords([], item.get('keywords')),
            'revision': max(1, int(item.get('revision', 1))),
            'source': self._normalize_source(item.get('source'), 'astrbot'),
        }

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

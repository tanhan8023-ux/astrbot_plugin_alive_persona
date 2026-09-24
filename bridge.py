"""One-character bridge between AstrBot Alive Persona and the SheShe device."""
import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone


SCHEMA_VERSION = 1
RECENT_LIMIT = 50
INJECT_LIMIT = 12


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _parse_time(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return time.time()


def _stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash_json(value) -> str:
    return hashlib.sha256(_stable_json(value).encode('utf-8')).hexdigest()


def _normalize_text(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip().lower()


def _safe_text(value, limit: int = 1000) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not text or text.startswith('data:'):
        return ''
    if re.match(r'^[A-Za-z]:\\', text) or text.startswith('file://'):
        return ''
    if re.search(r'[A-Za-z0-9+/]{300,}={0,2}', text):
        return ''
    return text if len(text) <= limit else text[: limit - 1] + '…'


class BridgeStore:
    def __init__(self, data_dir, memory, persona, enabled=False, allowed_user_id=''):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, 'sheshe_bridge.json')
        self._lock = threading.RLock()
        self.memory = memory
        self.persona = persona
        self.enabled = bool(enabled)
        self.allowed_user_id = str(allowed_user_id or '').strip()
        self.state = self._default_state()
        self._load()
        self._initialize_persona_state()

    @staticmethod
    def _default_state() -> dict:
        return {
            'schemaVersion': SCHEMA_VERSION,
            'pluginInstanceId': str(uuid.uuid4()),
            'binding': None,
            'revisions': {'persona': 0, 'memory': 0, 'recent': 0},
            'persona': {
                'revision': 0,
                'source': 'astrbot',
                'updatedAt': _utc_now(),
                'data': {},
            },
            'astrbotPersonaHash': '',
            'recentEvents': [],
            'memoryTombstones': {},
        }

    def _load(self):
        with self._lock:
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, 'r', encoding='utf-8') as handle:
                    loaded = json.load(handle)
                if not isinstance(loaded, dict):
                    return
                self.state.update(loaded)
                self.state.setdefault('pluginInstanceId', str(uuid.uuid4()))
                self.state.setdefault('binding', None)
                self.state.setdefault('revisions', {})
                for key in ('persona', 'memory', 'recent'):
                    self.state['revisions'][key] = max(0, int(self.state['revisions'].get(key, 0)))
                self.state.setdefault('persona', {})
                self.state.setdefault('recentEvents', [])
                self.state.setdefault('memoryTombstones', {})
            except Exception:
                # Do not print request payloads, access keys, persona text, or memories.
                self.state = self._default_state()

    def _save(self):
        with self._lock:
            temp_path = self.path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as handle:
                json.dump(self.state, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)

    def _initialize_persona_state(self):
        with self._lock:
            base = self.persona.export_base_persona()
            base_hash = _hash_json(base)
            stored = self.state.get('persona') or {}
            stored_data = stored.get('data') if isinstance(stored.get('data'), dict) else {}
            previous_base_hash = str(self.state.get('astrbotPersonaHash') or '')
            changed = False
            if not stored_data:
                revision = 1 if any(str(v).strip() for v in base.values()) else 0
                self.state['persona'] = {
                    'revision': revision,
                    'source': 'astrbot',
                    'updatedAt': _utc_now(),
                    'data': base,
                }
                self.state['revisions']['persona'] = revision
                stored_data = base
                changed = True
            elif previous_base_hash and previous_base_hash != base_hash:
                revision = max(0, int(self.state['revisions'].get('persona', 0))) + 1
                self.state['persona'] = {
                    'revision': revision,
                    'source': 'astrbot',
                    'updatedAt': _utc_now(),
                    'data': base,
                }
                self.state['revisions']['persona'] = revision
                stored_data = base
                changed = True
            self.state['astrbotPersonaHash'] = base_hash
            self.persona.set_shared_persona(stored_data)
            if changed or not previous_base_hash:
                self._save()

    def set_enabled(self, enabled: bool, allowed_user_id: str):
        with self._lock:
            self.enabled = bool(enabled)
            self.allowed_user_id = str(allowed_user_id or '').strip()

    def participates(self, user_id) -> bool:
        return self.enabled and bool(self.allowed_user_id) and str(user_id) == self.allowed_user_id

    def status(self) -> dict:
        with self._lock:
            binding = self.state.get('binding')
            return {
                'ok': True,
                'schemaVersion': SCHEMA_VERSION,
                'enabled': self.enabled,
                'allowedUserId': self.allowed_user_id,
                'pluginInstanceId': self.state.get('pluginInstanceId', ''),
                'bound': bool(binding),
                'binding': dict(binding) if isinstance(binding, dict) else None,
                'persona': dict((self.state.get('persona') or {}).get('data') or {}),
                'memoryCount': len(self.memory.list_shared(self.allowed_user_id)) if self.allowed_user_id else 0,
                'recentCount': len(self.state.get('recentEvents') or []),
                'revisions': dict(self.state.get('revisions') or {}),
            }

    def sync(self, data: dict) -> dict:
        if not self.enabled:
            return self._error('蛇蛇机互通尚未在插件配置中启用')
        if not isinstance(data, dict):
            return self._error('同步请求格式不正确')
        if int(data.get('schemaVersion', 0) or 0) != SCHEMA_VERSION:
            return self._error('不支持的同步协议版本')
        user_id = str(data.get('userId') or '').strip()
        if not self.allowed_user_id or user_id != self.allowed_user_id:
            return self._error('QQ ID 不在此插件实例的同步白名单中')
        binding_id = str(data.get('bindingId') or '').strip()
        character_id = str(data.get('characterId') or '').strip()
        device_id = str(data.get('deviceId') or '').strip()
        if not binding_id or not character_id or not device_id:
            return self._error('缺少绑定标识、角色 ID 或设备 ID')

        with self._lock:
            existing = self.state.get('binding')
            first_binding = not isinstance(existing, dict)
            if existing and not self._binding_matches(existing, binding_id, character_id, user_id):
                if data.get('replaceBinding') is True:
                    self.state['binding'] = None
                    self.state['recentEvents'] = []
                    self.state['revisions']['recent'] = int(self.state['revisions'].get('recent', 0)) + 1
                    existing = None
                    first_binding = True
                else:
                    return self._error('此插件已绑定其他蛇蛇机角色，请先解除原绑定')

            if not existing:
                self.state['binding'] = {
                    'bindingId': binding_id,
                    'characterId': character_id,
                    'userId': user_id,
                    'deviceId': device_id,
                    'createdAt': _utc_now(),
                }
            else:
                existing['deviceId'] = device_id

            if data.get('unbind') is True:
                self.state['binding'] = None
                self._save()
                return self._response()

            persona_conflict = self._merge_persona(data, first_binding)
            memory_changed = self._merge_memories(data.get('memoryChanges'), user_id)
            recent_changed = False
            if data.get('clearRecent') is True:
                recent_changed = self._clear_recent_locked() or True
            if self._merge_recent(data.get('recentEvents')):
                recent_changed = True
            if memory_changed:
                self.state['revisions']['memory'] = int(self.state['revisions'].get('memory', 0)) + 1
            if recent_changed:
                self.state['revisions']['recent'] = int(self.state['revisions'].get('recent', 0)) + 1
            self._save()
            return self._response(persona_conflict)

    def clear_recent(self, data: dict) -> dict:
        if not self.enabled:
            return self._error('蛇蛇机互通尚未在插件配置中启用')
        if not isinstance(data, dict):
            return self._error('请求格式不正确')
        user_id = str(data.get('userId') or '').strip()
        if user_id != self.allowed_user_id:
            return self._error('QQ ID 不在此插件实例的同步白名单中')
        with self._lock:
            binding = self.state.get('binding')
            if not binding or not self._binding_matches(
                binding,
                str(data.get('bindingId') or ''),
                str(data.get('characterId') or ''),
                user_id,
            ):
                return self._error('绑定信息不匹配')
            self._clear_recent_locked()
            self.state['revisions']['recent'] = int(self.state['revisions'].get('recent', 0)) + 1
            self._save()
            return {
                'ok': True,
                'recentRevision': self.state['revisions']['recent'],
            }

    def _merge_persona(self, data: dict, first_binding: bool):
        change = data.get('personaChange')
        if not isinstance(change, dict) or not isinstance(change.get('persona'), dict):
            return None
        incoming = self._clean_persona(change.get('persona'))
        current_block = self.state.get('persona') or {}
        current = self._clean_persona(current_block.get('data') or {})
        current_revision = int(self.state['revisions'].get('persona', 0))
        base_revision = int(change.get('baseRevision', 0) or 0)
        preference = str(data.get('initialPersonaPreference') or '')

        if first_binding and preference == 'astrbot':
            return None
        if incoming == current:
            return None
        if first_binding and preference == 'sheshe':
            self._apply_persona(incoming, 'sheshe')
            return None
        if base_revision != current_revision:
            return {
                'baseRevision': base_revision,
                'currentRevision': current_revision,
                'incomingPersona': incoming,
                'currentPersona': current,
            }
        self._apply_persona(incoming, 'sheshe')
        return None

    def _apply_persona(self, persona: dict, source: str):
        revision = int(self.state['revisions'].get('persona', 0)) + 1
        self.state['persona'] = {
            'revision': revision,
            'source': source,
            'updatedAt': _utc_now(),
            'data': persona,
        }
        self.state['revisions']['persona'] = revision
        self.persona.set_shared_persona(persona)

    @staticmethod
    def _clean_persona(value: dict) -> dict:
        fields = ('name', 'identity', 'background', 'description', 'systemPrompt', 'customPrompt', 'firstMessage')
        return {field: str(value.get(field) or '')[:20000] for field in fields}

    def _merge_memories(self, changes, user_id: str) -> bool:
        if not isinstance(changes, list):
            return False
        changed = False
        tombstones = self.state.setdefault('memoryTombstones', {})
        for change in changes:
            if not isinstance(change, dict):
                continue
            operation = str(change.get('op') or 'upsert')
            memory_id = str(change.get('id') or '').strip()
            if not memory_id:
                continue
            if operation == 'delete':
                removed = self.memory.delete_shared(user_id, memory_id)
                if removed is not None or memory_id not in tombstones:
                    tombstones[memory_id] = {
                        'id': memory_id,
                        'deletedAt': str(change.get('changedAt') or _utc_now()),
                        'revision': int(self.state['revisions'].get('memory', 0)) + 1,
                    }
                    changed = True
                continue
            if memory_id in tombstones:
                continue
            memory = change.get('memory')
            if not isinstance(memory, dict):
                continue
            memory = dict(memory)
            memory['id'] = memory_id
            canonical, item_changed = self.memory.upsert_shared(user_id, memory)
            if canonical and canonical.get('id') != memory_id:
                tombstones[memory_id] = {
                    'id': memory_id,
                    'deletedAt': _utc_now(),
                    'revision': int(self.state['revisions'].get('memory', 0)) + 1,
                }
                item_changed = True
            changed = changed or item_changed
        return changed

    def _merge_recent(self, events) -> bool:
        if not isinstance(events, list):
            return False
        changed = False
        existing_ids = {str(item.get('id')) for item in self.state.get('recentEvents') or []}
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = str(event.get('id') or '').strip()
            content = _safe_text(event.get('content'))
            if not event_id or not content or event_id in existing_ids:
                continue
            role = 'assistant' if event.get('role') == 'assistant' else 'user'
            self.state['recentEvents'].append({
                'id': event_id,
                'role': role,
                'content': content,
                'timestamp': str(event.get('timestamp') or _utc_now()),
                'source': 'sheshe',
            })
            existing_ids.add(event_id)
            changed = True
        if changed:
            self._trim_recent()
        return changed

    def add_recent(self, user_id, role: str, content: str, event_id: str | None = None, timestamp=None) -> bool:
        if not self.participates(user_id):
            return False
        content = _safe_text(content)
        if not content:
            return False
        event_id = str(event_id or uuid.uuid4())
        with self._lock:
            if any(str(item.get('id')) == event_id for item in self.state.get('recentEvents') or []):
                return False
            self.state['recentEvents'].append({
                'id': event_id,
                'role': 'assistant' if role == 'assistant' else 'user',
                'content': content,
                'timestamp': str(timestamp or _utc_now()),
                'source': 'astrbot',
            })
            self._trim_recent()
            self.state['revisions']['recent'] = int(self.state['revisions'].get('recent', 0)) + 1
            self._save()
            return True

    def note_astrbot_memory_change(self, user_id):
        if not self.participates(user_id):
            return
        with self._lock:
            self.state['revisions']['memory'] = int(self.state['revisions'].get('memory', 0)) + 1
            self._save()

    def note_astrbot_memory_deletions(self, user_id, memory_ids):
        if not self.participates(user_id):
            return
        ids = [str(value) for value in memory_ids if value]
        if not ids:
            return
        with self._lock:
            revision = int(self.state['revisions'].get('memory', 0)) + 1
            for memory_id in ids:
                self.state['memoryTombstones'][memory_id] = {
                    'id': memory_id,
                    'deletedAt': _utc_now(),
                    'revision': revision,
                }
            self.state['revisions']['memory'] = revision
            self._save()

    def hidden_recent_context(self, current_messages) -> str:
        with self._lock:
            visible = {
                _normalize_text(item.get('content'))
                for item in (current_messages or [])
                if _normalize_text(item.get('content'))
            }
            selected = []
            seen = set()
            for event in reversed(self.state.get('recentEvents') or []):
                if event.get('source') != 'sheshe':
                    continue
                normalized = _normalize_text(event.get('content'))
                key = f"{event.get('role')}:{normalized}"
                if not normalized or normalized in visible or key in seen:
                    continue
                seen.add(key)
                selected.append(event)
                if len(selected) >= INJECT_LIMIT:
                    break
            selected.reverse()
        if not selected:
            return ''
        lines = []
        for event in selected:
            speaker = '角色' if event.get('role') == 'assistant' else '用户'
            lines.append(f"{speaker}: {event.get('content')}")
        return (
            '【蛇蛇机共享近期上下文】\n'
            '这是同一个角色在蛇蛇机里最近聊过的内容，只用于接住当前话题；不要逐条复述，也不要声称这些消息出现在 QQ 聊天记录中。\n'
            + '\n'.join(lines)
        )

    def _clear_recent_locked(self) -> bool:
        had_items = bool(self.state.get('recentEvents'))
        self.state['recentEvents'] = []
        return had_items

    def _trim_recent(self):
        events = self.state.get('recentEvents') or []
        events.sort(key=lambda item: _parse_time(item.get('timestamp')))
        self.state['recentEvents'] = events[-RECENT_LIMIT:]

    @staticmethod
    def _binding_matches(binding, binding_id: str, character_id: str, user_id: str) -> bool:
        return (
            str(binding.get('bindingId')) == str(binding_id)
            and str(binding.get('characterId')) == str(character_id)
            and str(binding.get('userId')) == str(user_id)
        )

    def _response(self, persona_conflict=None) -> dict:
        user_id = self.allowed_user_id
        tombstones = list((self.state.get('memoryTombstones') or {}).values())
        return {
            'ok': True,
            'schemaVersion': SCHEMA_VERSION,
            'revisions': dict(self.state.get('revisions') or {}),
            'persona': dict((self.state.get('persona') or {}).get('data') or {}),
            'memories': self.memory.list_shared(user_id),
            'recentEvents': [dict(item) for item in self.state.get('recentEvents') or []],
            'memoryTombstones': tombstones,
            'personaConflict': persona_conflict,
        }

    @staticmethod
    def _error(message: str) -> dict:
        return {'ok': False, 'error': message}

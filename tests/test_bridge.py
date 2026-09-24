import json
from pathlib import Path
import uuid
import os
from concurrent.futures import ThreadPoolExecutor

from bridge import BridgeStore
from memory import MemorySystem
from persona import PersonaEngine


def make_test_dir():
    root = Path(__file__).resolve().parents[1] / '.test-data'
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / str(uuid.uuid4())
    data_dir.mkdir()
    return str(data_dir)


def make_store(enabled=True, user_id="10001"):
    data_dir = make_test_dir()
    memory = MemorySystem(data_dir)
    persona = PersonaEngine(data_dir)
    store = BridgeStore(data_dir, memory, persona, enabled=enabled, allowed_user_id=user_id)
    return data_dir, memory, persona, store


def base_request(**updates):
    data = {
        "schemaVersion": 1,
        "deviceId": "device-1",
        "bindingId": "binding-1",
        "characterId": "character-1",
        "userId": "10001",
        "knownRevisions": {"persona": 0, "memory": 0, "recent": 0},
        "memoryChanges": [],
        "recentEvents": [],
    }
    data.update(updates)
    return data


def memory_change(memory_id="memory-1", content="用户喜欢夜晚", importance=0.5, keywords=None):
    return {
        "op": "upsert",
        "id": memory_id,
        "changedAt": "2026-09-24T12:00:00Z",
        "memory": {
            "id": memory_id,
            "content": content,
            "createdAt": "2026-09-24T11:00:00Z",
            "updatedAt": "2026-09-24T12:00:00Z",
            "importance": importance,
            "keywords": keywords or [],
            "revision": 1,
            "source": "sheshe",
        },
    }


def recent_event(event_id="event-1", role="user", content="刚聊到夜晚"):
    return {
        "id": event_id,
        "role": role,
        "content": content,
        "timestamp": "2026-09-24T12:00:00Z",
        "source": "sheshe",
    }


def test_legacy_memory_is_backed_up_and_migrated_once():
    data_dir = make_test_dir()
    legacy = {
        "long_term": [
            {
                "time": 1000,
                "session_id": "s",
                "user_id": "10001",
                "summary": "旧记忆",
                "importance": 0.7,
            }
        ],
        "user_profiles": {},
    }
    memory_path = os.path.join(data_dir, "memory.json")
    with open(memory_path, "w", encoding="utf-8") as handle:
        json.dump(legacy, handle, ensure_ascii=False)

    memory = MemorySystem(data_dir)
    first_id = memory.long_term[0]["id"]
    assert os.path.exists(memory_path + ".legacy.bak")
    assert memory.long_term[0]["revision"] == 1
    assert memory.long_term[0]["source"] == "astrbot"

    memory_again = MemorySystem(data_dir)
    assert memory_again.long_term[0]["id"] == first_id


def test_disabled_and_wrong_user_are_rejected():
    _, _, _, disabled = make_store(enabled=False)
    assert not disabled.sync(base_request())["ok"]

    _, _, _, store = make_store()
    response = store.sync(base_request(userId="someone-else"))
    assert not response["ok"]
    assert store.status()["memoryCount"] == 0


def test_first_sync_merges_persona_memory_and_recent():
    _, memory, persona, store = make_store()
    phone_persona = {
        "name": "同一个人",
        "identity": "蛇蛇机与 AstrBot 共用的身份",
        "background": "共同背景",
        "description": "共同描述",
        "systemPrompt": "保持身份一致",
        "customPrompt": "记住两边发生的事",
        "firstMessage": "你好",
    }
    response = store.sync(base_request(
        initialPersonaPreference="sheshe",
        personaChange={"baseRevision": 0, "persona": phone_persona, "source": "sheshe"},
        memoryChanges=[memory_change()],
        recentEvents=[recent_event()],
    ))

    assert response["ok"]
    assert response["persona"]["name"] == "同一个人"
    assert persona.get_name() == "同一个人"
    assert len(memory.list_shared("10001")) == 1
    assert response["recentEvents"][0]["source"] == "sheshe"
    assert "蛇蛇机共享近期上下文" in store.hidden_recent_context([])


def test_memory_content_dedup_merges_importance_keywords_and_tombstones_alias():
    _, memory, _, store = make_store()
    first = store.sync(base_request(memoryChanges=[
        memory_change("memory-a", importance=0.4, keywords=["夜晚"]),
        memory_change("memory-b", importance=0.9, keywords=["安静"]),
    ]))

    assert first["ok"]
    records = memory.list_shared("10001")
    assert len(records) == 1
    assert records[0]["importance"] == 0.9
    assert set(records[0]["keywords"]) == {"夜晚", "安静"}
    assert any(item["id"] == "memory-b" for item in first["memoryTombstones"])


def test_tombstone_prevents_offline_memory_resurrection():
    _, memory, _, store = make_store()
    store.sync(base_request(memoryChanges=[memory_change()]))
    deleted = store.sync(base_request(memoryChanges=[{
        "op": "delete",
        "id": "memory-1",
        "changedAt": "2026-09-24T13:00:00Z",
    }]))
    assert deleted["memories"] == []

    resurrect = store.sync(base_request(memoryChanges=[memory_change()]))
    assert resurrect["memories"] == []
    assert memory.list_shared("10001") == []


def test_recent_is_deduplicated_and_capped_at_50():
    _, _, _, store = make_store()
    events = [recent_event(f"e-{index}", content=f"消息 {index}") for index in range(60)]
    events.append(recent_event("e-59", content="重复"))
    response = store.sync(base_request(recentEvents=events))
    assert len(response["recentEvents"]) == 50
    assert len({item["id"] for item in response["recentEvents"]}) == 50


def test_persona_conflict_does_not_block_memory_sync():
    _, memory, _, store = make_store()
    initial = store.sync(base_request(initialPersonaPreference="astrbot"))
    base_revision = initial["revisions"]["persona"]
    with store._lock:
        store._apply_persona({**initial["persona"], "name": "AstrBot 新版"}, "astrbot")
        store._save()

    response = store.sync(base_request(
        personaChange={
            "baseRevision": base_revision,
            "persona": {**initial["persona"], "name": "蛇蛇机新版"},
        },
        memoryChanges=[memory_change()],
    ))
    assert response["personaConflict"] is not None
    assert response["persona"]["name"] == "AstrBot 新版"
    assert len(memory.list_shared("10001")) == 1


def test_clear_recent_and_unbind_keep_long_term_memory():
    _, memory, _, store = make_store()
    store.sync(base_request(memoryChanges=[memory_change()], recentEvents=[recent_event()]))
    cleared = store.clear_recent(base_request())
    assert cleared["ok"]
    assert store.status()["recentCount"] == 0
    assert len(memory.list_shared("10001")) == 1

    unbound = store.sync(base_request(unbind=True))
    assert unbound["ok"]
    assert not store.status()["bound"]
    assert len(memory.list_shared("10001")) == 1


def test_hidden_context_uses_only_phone_events_and_deduplicates_current_chat():
    _, _, _, store = make_store()
    store.sync(base_request(recentEvents=[
        recent_event("phone-1", content="同一句话"),
        recent_event("phone-2", role="assistant", content="只有手机有"),
    ]))
    store.add_recent("10001", "user", "QQ 里的话", event_id="qq-1")
    context = store.hidden_recent_context([{"content": "同一句话"}])
    assert "同一句话" not in context
    assert "只有手机有" in context
    assert "QQ 里的话" not in context


def test_concurrent_atomic_writes_keep_json_valid():
    data_dir, memory, _, store = make_store()
    store.sync(base_request())

    def write(index):
        memory.add_long_term("s", "10001", f"并发记忆 {index}")
        store.add_recent("10001", "user", f"并发消息 {index}", event_id=f"parallel-{index}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(40)))

    with open(os.path.join(data_dir, "memory.json"), "r", encoding="utf-8") as handle:
        json.load(handle)
    with open(os.path.join(data_dir, "sheshe_bridge.json"), "r", encoding="utf-8") as handle:
        json.load(handle)


def test_phone_persona_overlay_survives_restart_without_rewriting_persona_file():
    data_dir = make_test_dir()
    persona_path = os.path.join(data_dir, "persona.json")
    with open(persona_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "AstrBot 原版", "identity": "原身份"}, handle, ensure_ascii=False)

    memory = MemorySystem(data_dir)
    persona = PersonaEngine(data_dir)
    store = BridgeStore(data_dir, memory, persona, enabled=True, allowed_user_id="10001")
    response = store.sync(base_request(
        initialPersonaPreference="sheshe",
        personaChange={
            "baseRevision": 0,
            "persona": {"name": "蛇蛇机版本", "identity": "共享身份"},
        },
    ))
    assert response["persona"]["name"] == "蛇蛇机版本"

    restarted_memory = MemorySystem(data_dir)
    restarted_persona = PersonaEngine(data_dir)
    restarted = BridgeStore(
        data_dir, restarted_memory, restarted_persona, enabled=True, allowed_user_id="10001"
    )
    assert restarted.status()["persona"]["name"] == "蛇蛇机版本"
    assert restarted_persona.get_name() == "蛇蛇机版本"
    with open(persona_path, "r", encoding="utf-8") as handle:
        assert json.load(handle)["name"] == "AstrBot 原版"


def test_manual_astrbot_persona_edit_creates_revision_and_phone_conflict():
    data_dir = make_test_dir()
    persona_path = os.path.join(data_dir, "persona.json")
    with open(persona_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "AstrBot 原版"}, handle, ensure_ascii=False)

    memory = MemorySystem(data_dir)
    persona = PersonaEngine(data_dir)
    store = BridgeStore(data_dir, memory, persona, enabled=True, allowed_user_id="10001")
    initial = store.sync(base_request(initialPersonaPreference="astrbot"))
    phone_base_revision = initial["revisions"]["persona"]

    with open(persona_path, "w", encoding="utf-8") as handle:
        json.dump({"name": "AstrBot 人工新版"}, handle, ensure_ascii=False)

    restarted_memory = MemorySystem(data_dir)
    restarted_persona = PersonaEngine(data_dir)
    restarted = BridgeStore(
        data_dir, restarted_memory, restarted_persona, enabled=True, allowed_user_id="10001"
    )
    assert restarted.status()["persona"]["name"] == "AstrBot 人工新版"
    assert restarted.status()["revisions"]["persona"] > phone_base_revision

    response = restarted.sync(base_request(personaChange={
        "baseRevision": phone_base_revision,
        "persona": {"name": "蛇蛇机离线新版"},
    }))
    assert response["personaConflict"] is not None
    assert response["persona"]["name"] == "AstrBot 人工新版"

import json
from pathlib import Path
import uuid

from living_state import LivingState
from memory import MemorySystem
from persona import PersonaEngine
from persona_style import PersonaStyleState
from personalization import match_special_user, special_prompt_text
from random_behavior import RandomBehavior


def make_test_dir():
    root = Path(__file__).resolve().parents[1] / '.test-data'
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / str(uuid.uuid4())
    data_dir.mkdir()
    return str(data_dir)


def test_memory_extracts_companion_status_and_social_events():
    memory = MemorySystem(make_test_dir())

    summaries = memory.extract_memory_summaries("亖", "我有点累，今晚可能早点睡，谢谢你")
    text = "\n".join(item["summary"] for item in summaries)

    assert "状态不太好" in text
    assert "表达了感谢" in text
    assert memory.should_remember("我有点累，今晚可能早点睡")


def test_memory_extracts_nickname_preference_and_plan():
    memory = MemorySystem(make_test_dir())

    summaries = memory.extract_memory_summaries("群友", "我叫小林，我喜欢夜晚，明天得记得带伞")
    text = "\n".join(item["summary"] for item in summaries)

    assert "自我介绍说叫小林" in text
    assert "喜欢夜晚" in text
    assert "之后要注意" in text


def test_special_user_matches_id_name_nickname_and_alias():
    special_users = {
        "亖": {
            "user_id": "1001",
            "nickname": "亖",
            "aliases": ["主人"],
            "attitude": "对亖绝对温柔",
        }
    }

    assert match_special_user(special_users, "1001", "别人")["key"] == "亖"
    assert match_special_user(special_users, "2002", "主人")["key"] == "亖"
    assert match_special_user(special_users, "2002", "路人", "亖")["key"] == "亖"
    assert match_special_user(special_users, "2002", "路人") is None
    assert "绝对温柔" in special_prompt_text(match_special_user(special_users, "1001", "别人"))


def test_random_behavior_filters_template_tail_and_soft_limits():
    text = "url末尾加/v1，密钥填一串英文数字，模型名照后台写。如果还有问题可以再问我。"
    cleaned = RandomBehavior.clean_reply(text)

    assert "再问我" not in cleaned
    assert "/v1" in cleaned

    limited = RandomBehavior.soft_limit("第一句很重要。第二句也还行。第三句不该留下。", 12)
    assert limited == "第一句很重要。"


def test_random_behavior_deduplicates_repeated_meaning():
    text = "知道了。知道了没问题。"

    assert RandomBehavior.deduplicate(text) == "知道了。"


def test_recent_status_is_structured_and_described():
    memory = MemorySystem(make_test_dir())
    memory.remember_from_message("s", "u", "小林", "我今天有点累")

    profile_text = memory.get_profile_description("u")
    assert "ta最近的状态" in profile_text
    assert "状态" in memory.get_recent_status_text("u")


def test_private_persona_takes_precedence():
    data_dir = make_test_dir()
    with open(f"{data_dir}/persona.json", "w", encoding="utf-8") as f:
        json.dump({"name": "公开"}, f, ensure_ascii=False)
    with open(f"{data_dir}/persona_private.json", "w", encoding="utf-8") as f:
        json.dump({"name": "私有"}, f, ensure_ascii=False)

    persona = PersonaEngine(data_dir)
    assert persona.get_name() == "私有"
    assert persona.loaded_from.endswith("persona_private.json")


def test_configured_persona_file_takes_precedence():
    data_dir = make_test_dir()
    with open(f"{data_dir}/persona.json", "w", encoding="utf-8") as f:
        json.dump({"name": "公开"}, f, ensure_ascii=False)
    with open(f"{data_dir}/persona_private.json", "w", encoding="utf-8") as f:
        json.dump({"name": "私有"}, f, ensure_ascii=False)
    with open(f"{data_dir}/persona_nne_2477.json", "w", encoding="utf-8") as f:
        json.dump({"name": "诺奈"}, f, ensure_ascii=False)

    persona = PersonaEngine(data_dir, config={"persona_file": "persona_nne_2477.json"})
    assert persona.get_name() == "诺奈"
    assert persona.loaded_from.endswith("persona_nne_2477.json")


def test_living_state_light_reply_skips_requests_and_special_users():
    state = LivingState()
    atmosphere = {"mood": "热闹"}
    state._random = lambda chance: True

    assert not state.should_light_reply("怎么配置api", "stranger", atmosphere, False, 1.0)
    assert not state.should_light_reply("随便说句话", "stranger", atmosphere, True, 1.0)
    assert state.should_light_reply("随便说句话", "stranger", atmosphere, False, 1.0)


def test_persona_style_keeps_technical_replies_low_anchor():
    style = PersonaStyleState(trait_anchor_rate=0.0)
    decision = style.decide("s", "api怎么配置", "stranger", {"mood": "正常"}, False)

    assert decision["intent"] == "technical"
    assert decision["mode"] == "答题优先，低显性人设"
    assert not decision["anchor"]


def test_persona_style_allows_identity_only_when_asked():
    style = PersonaStyleState(trait_anchor_rate=1.0, identity_mention_policy="never")

    asked = style.decide("s1", "你是谁", "stranger", {"mood": "正常"}, False)
    assert asked["allow_identity_mention"]
    assert asked["intent"] == "identity"
    assert asked["catchphrase_needs_content"]
    assert not asked["catchphrase_only_allowed"]

    not_asked = style.decide("s2", "今天天气不错", "stranger", {"mood": "正常"}, False)
    assert not not_asked["allow_identity_mention"]


def test_persona_style_classifies_identity_questions_before_other_intents():
    assert PersonaStyleState.classify_intent("你叫什么") == "identity"
    assert PersonaStyleState.classify_intent("你的身份是什么") == "identity"
    assert PersonaStyleState.classify_intent("你是什么模型") == "identity"
    assert PersonaStyleState.classify_intent("你能做什么") == "identity"
    assert PersonaStyleState.classify_intent("这个怎么配置") == "technical"
    assert PersonaStyleState.classify_intent("我今天有点难受") == "emotional"
    assert PersonaStyleState.classify_intent("谢谢你") == "acknowledgement"
    assert PersonaStyleState.classify_intent("晚安") == "social"
    assert PersonaStyleState.classify_intent("去吧") == "social"
    assert PersonaStyleState.classify_intent("你今天怎么样") == "question"


def test_catchphrase_only_is_allowed_only_for_natural_short_replies():
    assert PersonaStyleState.catchphrase_policy("social")["standalone_allowed"]
    assert PersonaStyleState.catchphrase_policy("acknowledgement")["standalone_allowed"]
    assert not PersonaStyleState.catchphrase_policy("identity")["standalone_allowed"]
    assert not PersonaStyleState.catchphrase_policy("technical")["standalone_allowed"]
    assert not PersonaStyleState.catchphrase_policy("emotional")["standalone_allowed"]
    assert not PersonaStyleState.catchphrase_policy("question")["standalone_allowed"]


def test_standalone_catchphrase_accepts_punctuation_but_not_real_content():
    phrases = ["嗯", "好呀"]

    assert RandomBehavior.is_standalone_catchphrase("好呀", phrases)
    assert RandomBehavior.is_standalone_catchphrase("嗯。", phrases)
    assert RandomBehavior.is_standalone_catchphrase("嗯，", phrases)
    assert RandomBehavior.is_standalone_catchphrase(" 嗯\n", phrases)
    assert RandomBehavior.is_standalone_catchphrase("嗯，好呀", phrases)
    assert not RandomBehavior.is_standalone_catchphrase("好呀，我是系尔", phrases)


def test_catchphrase_cooldown_removes_reused_phrase_edges():
    text = RandomBehavior.reduce_catchphrase("嗯，好呀", ["嗯"])

    assert text == "好呀"

    assert RandomBehavior.contains_catchphrase("嗯，好呀", ["嗯"])


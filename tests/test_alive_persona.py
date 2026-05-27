import tempfile

from memory import MemorySystem
from personalization import match_special_user, special_prompt_text
from random_behavior import RandomBehavior


def test_memory_extracts_companion_status_and_social_events():
    memory = MemorySystem(tempfile.mkdtemp())

    summaries = memory.extract_memory_summaries("亖", "我有点累，今晚可能早点睡，谢谢你")
    text = "\n".join(item["summary"] for item in summaries)

    assert "状态不太好" in text
    assert "表达了感谢" in text
    assert memory.should_remember("我有点累，今晚可能早点睡")


def test_memory_extracts_nickname_preference_and_plan():
    memory = MemorySystem(tempfile.mkdtemp())

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

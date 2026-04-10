"""
AstrBot 活人感插件 - 主入口

整合情绪系统、记忆系统、人设引擎、随机行为，
通过 AstrBot 的 LLM 钩子注入活人感 system prompt。

功能:
  1. 拦截 LLM 请求，注入人设+情绪+记忆+上下文的 system prompt
  2. 拦截 LLM 回复，用随机行为修饰
  3. 记录对话到记忆系统
  4. 根据对话更新情绪和用户画像
  5. /persona 命令查看/切换人设
  6. /mood 命令查看当前心情
  7. /memory 命令查看对某人的记忆
"""
import os
import re
import random
import asyncio
import logging

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core.star.register import (
    register_command,
    register_on_llm_request,
    register_on_llm_response,
    register_after_message_sent,
)

from .emotion import EmotionSystem
from .memory import MemorySystem
from .persona import PersonaEngine
from .random_behavior import RandomBehavior

logger = logging.getLogger("alive_persona")


class AlivePersonaPlugin(Star):
    """活人感人设插件 - 让你的 bot 像真人一样聊天

    /persona - 查看当前人设信息
    /mood - 查看当前心情状态
    /memory <@某人> - 查看对某人的记忆
    /favorability <@某人> - 查看对某人的好感度
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)

        # 数据目录
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(plugin_dir, 'data')
        os.makedirs(self.data_dir, exist_ok=True)

        # 初始化子系统
        self.emotion = EmotionSystem()
        self.memory = MemorySystem(self.data_dir)
        self.persona = PersonaEngine(self.data_dir)
        self.random_behavior = RandomBehavior()

        # 设置情绪基线
        self.emotion.set_baseline(self.persona.get_emotion_baseline())

        # 好感度开关 (persona.json 中设置 "enable_favorability": false 可关闭)
        self.enable_favorability = self.persona.persona.get('enable_favorability', True)

        logger.info(f"[AlivePersona] 已加载人设: {self.persona.get_name()}")
        logger.info(f"[AlivePersona] 好感度系统: {'开启' if self.enable_favorability else '关闭'}")

    async def initialize(self):
        logger.info("[AlivePersona] 插件已激活")

    async def terminate(self):
        logger.info("[AlivePersona] 插件已停用")

    # ==================== LLM 钩子 ====================

    @register_on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, request):
        """在 LLM 请求发出前，注入活人感 system prompt"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        session_id = event.unified_msg_origin
        message_text = event.get_message_str()

        # 更新记忆
        self.memory.add_message(session_id, user_id, user_name, message_text, is_bot=False)
        self.memory.update_profile(user_id, nickname=user_name)

        # 更新情绪
        relation = self.memory.get_relation(user_id)
        self.emotion.update_from_message(message_text, relation)

        # 更新好感度 (可通过 persona.json 关闭)
        if self.enable_favorability:
            self._process_favorability(user_id, message_text)

        # 检查是否需要记住
        if self.memory.should_remember(message_text):
            self.memory.add_long_term(session_id, user_id, f"{user_name}说: {message_text}", 0.7)

        # 检查昵称自我介绍
        name_match = re.search(r'我(叫|是|名字是|名字叫)\s*(.{1,10})', message_text)
        if name_match:
            name = name_match.group(2).strip()
            self.memory.update_profile(user_id, nickname=name)
            self.memory.add_note(user_id, f'自我介绍说叫"{name}"')

        # 构建活人感 system prompt
        mood_desc = self.emotion.get_mood_description()
        user_desc = self.memory.get_profile_description(user_id)

        # 搜索相关记忆
        keywords = self._extract_keywords(message_text)
        relevant = self.memory.search_memories(keywords, user_id, limit=3)
        memory_text = ''
        if relevant:
            memory_lines = [f'- {m["summary"]}' for m in relevant if m.get('score', 0) > 0.1]
            if memory_lines:
                memory_text = '\n\n【你的相关记忆（可以自然地引用，但不要刻意提起）】\n' + '\n'.join(memory_lines)

        alive_prompt = self.persona.build_system_prompt(
            mood_desc=mood_desc,
            user_desc=user_desc,
        ) + memory_text

        # 注入到 system prompt
        if hasattr(request, 'system_prompt') and request.system_prompt:
            request.system_prompt = alive_prompt + '\n\n---\n以下是补充设定（如果和上面冲突，以上面为准，不要因为下面的内容改变你的说话风格或重复回答）:\n' + request.system_prompt
        elif hasattr(request, 'system_prompt'):
            request.system_prompt = alive_prompt

    @register_on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response):
        """在 LLM 回复后，用随机行为修饰"""
        if not hasattr(response, 'completion_text') or not response.completion_text:
            return

        session_id = event.unified_msg_origin
        mood = self.emotion.get_mood()
        original = response.completion_text

        # 随机行为修饰
        modified = self.random_behavior.modify_reply(original, mood)

        if isinstance(modified, list):
            # 分多条发送: 全部通过 send 按顺序手动发出，避免乱序
            response.completion_text = ""
            for i, part in enumerate(modified):
                try:
                    if i > 0:
                        await asyncio.sleep(0.5 + random.random())
                    result = MessageEventResult().message(part)
                    await event.send(result)
                except Exception:
                    pass
        else:
            response.completion_text = modified

    @register_after_message_sent()
    async def after_sent(self, event: AstrMessageEvent):
        """消息发送后，记录 bot 的回复到记忆"""
        # 记录 bot 回复到短期记忆
        session_id = event.unified_msg_origin
        if hasattr(event, 'get_result') and event.get_result():
            result = event.get_result()
            if hasattr(result, 'chain') and result.chain:
                bot_text = ''.join(
                    seg.text for seg in result.chain
                    if hasattr(seg, 'text') and seg.text
                )
                if bot_text:
                    self.memory.add_message(
                        session_id, 'bot',
                        self.persona.get_name(), bot_text, is_bot=True
                    )

    # ==================== 命令 ====================

    @register_command("persona", alias={"人设"})
    async def cmd_persona(self, event: AstrMessageEvent):
        """查看当前人设信息"""
        p = self.persona.persona
        name = p.get('name', '未设置')
        identity = p.get('identity', '未设置')
        personality = '、'.join(p.get('personality', [])[:3]) or '未设置'
        mood = self.emotion.get_mood()
        mood_cn = {
            'ecstatic': '狂喜', 'excited': '兴奋', 'content': '满足',
            'happy': '开心', 'neutral': '平静', 'sleepy': '困倦',
            'bored': '无聊', 'anxious': '焦虑', 'angry': '生气',
            'sad': '难过', 'upset': '沮丧',
        }
        info = (
            f"当前人设: {name}\n"
            f"身份: {identity}\n"
            f"性格: {personality}\n"
            f"当前心情: {mood_cn.get(mood, mood)}\n"
            f"人设文件: data/persona.json (可自行编辑)"
        )
        yield event.plain_result(info)

    @register_command("mood", alias={"心情", "情绪"})
    async def cmd_mood(self, event: AstrMessageEvent):
        """查看当前心情"""
        mood = self.emotion.get_mood()
        desc = self.emotion.get_mood_description()
        v = self.emotion.current['valence']
        a = self.emotion.current['arousal']
        intensity = self.emotion.get_intensity()
        mood_cn = {
            'ecstatic': '狂喜', 'excited': '兴奋', 'content': '满足',
            'happy': '开心', 'neutral': '平静', 'sleepy': '困倦',
            'bored': '无聊', 'anxious': '焦虑', 'angry': '生气',
            'sad': '难过', 'upset': '沮丧',
        }
        info = (
            f"心情: {mood_cn.get(mood, mood)}\n"
            f"正负值: {v:.2f} | 激活度: {a:.2f}\n"
            f"波动强度: {intensity:.2f}\n"
            f"{desc}"
        )
        yield event.plain_result(info)

    @register_command("memory", alias={"记忆"})
    async def cmd_memory(self, event: AstrMessageEvent):
        """查看对某人的记忆"""
        user_id = event.get_sender_id()
        desc = self.memory.get_profile_description(user_id)
        profile = self.memory.get_profile(user_id)
        fav = profile['favorability']
        count = profile.get('message_count', 0)
        rel = self.memory.get_relation(user_id)
        rel_cn = {
            'close_friend': '好朋友', 'friend': '朋友',
            'acquaintance': '认识', 'stranger': '陌生人',
        }
        parts = [f"关于你的记忆:\n{desc}\n"]
        if self.enable_favorability:
            parts.append(f"好感度: {fav}/100")
            parts.append(f"关系: {rel_cn.get(rel, rel)}")
        parts.append(f"互动次数: {count}")
        info = '\n'.join(parts)
        yield event.plain_result(info)

    @register_command("favorability", alias={"好感度"})
    async def cmd_favorability(self, event: AstrMessageEvent):
        """查看好感度"""
        if not self.enable_favorability:
            yield event.plain_result("好感度系统已关闭")
            return
        user_id = event.get_sender_id()
        profile = self.memory.get_profile(user_id)
        fav = profile['favorability']
        bar_len = int(fav / 5)
        bar = '█' * bar_len + '░' * (20 - bar_len)
        yield event.plain_result(f"好感度: [{bar}] {fav}/100")

    # ==================== 内部方法 ====================

    def _process_favorability(self, user_id: str, message: str):
        """根据消息内容调整好感度"""
        msg = message.lower()
        positive = re.search(r'谢谢|感谢|爱你|喜欢你|好棒|厉害|可爱|真好|不错|666|nice|哈哈|笑死', msg)
        negative = re.search(r'滚|闭嘴|傻|笨|蠢|垃圾|废物|讨厌|烦死|恶心', msg)

        if positive:
            delta = 1 + random.random() * 2
            self.memory.adjust_favorability(user_id, delta)
            self.emotion.trigger_event('praised')
        elif negative:
            delta = -(2 + random.random() * 3)
            self.memory.adjust_favorability(user_id, delta)
            self.emotion.trigger_event('scolded')
        else:
            self.memory.adjust_favorability(user_id, 0.1)

    def _extract_keywords(self, text: str) -> list[str]:
        clean = re.sub(r'[，。！？、；：""''（）\[\]{},.!?;:\'"()\s]', '', text)
        keywords = []
        if len(clean) >= 2:
            for length in range(min(6, len(clean)), 1, -1):
                for i in range(len(clean) - length + 1):
                    keywords.append(clean[i:i+length])
                if len(keywords) > 10:
                    break
        return keywords[:10]

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
import logging

from astrbot.api.star import Context, Star
from astrbot.api.event import AstrMessageEvent
from astrbot.core.agent.message import TextPart
from astrbot.core.star.register import (
    register_command,
    register_on_llm_request,
    register_on_llm_response,
    register_after_message_sent,
)

from .emotion import EmotionSystem
from .memory import MemorySystem
from .persona import PersonaEngine
from .personalization import match_special_user, special_prompt_text
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
        self.behavior_config = {
            'companion_mode': self.persona.persona.get('companion_mode', True),
            'max_reply_chars': int(self.persona.persona.get('max_reply_chars', 60)),
            'short_reply_rate': float(self.persona.persona.get('short_reply_rate', 0.06)),
            'repeat_rate': float(self.persona.persona.get('repeat_rate', 0.03)),
            'recent_context_limit': int(self.persona.persona.get('recent_context_limit', 12)),
            'template_tail_filter': bool(self.persona.persona.get('template_tail_filter', True)),
        }
        self.last_reply_strategy: dict[str, str] = {}

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
        try:
            user_id = event.get_sender_id()
            user_name = event.get_sender_name()
            session_id = event.unified_msg_origin
            message_text = event.get_message_str()

            # 更新记忆
            self.memory.add_message(session_id, user_id, user_name, message_text, is_bot=False)
            self.memory.update_profile(user_id, nickname=user_name)

            special = self._match_special_user(user_id, user_name)
            special_prompt = special_prompt_text(special)

            # 更新情绪
            relation = self.memory.get_relation(user_id, bool(special))
            self.emotion.update_from_message(message_text, relation)

            # 更新好感度 (可通过 persona.json 关闭)
            if self.enable_favorability:
                self._process_favorability(user_id, message_text)

            # 检查昵称自我介绍
            name_match = re.search(r'我(叫|是|名字是|名字叫)\s*([^，。！？、；,.!?;\s]{1,10})', message_text)
            if name_match:
                name = name_match.group(2).strip()
                self.memory.update_profile(user_id, nickname=name)

            # 检查是否需要记住
            if self.memory.should_remember(message_text):
                self.memory.remember_from_message(session_id, user_id, user_name, message_text)

            mood_desc = self.emotion.get_mood_description()
            user_desc = self.memory.get_profile_description(user_id, special_prompt=special_prompt)
            atmosphere = self.memory.get_session_atmosphere(session_id)
            group_ctx = self._build_group_context(atmosphere)
            recent_context = self.memory.get_recent_context(
                session_id, self.behavior_config['recent_context_limit'], exclude_latest=True
            )
            reply_strategy = self._build_reply_strategy(
                user_id=user_id,
                message=message_text,
                relation=relation,
                atmosphere=atmosphere,
                special=bool(special),
            )
            self.last_reply_strategy[session_id] = reply_strategy

            # 搜索相关记忆
            keywords = self._extract_keywords(message_text)
            relevant = self.memory.search_memories(keywords, user_id, limit=3)
            memory_lines = [f'- {m["summary"]}' for m in relevant if m.get('score', 0) > 0.1]

            stable_prompt = self.persona.build_system_prompt(mood_desc='')
            runtime_context = self._build_runtime_context(
                mood_desc=mood_desc,
                user_desc=user_desc,
                group_ctx=group_ctx,
                recent_context=recent_context,
                reply_strategy=reply_strategy,
                special_prompt=special_prompt,
                memory_lines=memory_lines,
            )

            # 稳定人设放 system prompt；每轮变化的状态/记忆按 AstrBot 推荐放临时 extra parts。
            if hasattr(request, 'system_prompt') and request.system_prompt:
                request.system_prompt = stable_prompt + '\n\n---\n以下是补充设定（如果和上面冲突，以上面为准）:\n' + request.system_prompt
            elif hasattr(request, 'system_prompt'):
                request.system_prompt = stable_prompt

            self._append_runtime_context(request, runtime_context)
        except Exception:
            logger.exception("[AlivePersona] LLM 请求钩子失败，已跳过本轮活人感注入")

    @register_on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response):
        """在 LLM 回复后，用随机行为修饰"""
        try:
            if not hasattr(response, 'completion_text') or not response.completion_text:
                return

            session_id = event.unified_msg_origin
            mood = self.emotion.get_mood()
            original = response.completion_text

            direct = self.random_behavior.before_reply(
                session_id,
                event.get_message_str(),
                repeat_rate=self.behavior_config['repeat_rate'],
            )
            if direct:
                response.completion_text = direct
                return

            # 先去除 LLM 重复表达的句子
            original = self.random_behavior.deduplicate(original)

            # 随机行为修饰（不再分条，只做文本修饰）
            modified = self.random_behavior.modify_reply(
                original,
                mood,
                max_chars=self.behavior_config['max_reply_chars'],
                short_reply_rate=self.behavior_config['short_reply_rate'],
                template_tail_filter=self.behavior_config['template_tail_filter'],
                allow_short_reply=self.behavior_config['companion_mode'],
            )

            response.completion_text = modified
        except Exception:
            logger.exception("[AlivePersona] LLM 回复后处理失败，保留原始回复")

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
        special = self._match_special_user(user_id, event.get_sender_name())
        desc = self.memory.get_profile_description(user_id, special_prompt=special_prompt_text(special))
        profile = self.memory.get_profile(user_id)
        fav = profile['favorability']
        count = profile.get('message_count', 0)
        rel = self.memory.get_relation(user_id, bool(special))
        rel_cn = {
            'close_friend': '好朋友', 'friend': '朋友',
            'acquaintance': '认识', 'stranger': '陌生人',
        }
        notes = self.memory.get_recent_notes_text(user_id)
        parts = [f"关于你的记忆:\n{desc}\n"]
        if self.enable_favorability:
            parts.append(f"好感度: {fav}/100")
        parts.append(f"关系: {rel_cn.get(rel, rel)}")
        parts.append(f"互动次数: {count}")
        if notes:
            parts.append(f"最近记住: {notes}")
        info = '\n'.join(parts)
        yield event.plain_result(info)

    @register_command("alive", alias={"persona_status", "活人状态"})
    async def cmd_alive(self, event: AstrMessageEvent):
        """查看活人感运行状态"""
        session_id = event.unified_msg_origin
        user_id = event.get_sender_id()
        mood = self.emotion.get_mood()
        atmosphere = self.memory.get_session_atmosphere(session_id)
        relation = self.memory.get_relation(user_id, bool(self._match_special_user(user_id, event.get_sender_name())))
        info = (
            f"心情: {mood}\n"
            f"群聊氛围: {atmosphere['mood']} | 近1分钟{atmosphere['message_rate']}条 | 活跃{atmosphere['active_users']}人\n"
            f"关系: {relation}\n"
            f"短回概率: {self.behavior_config['short_reply_rate']:.2f}\n"
            f"上下文条数: {self.behavior_config['recent_context_limit']}\n"
            f"长期记忆: {len(self.memory.long_term)}条\n"
            f"上次策略: {self.last_reply_strategy.get(session_id, '暂无')}"
        )
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

    def _match_special_user(self, user_id: str, user_name: str):
        special_users = self.persona.persona.get('special_users') or {}
        profile = self.memory.get_profile(user_id)
        return match_special_user(special_users, user_id, user_name, profile.get('nickname'))

    @staticmethod
    def _build_group_context(atmosphere: dict) -> str:
        return (
            f"{atmosphere['description']}。"
            f"近1分钟消息数: {atmosphere['message_rate']}。"
            f"近5分钟活跃人数: {atmosphere['active_users']}。"
        )

    def _build_reply_strategy(
        self,
        user_id: str,
        message: str,
        relation: str,
        atmosphere: dict,
        special: bool = False,
    ) -> str:
        mood = self.emotion.get_mood()
        profile = self.memory.get_profile(user_id)
        parts = []

        if special:
            parts.append('这是你在意的人，语气放松直接，关心可以短一点，不要包装成客套话')
        elif relation == 'stranger':
            parts.append('和这个人还不熟，礼貌温和，别显得过分亲近')
        elif relation in ('friend', 'close_friend'):
            parts.append('你们比较熟，可以更自然随意一点')

        if atmosphere.get('mood') == '热闹':
            parts.append('群里很热闹，这次尽量只回一句，不要展开')
        elif atmosphere.get('mood') == '安静':
            parts.append('群里偏安静，可以正常回，但不要硬追问续话题')

        if re.search(r'(累|困|不舒服|难受|难过|烦|焦虑|崩溃|委屈|压力)', message):
            parts.append('对方在表达状态或情绪，先接住情绪，别立刻说教或列方案')

        if re.search(r'谢谢|感谢|辛苦了', message):
            parts.append('对方在感谢，可以只用很短的回应，不必每次说不客气')

        if re.search(r'(怎么|如何|为什么|配置|api|url|/v1|密钥|模型|报错|错误)', message, re.I):
            parts.append('这是求助或技术问题，给关键答案即可，不要客服式收尾')
        else:
            parts.append('这不是正式问答，允许只回应其中一小部分')

        if mood in ('sleepy', 'bored', 'upset'):
            parts.append('你现在不太想多说，回复可以更短')
        elif mood in ('excited', 'happy', 'content') and profile.get('message_count', 0) > 10:
            parts.append('心情还行，可以稍微自然一点，但别变话痨')

        parts.append(f'控制在{self.behavior_config["max_reply_chars"]}字以内，避免问句结尾')
        return '。'.join(parts)

    @staticmethod
    def _build_runtime_context(
        mood_desc: str,
        user_desc: str,
        group_ctx: str,
        recent_context: str,
        reply_strategy: str,
        special_prompt: str,
        memory_lines: list[str],
    ) -> str:
        sections = []
        if mood_desc:
            sections.append(f'【当前心情】\n{mood_desc}')
        if group_ctx:
            sections.append(f'【当前场景】\n{group_ctx}')
        if user_desc:
            sections.append(f'【关于当前对话的人】\n{user_desc}')
        if special_prompt:
            sections.append(f'【当前这人的特殊关系】\n{special_prompt}')
        if recent_context:
            sections.append(
                '【刚才的聊天上下文】\n'
                '下面是最近几条消息。回复时接住当前上下文，不要把它们逐条复述出来。\n'
                f'{recent_context}'
            )
        if memory_lines:
            sections.append('【你的相关记忆（可以自然地引用，但不要刻意提起）】\n' + '\n'.join(memory_lines))
        if reply_strategy:
            sections.append(f'【这次回复策略】\n{reply_strategy}')
        return '\n\n'.join(sections)

    @staticmethod
    def _append_runtime_context(request, runtime_context: str):
        if not runtime_context:
            return
        if not hasattr(request, 'extra_user_content_parts'):
            return
        if request.extra_user_content_parts is None:
            request.extra_user_content_parts = []
        part = TextPart(text=runtime_context)
        if hasattr(part, 'mark_as_temp'):
            part = part.mark_as_temp()
        request.extra_user_content_parts.append(part)

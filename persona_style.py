"""人设显性锚点与冷却策略。"""
import re
import time


class PersonaStyleState:
    def __init__(self, trait_anchor_rate: float = 0.35, identity_mention_policy: str = 'rare'):
        self.trait_anchor_rate = trait_anchor_rate
        self.identity_mention_policy = identity_mention_policy
        self.last_anchor_by_session: dict[str, float] = {}
        self.catchphrase_cooldown_until: dict[str, float] = {}
        self.last_mode_by_session: dict[str, str] = {}

    def decide(self, session_id: str, message: str, relation: str, atmosphere: dict, special: bool) -> dict:
        intent = self.classify_intent(message)
        catchphrase_policy = self.catchphrase_policy(intent)
        now = time.time()
        recently_anchored = now - self.last_anchor_by_session.get(session_id, 0) < 180

        rate = self.trait_anchor_rate
        if intent in ('identity', 'technical'):
            rate *= 0.35
        elif intent == 'emotional':
            rate *= 0.75
        elif intent in ('casual', 'social', 'acknowledgement'):
            rate *= 1.1
        if relation in ('friend', 'close_friend') or special:
            rate += 0.08
        if atmosphere.get('mood') == '热闹':
            rate *= 0.65
        if recently_anchored:
            rate *= 0.35

        anchor = self._random(max(0.02, min(0.85, rate)))
        if anchor:
            self.last_anchor_by_session[session_id] = now

        mode = self._mode(intent, anchor, special, relation)
        self.last_mode_by_session[session_id] = mode

        return {
            'intent': intent,
            'anchor': anchor,
            'mode': mode,
            'allow_identity_mention': self._allow_identity_mention(message, anchor),
            'catchphrase_on_cooldown': self.catchphrase_on_cooldown(session_id),
            'catchphrase_allowed': catchphrase_policy['allowed'],
            'catchphrase_only_allowed': catchphrase_policy['standalone_allowed'],
            'catchphrase_needs_content': catchphrase_policy['needs_content'],
        }

    def catchphrase_on_cooldown(self, session_id: str) -> bool:
        return time.time() < self.catchphrase_cooldown_until.get(session_id, 0)

    def mark_catchphrase(self, session_id: str, cooldown_seconds: int = 240):
        self.catchphrase_cooldown_until[session_id] = time.time() + cooldown_seconds

    def get_last_mode(self, session_id: str) -> str:
        return self.last_mode_by_session.get(session_id, '自然')

    @staticmethod
    def classify_intent(message: str) -> str:
        """Classify the message before deciding how visibly to use the persona.

        Identity questions must be checked before the broader technical/casual
        patterns.  Otherwise a question such as ``你是谁`` falls through to a
        casual reply and a short catchphrase can replace the actual answer.
        """
        message = str(message or '')
        if re.search(
            r'(你是谁|你叫什么(?:名字)?|你叫啥|你的名字|你的身份|什么身份|身份是什么|'
            r'你的设定|什么设定|你的背景|背景是什么|是什么人|你是哪位|'
            r'你是做什么的|你是干什么的|你是干嘛的|你是什么(?:模型|机器人|助手)|你能做什么|你能干什么|你来自哪里|你从哪来)',
            message,
            re.I,
        ):
            return 'identity'
        if re.search(r'(怎么(?!样)|如何|为什么|配置|api|url|/v1|密钥|模型|报错|错误|帮|求|教)', message, re.I):
            return 'technical'
        if re.search(r'(累|困|不舒服|难受|难过|烦|焦虑|崩溃|委屈|压力|开心|伤心|生气|难受)', message):
            return 'emotional'
        if re.search(r'(谢谢|感谢|辛苦了|多谢|收到|好的|好哒|明白了)', message):
            return 'acknowledgement'
        if re.search(r'(早上好|早安|早|晚安|睡了|睡吧|走了|去吧|先走|再见|拜拜|拜|下了|回来了)', message):
            return 'social'
        if re.search(
            r'(吗|什么|哪儿|哪里|哪边|谁|多少|几[个岁点次件]|怎么样|怎样|是否|能不能|可不可以|有没有|是不是|[？?])',
            message,
        ):
            return 'question'
        return 'casual'

    # Keep the old private name as a compatibility shim for external callers
    # and older tests that imported it directly.
    _classify_intent = classify_intent

    @staticmethod
    def catchphrase_policy(intent: str) -> dict:
        """Return the per-intent rules for using configured catchphrases."""
        standalone_allowed = intent in ('social', 'acknowledgement', 'casual')
        needs_content = intent in ('identity', 'technical', 'emotional', 'question')
        return {
            'allowed': True,
            'standalone_allowed': standalone_allowed,
            'needs_content': needs_content,
        }

    @staticmethod
    def _mode(intent: str, anchor: bool, special: bool, relation: str) -> str:
        if intent == 'identity':
            return '身份回答优先，直接说明自己是谁'
        if intent in ('technical', 'question'):
            return '答题优先，低显性人设'
        if intent == 'emotional':
            return '接情绪，少解释设定'
        if special or relation in ('friend', 'close_friend'):
            return '熟人自然，语气贴合'
        if anchor:
            return '轻微显性人设'
        return '自然低显性'

    def _allow_identity_mention(self, message: str, anchor: bool) -> bool:
        if re.search(r'(你是谁|你叫|身份|设定|背景|是什么人)', message):
            return True
        if self.identity_mention_policy == 'never':
            return False
        if self.identity_mention_policy == 'rare':
            return anchor and self._random(0.15)
        return anchor

    @staticmethod
    def _random(chance: float) -> bool:
        return (time.time_ns() % 10000) / 10000 < chance

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
        intent = self._classify_intent(message)
        now = time.time()
        recently_anchored = now - self.last_anchor_by_session.get(session_id, 0) < 180

        rate = self.trait_anchor_rate
        if intent == 'technical':
            rate *= 0.35
        elif intent == 'emotional':
            rate *= 0.75
        elif intent == 'casual':
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
        }

    def catchphrase_on_cooldown(self, session_id: str) -> bool:
        return time.time() < self.catchphrase_cooldown_until.get(session_id, 0)

    def mark_catchphrase(self, session_id: str, cooldown_seconds: int = 240):
        self.catchphrase_cooldown_until[session_id] = time.time() + cooldown_seconds

    def get_last_mode(self, session_id: str) -> str:
        return self.last_mode_by_session.get(session_id, '自然')

    @staticmethod
    def _classify_intent(message: str) -> str:
        if re.search(r'(怎么|如何|为什么|配置|api|url|/v1|密钥|模型|报错|错误|帮|求|教)', message, re.I):
            return 'technical'
        if re.search(r'(累|困|不舒服|难受|难过|烦|焦虑|崩溃|委屈|压力|开心|谢谢|感谢|对不起|抱歉)', message):
            return 'emotional'
        if re.search(r'(早|晚安|睡了|走了|拜|回来了)', message):
            return 'social'
        return 'casual'

    @staticmethod
    def _mode(intent: str, anchor: bool, special: bool, relation: str) -> str:
        if intent == 'technical':
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

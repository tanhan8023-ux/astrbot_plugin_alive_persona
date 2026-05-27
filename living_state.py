"""生活节律与低存在感策略。"""
import re
import time


class LivingState:
    def __init__(self):
        self.last_seen_by_user: dict[str, float] = {}
        self.last_seen_by_session: dict[str, float] = {}

    def observe(self, session_id: str, user_id: str) -> dict:
        now = time.time()
        user_last = self.last_seen_by_user.get(user_id)
        session_last = self.last_seen_by_session.get(session_id)
        self.last_seen_by_user[user_id] = now
        self.last_seen_by_session[session_id] = now

        return {
            'rhythm': self.get_rhythm(),
            'user_gap_minutes': self._minutes_since(user_last, now),
            'session_gap_minutes': self._minutes_since(session_last, now),
        }

    def get_rhythm(self) -> dict:
        hour = time.localtime().tm_hour
        if 5 <= hour < 9:
            return {
                'period': '清晨',
                'prompt': '现在是清晨，状态刚醒不久，说话可以更轻一点，别太热闹',
                'quiet_bias': 0.15,
            }
        if 9 <= hour < 12:
            return {
                'period': '上午',
                'prompt': '现在是上午，状态比较平稳，回复保持简短清楚',
                'quiet_bias': 0.0,
            }
        if 12 <= hour < 14:
            return {
                'period': '中午',
                'prompt': '现在是中午，语气可以放松一点，但不要主动展开太多',
                'quiet_bias': 0.05,
            }
        if 14 <= hour < 18:
            return {
                'period': '下午',
                'prompt': '现在是下午，状态普通，正常接话就好',
                'quiet_bias': 0.0,
            }
        if 18 <= hour < 23:
            return {
                'period': '晚上',
                'prompt': '现在是晚上，聊天可以比白天更自然一点，但仍然克制',
                'quiet_bias': -0.05,
            }
        return {
            'period': '深夜',
            'prompt': '现在是深夜，说话更安静短一点，除非对方明显需要回应',
            'quiet_bias': 0.2,
        }

    def build_presence_prompt(self, user_gap_minutes: float | None, session_gap_minutes: float | None) -> str:
        parts = [self.get_rhythm()['prompt']]
        if user_gap_minutes is not None and user_gap_minutes >= 180:
            parts.append('这个人隔了挺久才出现，可以自然一点接住，不要像第一次见')
        elif user_gap_minutes is not None and user_gap_minutes <= 3:
            parts.append('你们刚刚还在说话，不需要重复寒暄')

        if session_gap_minutes is not None and session_gap_minutes >= 60:
            parts.append('群里隔了一阵没人触发你，回复可以像刚看到消息一样自然')
        return '。'.join(parts)

    def should_light_reply(
        self,
        message: str,
        relation: str,
        atmosphere: dict,
        special: bool,
        light_reply_rate: float,
    ) -> bool:
        if special:
            return False
        if relation in ('friend', 'close_friend'):
            return False
        if self._looks_like_request(message):
            return False
        if self._looks_emotional(message):
            return False

        chance = light_reply_rate + self.get_rhythm()['quiet_bias']
        if atmosphere.get('mood') == '热闹':
            chance += 0.12
        elif atmosphere.get('mood') == '安静':
            chance -= 0.08
        chance = max(0, min(0.65, chance))
        return chance > 0 and self._random(chance)

    @staticmethod
    def _looks_like_request(message: str) -> bool:
        return bool(re.search(r'(怎么|如何|为什么|吗|嘛|？|\?|配置|api|url|/v1|密钥|模型|报错|错误|帮|求|教)', message, re.I))

    @staticmethod
    def _looks_emotional(message: str) -> bool:
        return bool(re.search(r'(累|困|不舒服|难受|难过|烦|焦虑|崩溃|委屈|压力|开心|谢谢|感谢|对不起|抱歉)', message))

    @staticmethod
    def _minutes_since(last_ts: float | None, now: float) -> float | None:
        if not last_ts:
            return None
        return (now - last_ts) / 60

    @staticmethod
    def _random(chance: float) -> bool:
        return (time.time_ns() % 10000) / 10000 < chance

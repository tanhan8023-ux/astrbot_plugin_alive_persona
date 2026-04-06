"""
随机行为系统 - 让 bot 偶尔做一些"不按套路"的事

- 发颜文字
- 打错字然后纠正
- 分多条消息发送
- 复读
- 根据情绪修饰回复
"""
import random, re

KAOMOJIS = [
    '(=^-^=)', '(>_<)', '(T_T)', '(*^_^*)', '(._. )',
    '(o_O)', '(^_^;)', '(-_-)', '(>w<)', '(QAQ)',
    'orz', '_(:3」∠)_', '(╯°□°)╯', '(´;ω;`)', '(≧▽≦)',
]

EMOJI_ONLY = [
    '哈哈哈', '?', '啊这', '6', '好家伙',
    '笑死', '绷不住了', '确实', '真的假的', '...',
    '嗯嗯', '哦', '啊？', '草', '无语',
]

SIMILAR_CHARS = {
    '的': '得', '得': '的', '地': '的', '在': '再', '再': '在',
    '他': '她', '她': '他', '做': '作', '作': '做',
    '那': '哪', '哪': '那', '了': '乐', '好': '号', '是': '事',
}


class RandomBehavior:
    def __init__(self):
        self.repeat_tracker: dict[str, dict] = {}  # session -> {content, count}

    def before_reply(self, session_id: str, user_msg: str):
        """在 AI 回复前，决定是否触发随机行为。返回 str 或 None"""
        r = random.random()
        # 5% 复读
        if r < 0.05:
            rep = self._check_repeat(session_id, user_msg)
            if rep: return rep
        # 3% 只发表情
        if 0.05 <= r < 0.08:
            return random.choice(EMOJI_ONLY)
        return None

    def modify_reply(self, reply: str, mood: str) -> str | list[str]:
        """对 AI 回复进行随机修饰，可能返回 list 表示分多条发"""
        r = random.random()

        # 8% 加颜文字
        if r < 0.08:
            reply = reply + ' ' + random.choice(KAOMOJIS)

        # 5% 打错字
        if 0.08 <= r < 0.13:
            reply = self._typo(reply)

        # 10% 分多条 (够长时)
        if 0.13 <= r < 0.23 and len(reply) > 15:
            parts = self._split(reply)
            if len(parts) > 1:
                return parts

        # 困倦加 zzz
        if mood == 'sleepy' and random.random() < 0.15:
            reply += random.choice(['...zzz', ' (打哈欠)', '...困', '..'])

        # 兴奋加感叹号
        if mood == 'excited' and random.random() < 0.1:
            reply = re.sub(r'[。！!]?$', '!!!', reply)

        return reply

    def _check_repeat(self, sid: str, msg: str):
        t = self.repeat_tracker.get(sid)
        if t and t['content'] == msg:
            t['count'] += 1
            if t['count'] >= 3 and random.random() < 0.6:
                return msg
        else:
            self.repeat_tracker[sid] = {'content': msg, 'count': 1}
        return None

    def _typo(self, text: str) -> str:
        if len(text) < 5: return text
        # 打错字然后纠正
        for i, ch in enumerate(text):
            if ch in SIMILAR_CHARS and random.random() < 0.3:
                wrong = text[:i] + SIMILAR_CHARS[ch] + text[i+1:]
                return wrong + f'\n*{ch}'
        return text

    def _split(self, text: str) -> list[str]:
        parts = re.split(r'(?<=[。！？!?\n，,])\s*', text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) <= 1:
            mid = len(text) // 2
            return [text[:mid].strip(), text[mid:].strip()]
        # 合并太短的
        result, cur = [], ''
        for p in parts:
            cur += p
            if len(cur) >= 5:
                result.append(cur)
                cur = ''
        if cur: result.append(cur)
        return result[:3]

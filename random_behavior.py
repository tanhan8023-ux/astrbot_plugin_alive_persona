"""
随机行为系统 - 让 bot 的回复节奏更像真人

- 偶尔复读群友（跟风）
- 偶尔把回复压成完整短回
- 去掉客服式尾巴和重复表达
- 软限制回复长度
"""
import random
import re


TEMPLATE_TAIL_PATTERNS = [
    r'[，,。；;]?\s*如果还有(什么)?(问题|不懂的|需要).*$',
    r'[，,。；;]?\s*有(什么)?(问题|不懂的|需要)(的话)?(可以)?(再)?(来)?问我.*$',
    r'[，,。；;]?\s*需要的话(可以)?(再)?(来)?问我.*$',
    r'[，,。；;]?\s*我会尽力(帮你|帮助你).*$',
    r'[，,。；;]?\s*希望(这些|这个)?(能|可以)?帮到你.*$',
]

ACTION_PATTERNS = [
    r'\*[^*]{1,30}\*',
    r'（[^）]{1,30}）',
    r'\([^)]{1,30}\)',
]


class RandomBehavior:
    def __init__(self):
        self.repeat_tracker: dict[str, dict] = {}

    def before_reply(self, session_id: str, user_msg: str, repeat_rate: float = 0.03):
        """在 AI 回复前，决定是否触发随机行为。返回 str 或 None"""
        if random.random() < repeat_rate:
            rep = self._check_repeat(session_id, user_msg)
            if rep:
                return rep
        else:
            self._check_repeat(session_id, user_msg)
        return None

    def modify_reply(
        self,
        reply: str,
        mood: str,
        max_chars: int = 60,
        short_reply_rate: float = 0.06,
        template_tail_filter: bool = True,
        allow_short_reply: bool = True,
    ) -> str:
        """对 AI 回复进行轻量修饰，保持克制，不加戏。"""
        if not reply or not reply.strip():
            return reply

        reply = self.clean_reply(reply, template_tail_filter=template_tail_filter)

        if allow_short_reply and self._can_collapse_to_short(reply, mood) and random.random() < short_reply_rate:
            return self._short_reply(mood)

        r = random.random()
        if r < 0.08:
            reply = self._strip_trailing_punct(reply)
        elif 0.08 <= r < 0.13:
            reply = self._soften_ending(reply)

        reply = self._reduce_question_tail(reply)
        reply = self.soft_limit(reply, max_chars)
        return reply.strip()

    @classmethod
    def clean_reply(cls, text: str, template_tail_filter: bool = True) -> str:
        text = str(text or '').strip()
        text = cls.deduplicate(text)
        text = cls._remove_action_text(text)
        if template_tail_filter:
            text = cls._remove_template_tail(text)
        text = re.sub(r'\n{2,}', '\n', text).strip()
        return text

    def _check_repeat(self, sid: str, msg: str):
        """检测复读：同一条短消息连续出现3次以上，有概率跟着复读"""
        msg = str(msg or '').strip()
        if not msg or len(msg) > 20:
            return None
        t = self.repeat_tracker.get(sid)
        if t and t['content'] == msg:
            t['count'] += 1
            if t['count'] >= 3 and random.random() < 0.5:
                return msg
        else:
            self.repeat_tracker[sid] = {'content': msg, 'count': 1}
        return None

    @staticmethod
    def deduplicate(text: str) -> str:
        """去除 LLM 回复中语义重复的句子。"""
        if not text or len(text) < 10:
            return text

        sentences = re.split(r'(?<=[。！？!?\n])', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if len(sentences) <= 1:
            return text

        kept = [sentences[0]]
        for sent in sentences[1:]:
            if RandomBehavior._is_redundant(sent, kept):
                continue
            kept.append(sent)

        result = ''.join(kept)
        return result if result.strip() else text

    @staticmethod
    def soft_limit(text: str, max_chars: int) -> str:
        if not max_chars or max_chars <= 0 or len(text) <= max_chars:
            return text

        candidates = re.split(r'(?<=[。！？!?])', text)
        kept = ''
        for part in candidates:
            if not part:
                continue
            if len(kept + part) <= max_chars:
                kept += part
            elif kept:
                break
            else:
                kept = part[:max_chars]
                break

        kept = kept.strip() or text[:max_chars].strip()
        return re.sub(r'[，,、；;：:]+$', '', kept)

    @staticmethod
    def _is_redundant(candidate: str, existing: list[str]) -> bool:
        clean_cand = re.sub(r'[^\w]', '', candidate)
        if len(clean_cand) < 3:
            return False

        cand_bigrams = {clean_cand[i:i + 2] for i in range(len(clean_cand) - 1)}
        if not cand_bigrams:
            return False

        for sent in existing:
            clean_sent = re.sub(r'[^\w]', '', sent)
            if len(clean_sent) < 3:
                continue
            sent_bigrams = {clean_sent[i:i + 2] for i in range(len(clean_sent) - 1)}
            if not sent_bigrams:
                continue
            overlap = len(cand_bigrams & sent_bigrams)
            ratio_cand = overlap / len(cand_bigrams)
            ratio_sent = overlap / len(sent_bigrams)
            if max(ratio_cand, ratio_sent) > 0.6:
                return True

        return False

    @staticmethod
    def _remove_template_tail(text: str) -> str:
        old = None
        while old != text:
            old = text
            for pattern in TEMPLATE_TAIL_PATTERNS:
                text = re.sub(pattern, '', text, flags=re.I | re.S).strip()
        return text

    @staticmethod
    def _remove_action_text(text: str) -> str:
        for pattern in ACTION_PATTERNS:
            text = re.sub(pattern, '', text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _strip_trailing_punct(text: str) -> str:
        return re.sub(r'[。，,\.]+$', '', text)

    @staticmethod
    def _soften_ending(text: str) -> str:
        if text.endswith('。') and len(text) <= 30:
            return text[:-1]
        return text

    @staticmethod
    def _reduce_question_tail(text: str) -> str:
        if text.count('？') + text.count('?') <= 1:
            return text
        parts = re.split(r'(?<=[。！？!?])', text)
        kept = []
        question_seen = False
        for part in parts:
            if not part:
                continue
            is_question = part.endswith(('？', '?'))
            if is_question and question_seen:
                continue
            if is_question:
                question_seen = True
            kept.append(part)
        return ''.join(kept) or text

    @staticmethod
    def _can_collapse_to_short(reply: str, mood: str) -> bool:
        if len(reply) > 24:
            return False
        if re.search(r'url|api|/v1|密钥|模型|配置|错误|报错|怎么|如何|为什么', reply, re.I):
            return False
        return mood in ('neutral', 'sleepy', 'bored', 'happy', 'content')

    @staticmethod
    def _short_reply(mood: str) -> str:
        pools = {
            'sleepy': ['嗯', '好', '知道了'],
            'bored': ['嗯', '随你', '都行'],
            'happy': ['好呀', '嗯嗯', '没事的'],
            'content': ['嗯，好呀', '知道了', '没事的'],
        }
        pool = pools.get(mood, ['嗯', '好', '知道了', '没事的'])
        return random.choice(pool)

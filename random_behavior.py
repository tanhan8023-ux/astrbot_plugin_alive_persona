"""
随机行为系统 - 让 bot 的回复节奏更像真人

- 分多条消息发送（模拟真人打字分段发）
- 偶尔复读群友（跟风）
- 回复延迟感（通过分段模拟思考间隔）
- 偶尔省略句末标点（真人打字习惯）
- 偶尔在句末加语气词（嗯、吧、呢等，增加口语感）
- 去除 LLM 重复表达的句子
"""
import random, re


class RandomBehavior:
    def __init__(self):
        self.repeat_tracker: dict[str, dict] = {}  # session -> {content, count}

    def before_reply(self, session_id: str, user_msg: str):
        """在 AI 回复前，决定是否触发随机行为。返回 str 或 None"""
        r = random.random()
        # 3% 复读（群里跟风行为，很自然）
        if r < 0.03:
            rep = self._check_repeat(session_id, user_msg)
            if rep:
                return rep
        return None

    def modify_reply(self, reply: str, mood: str) -> str | list[str]:
        """对 AI 回复进行随机修饰，可能返回 list 表示分多条发"""
        if not reply or not reply.strip():
            return reply

        r = random.random()

        # 8% 去掉句末标点（真人经常不打句号）
        if r < 0.08:
            reply = self._strip_trailing_punct(reply)

        # 10% 分多条发送（够长时，模拟真人打字节奏）
        elif 0.08 <= r < 0.18 and len(reply) > 15:
            parts = self._split(reply)
            if len(parts) > 1:
                return parts

        # 5% 把句末的句号换成更口语化的结尾
        elif 0.18 <= r < 0.23:
            reply = self._soften_ending(reply)

        return reply

    def _check_repeat(self, sid: str, msg: str):
        """检测复读：同一条消息连续出现3次以上，有概率跟着复读"""
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
        """去除 LLM 回复中语义重复的句子。
        
        把回复按句子拆开，如果后面的句子和前面某句字符重叠率过高，就砍掉。
        这能解决 LLM 经常"好的知道了。我知道了没问题。"这种重复表达。
        """
        if not text or len(text) < 10:
            return text

        # 按句末标点拆句，保留标点
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
    def _is_redundant(candidate: str, existing: list[str]) -> bool:
        """判断 candidate 是否和 existing 中的某句语义重复。
        
        用字符级别的 bigram 重叠率来判断，不依赖任何外部库。
        """
        # 去掉标点和空白，只留实际内容
        clean_cand = re.sub(r'[^\w]', '', candidate)
        if len(clean_cand) < 4:
            return False  # 太短的不判（语气词、"嗯"、"好"之类的）

        cand_bigrams = set()
        for i in range(len(clean_cand) - 1):
            cand_bigrams.add(clean_cand[i:i+2])

        if not cand_bigrams:
            return False

        for sent in existing:
            clean_sent = re.sub(r'[^\w]', '', sent)
            if len(clean_sent) < 4:
                continue
            sent_bigrams = set()
            for i in range(len(clean_sent) - 1):
                sent_bigrams.add(clean_sent[i:i+2])
            if not sent_bigrams:
                continue
            # 双向重叠：candidate 的 bigram 有多少在 sent 里，反过来也算
            overlap = len(cand_bigrams & sent_bigrams)
            ratio_cand = overlap / len(cand_bigrams)
            ratio_sent = overlap / len(sent_bigrams)
            # 取较大值，任一方向高度重叠就算重复
            if max(ratio_cand, ratio_sent) > 0.6:
                return True

        return False

    def _strip_trailing_punct(self, text: str) -> str:
        """去掉句末标点，模拟真人懒得打标点的习惯"""
        # 只去句号和逗号，保留问号感叹号（这些有语气意义）
        return re.sub(r'[。，,\.]+$', '', text)

    def _soften_ending(self, text: str) -> str:
        """偶尔把生硬的句号结尾变柔和"""
        if text.endswith('。'):
            # 不是所有句子都适合加语气词，只处理短句
            if len(text) <= 30:
                text = text[:-1]  # 直接去掉句号，更自然
        return text

    def _split(self, text: str) -> list[str]:
        """把长回复拆成多条，模拟真人分段打字"""
        # 优先按标点分割
        parts = re.split(r'(?<=[。！？!?\n])\s*', text)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            # 尝试按逗号分
            parts = re.split(r'(?<=[，,])\s*', text)
            parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            # 实在分不了就不分
            return [text]

        # 合并太短的片段
        result, cur = [], ''
        for p in parts:
            cur += p
            if len(cur) >= 5:
                result.append(cur)
                cur = ''
        if cur:
            if result:
                result[-1] += cur
            else:
                result.append(cur)

        return result[:3]

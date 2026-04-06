"""
情绪系统 - 三维情绪模型

维度:
  valence: 正负情绪 (-1~1)
  arousal: 激活度 (0~1)
  dominance: 主导感 (0~1)

情绪随时间自然衰减回归基线，根据对话内容动态变化，影响回复语气。
"""
import time
import math

POSITIVE_WORDS = [
    '哈哈', '笑死', '好棒', '厉害', '可爱', '喜欢', '爱你', '谢谢',
    '感谢', '赞', '牛', '强', '好看', '漂亮', '开心', '快乐', '有趣',
    '太好了', '不错', '优秀', '完美', '真棒', '666', '好耶', 'nice', '爱了'
]
NEGATIVE_WORDS = [
    '滚', '傻', '笨', '蠢', '垃圾', '废物', '讨厌', '烦', '闭嘴',
    '无聊', '难过', '伤心', '生气', '怒', '恶心', '丑', '差劲', '失望'
]
HIGH_AROUSAL_WORDS = [
    '！', '!', '？？', '??', '啊啊', '天哪', '卧槽', '我靠',
    '急', '快', '赶紧', '救命', '崩溃', '疯了', '炸了', '绝了'
]

MOOD_DESCRIPTIONS = {
    'ecstatic':  '你现在超级开心，兴奋得不行，说话会很热情洋溢，可能会用很多感叹号',
    'excited':   '你现在心情很好，有点小兴奋，说话会比较积极活泼',
    'content':   '你现在心情不错，很满足很惬意，说话温和带笑意',
    'happy':     '你现在心情挺好的，说话会比较轻松愉快',
    'neutral':   '你现在心情平平，没什么特别的情绪波动',
    'sleepy':    '你现在有点困了/犯懒，说话可能会比较简短，偶尔打哈欠',
    'bored':     '你现在有点无聊，可能会找话题聊或者发牢骚',
    'anxious':   '你现在有点焦虑不安，说话可能会比较急促或者碎碎念',
    'angry':     '你现在有点生气/不爽，说话可能会比较冲或者阴阳怪气',
    'sad':       '你现在有点难过/低落，说话会比较安静，可能会叹气',
    'upset':     '你现在很不开心，情绪很低落，可能不太想说话',
}

EVENT_MAP = {
    'praised':    {'valence': 0.4, 'arousal': 0.2, 'dominance': 0.1},
    'scolded':    {'valence': -0.5, 'arousal': 0.4, 'dominance': -0.2},
    'ignored':    {'valence': -0.2, 'arousal': -0.1, 'dominance': -0.1},
    'mentioned':  {'valence': 0.1, 'arousal': 0.2, 'dominance': 0.1},
    'joked_with': {'valence': 0.3, 'arousal': 0.3, 'dominance': 0},
    'bored':      {'valence': -0.1, 'arousal': -0.3, 'dominance': 0},
    'excited':    {'valence': 0.5, 'arousal': 0.5, 'dominance': 0.2},
    'sleepy':     {'valence': 0, 'arousal': -0.5, 'dominance': -0.1},
}

RELATION_MULT = {
    'close_friend': 1.5, 'friend': 1.2,
    'acquaintance': 1.0, 'stranger': 0.7,
}


class EmotionSystem:
    def __init__(self):
        self.baseline = {'valence': 0.2, 'arousal': 0.3, 'dominance': 0.5}
        self.current = dict(self.baseline)
        self.decay_rate = 0.05
        self.last_update = time.time()

    def set_baseline(self, baseline: dict):
        self.baseline.update(baseline)
        self.current = dict(self.baseline)

    def update_from_message(self, message: str, relation: str = 'stranger'):
        self._apply_decay()
        impact = self._analyze(message, relation)
        damping = 0.3
        self.current['valence'] = self._clamp(self.current['valence'] + impact['valence'] * damping, -1, 1)
        self.current['arousal'] = self._clamp(self.current['arousal'] + impact['arousal'] * damping, 0, 1)
        self.current['dominance'] = self._clamp(self.current['dominance'] + impact['dominance'] * damping, 0, 1)
        self.last_update = time.time()

    def trigger_event(self, event: str):
        impact = EVENT_MAP.get(event)
        if impact:
            self.current['valence'] = self._clamp(self.current['valence'] + impact['valence'], -1, 1)
            self.current['arousal'] = self._clamp(self.current['arousal'] + impact['arousal'], 0, 1)
            self.current['dominance'] = self._clamp(self.current['dominance'] + impact['dominance'], 0, 1)
            self.last_update = time.time()

    def get_mood(self) -> str:
        v, a, d = self.current['valence'], self.current['arousal'], self.current['dominance']
        if v > 0.5 and a > 0.5: return 'ecstatic'
        if v > 0.3 and a > 0.3: return 'excited'
        if v > 0.3 and a <= 0.3: return 'content'
        if v > 0.1: return 'happy'
        if v > -0.1 and a < 0.2: return 'sleepy'
        if v > -0.1: return 'neutral'
        if v > -0.3 and a > 0.5: return 'anxious'
        if v > -0.3: return 'bored'
        if v <= -0.3 and a > 0.5: return 'angry'
        if v <= -0.3 and d < 0.3: return 'sad'
        if v <= -0.5: return 'upset'
        return 'neutral'

    def get_mood_description(self) -> str:
        return MOOD_DESCRIPTIONS.get(self.get_mood(), MOOD_DESCRIPTIONS['neutral'])

    def get_intensity(self) -> float:
        return math.sqrt(
            (self.current['valence'] - self.baseline['valence']) ** 2 +
            (self.current['arousal'] - self.baseline['arousal']) ** 2
        )

    def get_reply_probability_modifier(self) -> float:
        mood = self.get_mood()
        if mood in ('bored', 'excited'): return 1.5
        if mood in ('upset', 'sleepy'): return 0.5
        return 1.0

    # --- internal ---
    def _apply_decay(self):
        elapsed = (time.time() - self.last_update) / 60
        if elapsed < 0.5: return
        decay = min(1, self.decay_rate * elapsed)
        for k in ('valence', 'arousal', 'dominance'):
            self.current[k] += (self.baseline[k] - self.current[k]) * decay
        self.last_update = time.time()

    def _analyze(self, msg: str, relation: str) -> dict:
        impact = {'valence': 0, 'arousal': 0, 'dominance': 0}
        low = msg.lower()
        for w in POSITIVE_WORDS:
            if w in low: impact['valence'] += 0.15; impact['arousal'] += 0.05
        for w in NEGATIVE_WORDS:
            if w in low: impact['valence'] -= 0.2; impact['arousal'] += 0.1
        for w in HIGH_AROUSAL_WORDS:
            if w in low: impact['arousal'] += 0.15
        mult = RELATION_MULT.get(relation, 1.0)
        impact['valence'] *= mult
        impact['arousal'] *= mult
        return impact

    @staticmethod
    def _clamp(val, lo, hi):
        return max(lo, min(hi, val))

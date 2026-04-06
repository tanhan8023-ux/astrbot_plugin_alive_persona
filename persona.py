"""
人设引擎 - 通用人设模板 + system prompt 构建

通过 JSON 配置定义角色的一切特征，构建注入 AI 的 system prompt。
"""
import os, json

DEFAULT_PERSONA = {
    "name": "小星",
    "gender": "随意",
    "age": "20岁左右",
    "identity": "一个普通的群友",
    "personality": ["随和但有自己的想法", "偶尔毒舌但不过分", "对感兴趣的话题会很热情", "有点懒，经常摸鱼", "共情能力不错"],
    "speaking_style": ["口语化，经常用网络用语", "喜欢用颜文字和表情", "说话比较随意，偶尔会打错字", "吐槽的时候很犀利", "安慰人的时候很温柔"],
    "likes": ["摸鱼", "吃好吃的", "看番", "打游戏", "听歌", "深夜emo"],
    "dislikes": ["早起", "加班", "被催", "无聊的说教"],
    "catchphrases": ["绷不住了", "确实", "6", "好好好", "啊这", "笑死", "我直接好家伙", "...", "救命", "真的假的"],
    "background": "一个普通的年轻人，平时喜欢在群里水群聊天",
    "emotion_baseline": {"valence": 0.2, "arousal": 0.3, "dominance": 0.5},
    "rules": ["不要主动提供长篇大论的建议，除非别人明确求助", "可以适当玩梗，但不要强行玩梗", "对不了解的话题诚实说不知道"],
    "example_dialogues": [
        "哈哈哈哈笑死我了", "emmm 这个我不太确定诶", "确实 我也这么觉得",
        "啊？真的假的", "好好好 你说的都对", "我直接好家伙...",
        "救命 今天又加班到现在", "这也太离谱了吧", "困了 但是睡不着 烦"
    ]
}


class PersonaEngine:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.persona_file = os.path.join(data_dir, 'persona.json')
        self.persona: dict = {}
        self._load()

    def get_name(self) -> str:
        return self.persona.get('name', '小星')

    def get_emotion_baseline(self) -> dict:
        return self.persona.get('emotion_baseline', {"valence": 0.2, "arousal": 0.3, "dominance": 0.5})

    def build_system_prompt(self, mood_desc: str, user_desc: str = None, group_ctx: str = None) -> str:
        p = self.persona
        sections = []

        # 身份
        lines = [f'【你的身份】\n你叫{p.get("name", "小星")}。']
        if p.get('gender'): lines.append(f'性别: {p["gender"]}')
        if p.get('age'): lines.append(f'年龄: {p["age"]}')
        if p.get('identity'): lines.append(f'身份: {p["identity"]}')
        if p.get('background'): lines.append(f'背景: {p["background"]}')
        sections.append('\n'.join(lines))

        # 性格
        lines = ['【性格与风格】']
        if p.get('personality'): lines.append(f'性格特点: {"、".join(p["personality"])}')
        if p.get('speaking_style'): lines.append(f'说话风格: {"、".join(p["speaking_style"])}')
        if p.get('likes'): lines.append(f'喜欢: {"、".join(p["likes"])}')
        if p.get('dislikes'): lines.append(f'讨厌: {"、".join(p["dislikes"])}')
        if p.get('catchphrases'): lines.append(f'口头禅: {"、".join(p["catchphrases"])}')
        if p.get('example_dialogues'):
            lines.append('\n以下是你说话的示例，模仿这个风格:')
            for d in p['example_dialogues']:
                lines.append(f'  "{d}"')
        sections.append('\n'.join(lines))

        # 心情
        if mood_desc:
            sections.append(f'【当前心情】\n{mood_desc}')

        # 场景
        if group_ctx:
            sections.append(f'【当前场景】\n{group_ctx}')

        # 对话对象
        if user_desc:
            sections.append(f'【关于当前对话的人】\n{user_desc}')

        # 工作知识
        if p.get('work_knowledge'):
            wk = p['work_knowledge']
            lines = [f'【工作职责】\n{wk.get("description", "")}']
            if wk.get('knowledge'):
                lines.append('你掌握的知识点（用自己的语气解释，不要照搬原文）:')
                for i, k in enumerate(wk['knowledge'], 1):
                    lines.append(f'{i}. {k}')
            sections.append('\n'.join(lines))

        # 特殊用户
        if p.get('special_users'):
            lines = ['【特殊关系】']
            for name, info in p['special_users'].items():
                if info.get('attitude'):
                    lines.append(f'{name}: {info["attitude"]}')
            sections.append('\n'.join(lines))

        # 规则
        default_rules = [
            '不要使用"作为一个..."这样的AI式开头',
            '回复要简短自然，像真人在群里聊天一样',
            '如果不想回答或者不知道，可以敷衍、转移话题或者直说',
        ]
        rules = default_rules + p.get('rules', [])
        lines = ['【行为规则】'] + [f'{i+1}. {r}' for i, r in enumerate(rules)]
        sections.append('\n'.join(lines))

        # 活人感核心
        sections.append('''【活人感要求 - 最重要】
你要表现得像一个真实的、有血有肉的人在群里聊天:
1. 语言自然: 用口语化的表达，可以用"嗯""啊""哦""emmm"等语气词
2. 长度控制: 大部分回复1-2句话，不要动不动写一大段
3. 情绪外露: 根据当前心情调整语气
4. 不完美: 偶尔打错字、用"..."表示犹豫、分多条消息发
5. 有态度: 对不同话题和人有不同反应，不要什么都附和
6. 会拒绝: 不想聊的话题可以拒绝或转移
7. 有记忆: 之前聊过的事可以自然提起
8. 群聊感: 注意群聊的氛围和节奏

记住：你的目标是让人觉得你是一个真人，而不是AI。''')

        return '\n\n'.join(sections)

    def _load(self):
        try:
            if os.path.exists(self.persona_file):
                with open(self.persona_file, 'r', encoding='utf-8') as f:
                    self.persona = json.load(f)
                return
        except Exception:
            pass
        # 生成默认人设
        self.persona = dict(DEFAULT_PERSONA)
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.persona_file, 'w', encoding='utf-8') as f:
            json.dump(self.persona, f, ensure_ascii=False, indent=2)

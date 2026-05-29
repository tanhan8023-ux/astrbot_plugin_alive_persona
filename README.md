# astrbot_plugin_alive_persona

AstrBot 活人感人设插件，当前默认人设为 **系尔**。

## 功能

- 在 LLM 请求前注入人设、情绪、上下文、记忆和回复策略
- 记录短期聊天上下文，让 bot 能接住前文
- 记录偏好、状态、感谢、道歉、约定等陪伴型记忆
- 根据心情、熟悉度、生活节律和群聊氛围调整回复策略
- 支持“贴人设但不死板”的弹性人设锚点
- 清理重复表达、客服式尾巴和过长回复
- 支持 `/persona`、`/mood`、`/memory`、`/alive`

## 人设文件

默认人设在：

```text
data/persona.json
```

如果你在本地放了：

```text
data/persona_private.json
```

插件会优先读取 `persona_private.json`，没有这个文件才读取 `persona.json`。

## 常用配置

- `name`: 角色名字
- `identity`: 角色身份
- `personality`: 性格特点
- `speaking_style`: 说话风格
- `rules`: 行为规则
- `example_dialogues`: 示例回复
- `special_users`: 特殊用户关系配置
- `work_knowledge`: 可选知识库
- `max_reply_chars`: 回复软长度限制
- `short_reply_rate`: 低概率短回比例
- `light_reply_rate`: 普通闲聊低存在感轻回比例
- `persona_flexibility`: 人设表达弹性
- `trait_anchor_rate`: 显性体现人设特征的概率
- `catchphrase_cooldown`: 是否避免连续复用口头禅
- `identity_mention_policy`: 身份背景主动提及策略
- `recent_context_limit`: 注入最近聊天上下文条数

## 活人感机制

- 生活节律：根据清晨、白天、晚上、深夜调整回复状态
- 低存在感轻回：非求助、非情绪消息可低概率压成短回
- 人设弹性：核心身份稳定，但不是每句话都展示设定
- 口头禅冷却：避免连续多轮机械复用常用短语
- 陪伴记忆：记录疲惫、身体、心情等最近状态，并在24小时内自然影响回复

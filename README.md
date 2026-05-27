# astrbot_plugin_alive_persona

AstrBot 活人感人设插件 demo 版。

这个仓库里的 `data/persona.json` 是公开演示人设，不包含私人角色设定。你可以直接安装使用，也可以把它复制一份改成自己的角色。

## 功能

- 在 LLM 请求前注入人设、情绪、上下文、记忆和回复策略
- 记录短期聊天上下文，让 bot 能接住前文
- 记录偏好、状态、感谢、道歉、约定等陪伴型记忆
- 根据心情、熟悉度和群聊氛围调整回复策略
- 清理重复表达、客服式尾巴和过长回复
- 支持 `/persona`、`/mood`、`/memory`、`/alive`

## 自定义人设

公开 demo 人设在：

```text
data/persona.json
```

建议把私人人设另存为类似下面的文件名：

```text
data/persona_你的角色名.json
```

如果你想本地自动优先使用私人人设，请保存为：

```text
data/persona_private.json
```

插件会优先加载 `data/persona_private.json`，不存在时才加载公开 demo 的 `data/persona.json`。这类私人人设文件已被 `.gitignore` 忽略，不会被提交到 GitHub。

## 配置项

`data/persona.json` 中常用字段：

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
- `recent_context_limit`: 注入最近聊天上下文条数

## 活人感机制

- 生活节律：根据清晨、白天、晚上、深夜调整回复状态
- 低存在感轻回：非求助、非情绪消息可低概率压成短回
- 陪伴记忆：记录疲惫、身体、心情等最近状态，并在24小时内自然影响回复
- 私人人设保护：本地 `persona_private.json` 优先加载，公开仓库保持 demo 人设

## 隐私提醒

提交或分享前检查：

```bash
git status --short
```

不要提交包含真实角色、真实用户关系、私密知识库或聊天记忆的文件。`data/memory.json` 和 `data/persona_*.json` 默认已忽略。

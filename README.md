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
data/persona_private.json
data/persona_你的角色名.json
```

这类文件已被 `.gitignore` 忽略，不会被提交到 GitHub。要让插件实际使用你的私人人设，可以把私人人设内容复制到本地的 `data/persona.json`，但不要提交这个改动。

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
- `recent_context_limit`: 注入最近聊天上下文条数

## 隐私提醒

提交或分享前检查：

```bash
git status --short
```

不要提交包含真实角色、真实用户关系、私密知识库或聊天记忆的文件。`data/memory.json` 和 `data/persona_*.json` 默认已忽略。

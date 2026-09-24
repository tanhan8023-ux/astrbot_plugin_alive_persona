# astrbot_plugin_alive_persona

AstrBot 活人感人设插件，当前默认人设为 **系尔**。

## 功能

- 在 LLM 请求前注入人设、情绪、上下文、记忆和回复策略
- 记录短期聊天上下文，让 bot 能接住前文
- 记录偏好、状态、感谢、道歉、约定等陪伴型记忆
- 根据心情、熟悉度、生活节律和群聊氛围调整回复策略
- 支持“贴人设但不死板”的弹性人设锚点
- 清理重复表达、客服式尾巴和过长回复
- 支持 `/persona`、`/mood`、`/memory`、`/alive`、`/forget`

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

仓库还提供了一个独立的人设文件：

```text
data/persona_nne_2477.json
```

它对应“诺奈 NNE-2477”人设，不会覆盖现有的 `persona_private.json`。启用方式有两种：

1. 在 AstrBot 插件配置里设置 `persona_file` 为 `persona_nne_2477.json`。
2. 或将它复制为 `data/persona_private.json`，作为当前实例的私有人设。

配置项优先级为：`persona_file`、环境变量 `ALIVE_PERSONA_FILE`、`persona_private.json`、`persona.json`。

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
- 会话情绪隔离：不同群聊不会互相污染心情
- 记忆去重与清除：重复事实会合并，可用 `/forget` 清除自己的长期记忆
- 技术回复自适应长度：排查问题时不会套用闲聊的短回复限制


## 蛇蛇机单角色人设与记忆互通

版本 1.1.0 增加蛇蛇机桥接。一个插件实例只能绑定蛇蛇机中的一个角色，并且只同步配置的本人 QQ ID：

- 共享角色姓名、身份、背景、人物描述、系统提示词、自定义提示词和初次见面消息
- 双向合并长期记忆，使用 UUID、版本号和删除墓碑防止重复或离线复活
- 双向保存最近 50 条文本上下文，每次回复最多注入 12 条
- 共享近期上下文只作为隐藏提示，不伪造 QQ 或蛇蛇机聊天气泡
- 其他 QQ 用户、群成员和蛇蛇机其他角色不会进入共享数据

### AstrBot 配置

1. AstrBot 版本至少为 4.18.0。
2. 在插件配置中开启 `bridge_enabled`。
3. 将 `bridge_allowed_user_id` 填为本人的 QQ ID。
4. 在 AstrBot Access Key 管理中创建只包含 `plugin` 权限的 Key。
5. Docker 映射 `6185:6185`，让 AstrBot 监听局域网地址，并在宿主机防火墙中仅对“私有网络”放行 TCP 6185。
6. 在蛇蛇机“设置 → AI 行为与记忆 → AstrBot 人设绑定”中填写 `http://电脑局域网IP:6185` 和 Access Key。

同一 Wi‑Fi、手机热点和电脑热点均可使用，但手机与 AstrBot 宿主机必须处在同一个局域网。不要开放公网端口。

### 数据文件

桥接元数据位于 `data/sheshe_bridge.json`。手机只通过鉴权接口同步，不会直接修改 `persona.json` 或 `memory.json`。旧版 `memory.json` 第一次迁移 UUID 前会自动创建 `memory.json.legacy.bak`。解除绑定只停止同步，不会自动删除两边的人设或记忆。

# 多 Agent 群聊 v1 数据示例

## 1) 群聊配置 JSON 示例

```json
{
  "group_id": "1024001",
  "group_name": "产品策略讨论群",
  "group_intro": "围绕需求优先级、增长实验和版本节奏进行讨论",
  "group_topic": "Q2 产品路线",
  "group_mode": "semi_active",
  "default_agent_id": "moyuan",
  "allowed_agent_ids": ["moyuan", "assistant_ops"],
  "trigger_keywords": ["排期", "上线", "复盘"],
  "trigger_settings": {
    "at_reply": true,
    "name_reply": true,
    "quote_reply": true,
    "keyword_trigger": true,
    "admin_force_wakeup": true
  },
  "cooldown_seconds": 8,
  "anti_conflict_enabled": true,
  "max_reply_length": 260,
  "context_turn_n": 3,
  "response_mode": "normal",
  "allow_proactive_reply": false,
  "allow_followup_short_reply": false,
  "allow_followup_multi_agent": false,
  "followup_max_agents": 1,
  "followup_max_reply_length": 0,
  "group_memory_enabled": true,
  "group_memory_path": "group_memory/1024001",
  "allow_group_rag": true,
  "allow_cross_domain_analysis": true
}
```

- `followup_max_reply_length = 0` 表示补刀字数不设硬上限（仅作可视化参数占位）。

## 2) 群成员结构示例

```json
[
  {
    "member_id": "10001",
    "member_name": "Alice",
    "member_type": "admin",
    "is_admin": true,
    "muted": false,
    "speak_enabled": true,
    "visible": true
  },
  {
    "member_id": "10002",
    "member_name": "Bob",
    "member_type": "user",
    "is_admin": false,
    "muted": false,
    "speak_enabled": true,
    "visible": true
  },
  {
    "member_id": "moyuan",
    "member_name": "沐原",
    "member_type": "agent",
    "is_admin": false,
    "is_default_agent": true,
    "muted": false,
    "speak_enabled": true,
    "visible": true,
    "trigger_keywords": ["排期", "方案"]
  }
]
```

## 3) 群记忆路径默认规则

- 群聊配置存储：`configs/group_chats.json`
- 群聊记忆默认目录：`group_memory/<group_id>/`
- 物理隔离约束：
  - `group_memory/群A` 仅服务群 A
  - `group_memory/群B` 仅服务群 B
  - 群聊记忆与私聊记忆目录分离，不混用
- 常规群聊 RAG 仅检索当前 `group_id` 对应目录

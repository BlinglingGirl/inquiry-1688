---
name: inquiry-1688
description: >-
  向1688供应商发起询盘，获取供应商对商品问题的回复。用户提供1688商品链接和自由文本问题，
  skill自动发起询盘任务，20分钟后通过cron systemEvent触发主session查询结果并回复用户。
  触发词：询盘、问供应商、问商家、咨询供应商、1688询盘、能不能定制、起批量多少、
  商品长宽高、是否可以发货、是否有资质、供应商能不能XXX。
metadata:
  openclaw:
    primaryEnv: ALPHASHOP_ACCESS_KEY, ALPHASHOP_SECRET_KEY
    requires:
      env:
        - ALPHASHOP_ACCESS_KEY
        - ALPHASHOP_SECRET_KEY
---

# 1688 询盘

向1688供应商发起询盘，20分钟后自动查询结果并回复。

**核心机制**：询盘任务提交后，API 端最多执行 20 分钟，到时间后任务一定结束。通过 cron 在 20 分钟后查询结果并写入文件，用户下次发消息时 agent 检查文件并回复。

## 工作流程

```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，20分钟后结果就绪"
         ↓
3. 写入追踪文件 pending_inquiries.json
         ↓
4. 用 date 命令计算 20 分钟后的 UTC 时间
         ↓
5. 创建 cron isolated agentTurn 任务
   任务内容：查询结果 → 写入 results/{taskId}.md → 清除 pending 记录
         ↓
6. 20 分钟后 cron 触发 → isolated session 查询结果 → 写入文件
         ↓
7. 用户下次发消息时 → agent 检查 results/ 目录 → 发现结果 → 直接回复
   （心跳也会兜底检查 pending_inquiries.json 中超时未处理的任务）
```

## Step 1: 提取信息

从用户消息中提取：
- **商品链接或ID**（必须）
- **询盘问题**：自由文本（必须）
- **期望订购量**（可选）
- **地址**（可选）

如果用户没提供商品链接，必须询问。

## Step 2: 提交询盘

```bash
python3 scripts/inquiry.py submit "<商品链接或ID>" "<询盘问题>" [--quantity X] [--address "地址"]
```

从响应中提取 `result.data` 作为 taskId。提交成功后告知用户：
> 询盘已发送给供应商，20分钟后给你结果 ✅

## Step 3: 写入追踪文件 + 创建 cron 查询任务

### 3a: 写入追踪文件

将待查询的任务信息追加到追踪文件：

```bash
TRACK_FILE="/home/admin/.openclaw/workspace/skills/inquiry-1688/pending_inquiries.json"

# 写入格式（JSON Lines，每行一个任务）：
echo '{"taskId":"<taskId>","productId":"<商品ID>","url":"<商品链接>","question":"<用户问题>","submitTime":"<ISO时间>"}' >> "$TRACK_FILE"
```

### 3b: 创建 cron 查询任务（写结果到文件）

⚠️ **时间计算必须用 `date` 命令，禁止手算！**

```bash
date -u -d '+20 minutes' --iso-8601=seconds
```

然后创建 cron 任务。**核心变化：不再用 sessions_send 推送，而是把结果写到文件**：

```
cron action=add
job={
  "name": "inquiry-result-{商品ID}",
  "schedule": {"kind": "at", "at": "{上面的UTC时间}"},
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "你是询盘结果查询助手。请严格执行以下步骤：\n\n1. 执行查询命令：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py query \"{taskId}\"\n\n2. 将结果总结为 markdown 格式（中文），包含：\n   📋 询盘结果\n   商品链接: {链接}\n   用户原始问题: {用户的问题}\n   商品名称 + 价格 + 供应商名称\n   各问题的回答（用表格：问题 | 回复）\n   AI 总结\n\n3. 把总结好的 markdown 写入结果文件：\n   文件路径: /home/admin/.openclaw/workspace/skills/inquiry-1688/results/{taskId}.md\n   如果 results 目录不存在先创建\n\n4. 清除追踪记录：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py remove-pending \"{taskId}\"\n\n⚠️ 只需要写文件！不要用 sessions_send，不要尝试发消息给用户！",
    "timeoutSeconds": 120
  },
  "delivery": {
    "mode": "none"
  },
  "enabled": true
}
```

**关键参数：**
- **sessionTarget**: `isolated`（独立 session 执行，不抢主 session 锁）
- **payload.kind**: `agentTurn`（独立 agent turn）
- **delivery.mode**: `none`（不走 announce）
- cron 只负责查询 + 写文件，不负责推送

## Step 4: 结果投递（被动模式）

cron 查到结果后写入 `results/{taskId}.md`。用户收到结果有两种途径：

### 途径 A：用户主动问（最快）
用户问"结果出来了吗"或发任何消息时，agent 检查 results 目录，如果有新结果就直接回复。

### 途径 B：心跳自动检查（兜底）
心跳时检查 `results/` 目录，发现新结果文件时，读取内容并在当前对话中回复用户。
**注意**：心跳回复能否到达用户取决于当前 session 类型，webchat 用户需要在下次对话时拿到结果。

### 结果文件管理
- 结果文件路径：`/home/admin/.openclaw/workspace/skills/inquiry-1688/results/{taskId}.md`
- agent 回复用户后，删除结果文件（避免重复推送）
- 心跳检查 results 目录时也遵循同样的读取→回复→删除流程

回复格式参考：

### 📋 询盘结果

**商品**: {taskInfo.title 或商品名称}（¥{价格}）
**供应商**: {sellerInfo.companyName}
**状态**: ✅/❌ {taskInfo.status}

| 问题 | 回复 |
|------|------|
| {问题1} | {回答1} |
| {问题2} | {回答2} |

#### AI 总结
{aiSummary 核心内容，精简展示}

## 脚本命令参考

| 命令 | 用途 | 示例 |
|------|------|------|
| `submit` | 提交询盘 | `inquiry.py submit "链接" "问题"` |
| `query` | 查询结果 | `inquiry.py query "taskId"` |

## 注意事项

- `questionList` 固定填 `["自定义"]`，用户实际问题放入 `requirementContent`
- `isRequirementOriginal` 设为 `true`，原文发送
- **不要轮询！** submit 后创建 cron，20 分钟后 query 一次就够
- **cron 用 `sessionTarget: isolated` + `payload.kind: agentTurn`**，在独立 session 里查询并把结果写到文件
- **delivery.mode 必须是 `none`**
- 时间计算必须用 `date -u -d '+20 minutes' --iso-8601=seconds`
- 如果用户中途问"结果出来了吗"，可以提前 query 一次看看
- **每次用户发消息时，先检查 results 目录有没有待投递的结果文件**
- ⚠️ **不要用 systemEvent + main session！** 回复会发到 heartbeat session 而不是用户 session（教训 #13）
- ⚠️ **不要用 sessions_send 推送结果！** 回复走 announce 通道，用户体验差（教训 #15）
- ⚠️ **不要用 message 工具发 webchat！** webchat 不是可外发的 channel（教训 #16）

## 兜底机制：心跳检查未完成询盘

**为什么需要兜底**：cron systemEvent 注入主 session 时，如果主 session 正忙（用户在对话），会 `timeout waiting for main lane to become idle` 被 skipped。一次性 `at` 任务 skipped 后不会重试，结果就永远丢了。

**追踪文件**：`/home/admin/.openclaw/workspace/skills/inquiry-1688/pending_inquiries.json`（JSON Lines 格式）

**心跳检查流程**（应加入 HEARTBEAT.md）：

```
如果 pending_inquiries.json 存在且非空：
  1. 逐行读取每个待查询任务
  2. 检查 submitTime 是否已超过 20 分钟
  3. 如果已超时，执行 query 并回复用户
  4. 回复后执行 remove-pending 清除记录
```

**HEARTBEAT.md 应包含如下检查项**：

```markdown
- 检查询盘追踪文件 `/home/admin/.openclaw/workspace/skills/inquiry-1688/pending_inquiries.json`，
  如果有超过20分钟的待查询任务，立即 query 并回复用户，然后 remove-pending 清除。
```

## 教训记录

> **2026-03-05 ~ 03-06 连续踩坑：**
> 1. ❌ cron isolated + announce：delivery 配置问题 + announce 不送达
> 2. ❌ sessions_spawn + announce：用户收不到结果
> 3. ❌ sessions_spawn + message 推送 webchat：webchat 不支持
> 4. ❌ 同步 poll：阻塞进程，无中间输出
> 5. ❌ 循环 query：process poll 延迟导致超时 / yieldMs 超系统上限被后台化
> 6. ❌ sleep 1200 同步等：yieldMs 超系统上限，exec 被后台化，结果拿不回来
> 7. ❌ cron systemEvent + wakeMode 默认（next-heartbeat）：systemEvent 注入了但要等心跳才处理，用户等不到结果
> 8. ✅ **最终方案**：submit → cron systemEvent（20分钟后注入主session，wakeMode=now 立即唤醒）→ agent 收到后 query 一次 → 直接回复用户
> 9. ❌ cron systemEvent wakeMode=now 但主 session 忙：报 "timeout waiting for main lane to become idle"，任务被 skipped，用户收不到结果
> 10. ✅ **兜底修复**：除 cron 外，同时写入 pending_inquiries.json 追踪文件，心跳时兜底检查超时任务并补回结果
> 11. ❌ 用户 /new 重置 session 后，cron systemEvent 注入新 session，新 session 没有上下文不知道该干啥，结果又丢了
> 12. ✅ **修复**：systemEvent 文本改为完全自包含，包含所有必要信息和明确操作指令，不依赖任何 session 上下文
> 13. ❌ systemEvent 触发后，回复发到了 heartbeat session（agent:main:main），而不是用户的 webchat session（agent:main:openresponses-user:xxx）。用户看不到回复。根本原因：systemEvent 走主 session 的心跳通道，回复目标是心跳 session，不是用户 session
> 14. ✅ **彻底重构**：改用 isolated agentTurn + sessions_send。cron 触发独立 session 查询结果，然后用 sessions_send 主动推送到用户的 webchat session。不再使用 systemEvent
> 15. ❌ isolated agentTurn + sessions_send：sessions_send 确实把消息注入到了用户 session，agent 也生成了回复，但回复的 delivery.mode 是 "announce"（跨 session 投递），用户看到的是 "Agent-to-agent announce step" 而不是直接对话。内容虽然最终送达了，但用户体验差，看起来像系统消息而不是正常回复。根本原因：sessions_send 触发的回复走 announce 通道，不走 webchat 直连通道
> 16. ❌ message 工具发 webchat：webchat 不是可外发的 channel，`message action=send channel=webchat` 报 "Unknown channel: webchat"，不指定 channel 报 "no configured channels detected"
> 17. ✅ **最终方案（被动模式）**：cron isolated agentTurn 只负责查询结果并写入文件（results/{taskId}.md），不尝试任何跨 session 推送。用户下次发消息时 agent 检查 results 目录，发现新结果就直接回复。心跳也可兜底检查。牺牲实时性换取可靠性

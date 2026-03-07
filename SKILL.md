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

**核心机制**：询盘任务提交后，API 端最多执行 20 分钟，到时间后任务一定结束。通过 cron 在 20 分钟后向主 session 注入 systemEvent，触发 agent 查询结果并回复用户。

## 工作流程

```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，20分钟后给你结果"
         ↓
3. 记录用户当前 session key（从 runtime 或 sessions_list 获取）
         ↓
4. 用 date 命令计算 20 分钟后的 UTC 时间
         ↓
5. 创建 cron isolated agentTurn 任务
   任务内容：查询结果 + 用 sessions_send 发到用户 session
         ↓
6. 20 分钟后 cron 触发 → isolated session 查询结果 → sessions_send 发给用户
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

## Step 3: 获取用户 session key + 写入追踪文件 + 创建 cron 任务

### 3a: 获取用户当前 session key

在当前对话中，通过 `sessions_list` 找到当前用户的 webchat session key。
session key 格式通常为 `agent:main:openresponses-user:XXXXXX`。

**⚠️ 必须在提交询盘时就记录 session key，因为后续 cron 要用它发送结果。**

### 3b: 写入追踪文件（兜底机制）

将待查询的任务信息追加到追踪文件，用于心跳兜底检查：

```bash
TRACK_FILE="/home/admin/.openclaw/workspace/skills/inquiry-1688/pending_inquiries.json"

# 写入格式（JSON Lines，每行一个任务）：
echo '{"taskId":"<taskId>","productId":"<商品ID>","url":"<商品链接>","question":"<用户问题>","submitTime":"<ISO时间>","sessionKey":"<用户session key>"}' >> "$TRACK_FILE"
```

### 3c: 创建 cron isolated agentTurn 任务

⚠️ **时间计算必须用 `date` 命令，禁止手算！**

```bash
date -u -d '+20 minutes' --iso-8601=seconds
```

然后创建 cron 任务：

```
cron action=add
job={
  "name": "inquiry-result-{商品ID}",
  "schedule": {"kind": "at", "at": "{上面的UTC时间}"},
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "你是询盘结果查询助手。请严格执行以下步骤：\n\n1. 执行查询命令：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py query \"{taskId}\"\n\n2. 将结果总结为以下格式：\n   📋 询盘结果\n   商品链接: {链接}\n   用户原始问题: {用户的问题}\n   商品名称 + 价格\n   供应商名称\n   各问题的回答（用表格）\n\n3. 用 sessions_send 工具把总结结果发到用户 session：\n   sessionKey: \"{用户session key}\"\n   message: （上面总结好的结果）\n\n4. 发送后，清除追踪记录：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py remove-pending \"{taskId}\"\n\n⚠️ 必须用 sessions_send 发送！不要只是回复当前 session！",
    "timeoutSeconds": 120
  },
  "delivery": {
    "mode": "none"
  },
  "deleteAfterRun": true,
  "wakeMode": "now"
}
```

**关键参数：**
- **sessionTarget**: `isolated`（独立 session 执行，不抢主 session 锁）
- **payload.kind**: `agentTurn`（独立 agent turn）
- **delivery.mode**: `none`（不走 announce，由 agentTurn 内部用 sessions_send 推送）
- **deleteAfterRun**: `true`（一次性任务）

## Step 4: isolated session 查询并推送结果

20 分钟后 cron 触发 isolated agentTurn，该 session 会：
1. 执行 `inquiry.py query` 获取结果
2. 总结结果
3. 用 `sessions_send(sessionKey, message)` 推送到用户 session
4. 执行 `inquiry.py remove-pending` 清除追踪记录

用户在其 webchat session 中会直接收到结果消息。

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
- **cron 用 `sessionTarget: isolated` + `payload.kind: agentTurn`**，在独立 session 里查询并用 `sessions_send` 推送结果
- **delivery.mode 必须是 `none`**，结果通过 sessions_send 发送，不走 announce
- 时间计算必须用 `date -u -d '+20 minutes' --iso-8601=seconds`
- **必须在提交时记录用户的 session key**，cron agentTurn 需要它来 sessions_send
- 如果用户中途问"结果出来了吗"，可以提前 query 一次看看
- ⚠️ **不要用 systemEvent + main session！** 回复会发到 heartbeat session 而不是用户 session（教训 #13）

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

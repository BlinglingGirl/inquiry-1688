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
3. 用 date 命令计算 20 分钟后的 UTC 时间
         ↓
4. 创建 cron 一次性任务（systemEvent → main session）
   内容："询盘任务 {taskId} 已到20分钟，请立即 query 并回复用户"
         ↓
5. 20 分钟后 cron 触发 → agent 收到 systemEvent → query 一次 → 回复用户
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

## Step 3: 写入追踪文件 + 创建 cron systemEvent

### 3a: 写入追踪文件（兜底机制）

将待查询的任务信息追加到追踪文件，用于心跳兜底检查：

```bash
# 追踪文件路径
TRACK_FILE="/home/admin/.openclaw/workspace/skills/inquiry-1688/pending_inquiries.json"

# 写入格式（JSON Lines，每行一个任务）：
echo '{"taskId":"<taskId>","productId":"<商品ID>","url":"<商品链接>","question":"<用户问题>","submitTime":"<ISO时间>","cronJobId":"<cron任务ID>"}' >> "$TRACK_FILE"
```

### 3b: 创建 cron systemEvent

⚠️ **时间计算必须用 `date` 命令，禁止手算！**

```bash
# 获取20分钟后的 UTC ISO-8601 时间戳
date -u -d '+20 minutes' --iso-8601=seconds
```

然后创建 cron 任务：

```
cron action=add
job={
  "name": "inquiry-result-{商品ID}",
  "schedule": {"kind": "at", "at": "{上面的UTC时间}"},
  "sessionTarget": "main",
  "payload": {
    "kind": "systemEvent",
    "text": "🔔 询盘结果待查询——这是一个定时任务，不依赖任何 session 上下文。\n\n## 你必须执行以下操作：\n\n1. 执行查询命令：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py query \"{taskId}\"\n\n2. 将查询结果总结后回复用户（用户之前问的问题如下）：\n   - 商品链接: {链接}\n   - 询盘问题: {用户的问题}\n\n3. 回复格式参考（直接发给用户，不需要额外上下文）：\n   📋 询盘结果\n   商品: xxx（¥价格）\n   供应商: xxx\n   各问题的回答\n\n4. 回复用户后，清除追踪记录：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py remove-pending \"{taskId}\"\n\n⚠️ 即使当前 session 没有之前的对话记录，也必须执行上述操作并直接回复用户！"
  },
  "deleteAfterRun": true,
  "wakeMode": "now"
}
```

**关键参数：**
- **sessionTarget**: `main`（注入到主 session，不是 isolated）
- **payload.kind**: `systemEvent`（不是 agentTurn）
- **deleteAfterRun**: `true`（一次性任务，执行后自动删除）

## Step 4: 收到 systemEvent 后查询并回复

20 分钟后 agent 收到 systemEvent，执行：

```bash
python3 scripts/inquiry.py query "{taskId}"
```

**回复用户后，务必清除追踪记录：**

```bash
python3 scripts/inquiry.py remove-pending "{taskId}"
```

拿到 JSON 结果后，按以下格式总结回复用户：

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
- cron 用 `sessionTarget: main` + `payload.kind: systemEvent`，直接注入主 session
- 时间计算必须用 `date -u -d '+20 minutes' --iso-8601=seconds`
- ⚠️ **cron 必须设置 `wakeMode: now`**，否则 systemEvent 要等心跳才处理，用户等不到结果（教训：2026-03-06 默认 next-heartbeat 导致 systemEvent 没被及时处理）
- 如果用户中途问"结果出来了吗"，可以提前 query 一次看看

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

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

## Step 3: 创建 cron systemEvent

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
    "text": "🔔 询盘提醒：任务 {taskId} 已到20分钟，请立即查询结果并回复用户。\n\n请执行：\npython3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py query \"{taskId}\"\n\n查询后按以下格式总结回复用户：\n\n商品链接: {链接}\n询盘问题: {用户的问题}"
  },
  "deleteAfterRun": true
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
- 如果用户中途问"结果出来了吗"，可以提前 query 一次看看

## 教训记录

> **2026-03-05 ~ 03-06 连续踩坑：**
> 1. ❌ cron isolated + announce：delivery 配置问题 + announce 不送达
> 2. ❌ sessions_spawn + announce：用户收不到结果
> 3. ❌ sessions_spawn + message 推送 webchat：webchat 不支持
> 4. ❌ 同步 poll：阻塞进程，无中间输出
> 5. ❌ 循环 query：process poll 延迟导致超时 / yieldMs 超系统上限被后台化
> 6. ❌ sleep 1200 同步等：yieldMs 超系统上限，exec 被后台化，结果拿不回来
> 7. ✅ **最终方案**：submit → cron systemEvent（20分钟后注入主session）→ agent 收到后 query 一次 → 直接回复用户

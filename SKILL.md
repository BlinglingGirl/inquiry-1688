---
name: inquiry-1688
description: >-
  向1688供应商发起询盘，获取供应商对商品问题的回复。用户提供1688商品链接和自由文本问题，
  skill自动发起询盘任务，等待供应商回复后总结结果。
  webchat场景在当前session同步轮询；外部channel（钉钉等）用sessions_spawn异步轮询+message主动推送。
  触发词：询盘、问供应商、问商家、咨询供应商、1688询盘、能不能定制、起批量多少、
  商品长宽高、是否可以发货、是否有资质、供应商能不能XXX。
---

# 1688 询盘

向1688供应商发起询盘，等待结果，自动总结回复。

## 工作流程（按 channel 区分）

### webchat 场景（同步轮询）
```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，正在等待"
         ↓
3. 当前 session 直接运行 poll 命令（每30秒查一次，最多20分钟）
         ↓
4. 结果出来后直接回复用户
```

### 外部 channel 场景（钉钉/Telegram/Discord 等，异步推送）
```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，有结果会通知你"
         ↓
3. sessions_spawn 启动子agent → 后台轮询
         ↓
4. 子agent poll 拿到结果后，用 message 工具主动推送给用户
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

从响应中提取 `result.data` 作为 taskId。

## Step 3: 等待结果（按 channel 区分）

### 方案 A：webchat — 当前 session 同步轮询

直接在当前 session 中运行 poll 命令，阻塞等待结果：

```bash
python3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py poll "{taskId}"
```

提交后先告知用户：
> 询盘已发送，正在等供应商回复，大概需要几分钟，请稍等... ⏳

poll 命令会每30秒查一次，最多等20分钟。结果出来后**直接在当前会话回复用户**，不会丢。

### 方案 B：外部 channel（钉钉/Telegram/Discord 等）— sessions_spawn 异步 + message 推送

使用 `sessions_spawn` 启动子agent后台轮询。

**调用参数：**
- **task**: 轮询指令（见下方模板）
- **runTimeoutSeconds**: `1400`
- **label**: `inquiry-poll-{商品ID}`

**task 模板：**

```
请轮询1688询盘任务结果并总结，然后主动推送给用户。

执行步骤：
1. 先等待60秒（给询盘初始处理时间）：
   sleep 60

2. 运行轮询（每30秒查一次，最多20分钟）:
   python3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py poll "{taskId}"

3. 轮询结束后解析JSON结果，重点关注：
   - taskInfo.status（任务状态）
   - aiSummary（AI总结，markdown格式）
   - supplierCompare[].inquiryAnswers（各问题回复）
   - supplierCompare[].sellerInfo（供应商信息）
   - supplierCompare[].messages（完整聊天记录）

4. 按以下格式总结：

### 📋 询盘结果

**商品**: {商品名称}
**询盘问题**: {原始问题}
**任务状态**: {status}

#### AI 总结
{aiSummary内容}

#### 供应商回复
**{companyName}**
- 进度: {progress}
- 回复详情: {inquiryAnswers}

5. 如果超时仍未完成，说明当前进度。

6. 总结完成后，使用 message 工具主动推送结果给用户：
   message action=send, channel={channel}, target={target}, message="{总结内容}"

原始信息：
- 任务ID: {taskId}
- 商品链接: {链接}
- 询盘问题: {用户的问题}
- 推送 channel: {channel}
- 推送 target: {target}
```

## 结果展示格式

拿到 poll/query 的 JSON 结果后，按以下格式总结回复：

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
| `query` | 单次查询 | `inquiry.py query "taskId"` |
| `poll` | 轮询等结果 | `inquiry.py poll "taskId"` |

## 注意事项

- `questionList` 固定填 `["自定义"]`，用户实际问题放入 `requirementContent`
- `isRequirementOriginal` 设为 `true`，原文发送
- **webchat 必须用同步轮询（方案A）**，不要用 sessions_spawn！webchat 不支持 message 主动推送，announce 也不会主动通知用户（教训：2026-03-06 连续多次 announce 结果用户收不到）
- 外部 channel 用异步轮询（方案B），通过 message 工具主动推送结果
- 如果需要手动查询结果，可直接运行 `inquiry.py query "{taskId}"`

## 教训记录

> **2026-03-05 ~ 03-06 连续踩坑：**
> 1. ❌ cron + delivery 方案：delivery 没配 channel → 报错；手算 UTC 时间错 → 延迟触发；配置都对了 announce 仍不送达
> 2. ❌ sessions_spawn + announce 方案：子agent 跑完了但用户看不到结果，必须用户主动发消息才能触发
> 3. ❌ sessions_spawn + message 推送 webchat：webchat 不是 channel plugin，不支持 message 推送
> 4. ✅ **最终方案**：webchat 用同步轮询直接回复；外部 channel 用 sessions_spawn + message 主动推送

---
name: inquiry-1688
description: >-
  向1688供应商发起询盘，获取供应商对商品问题的回复。用户提供1688商品链接和自由文本问题，
  skill自动发起询盘任务，等待供应商回复后总结结果。
  询盘任务最多执行20分钟，到时间后一定有最终结果。
  webchat场景在当前session循环query；外部channel（钉钉等）用sessions_spawn异步轮询+message主动推送。
  触发词：询盘、问供应商、问商家、咨询供应商、1688询盘、能不能定制、起批量多少、
  商品长宽高、是否可以发货、是否有资质、供应商能不能XXX。
---

# 1688 询盘

向1688供应商发起询盘，等待结果，自动总结回复。

**核心机制**：询盘任务提交后，API 端最多执行 20 分钟，到时间后任务状态一定会变为 FINISHED/FAILED/CANCELED。所以 **20 分钟后 query 一次，一定能拿到最终结果**。

## 工作流程（按 channel 区分）

### webchat 场景（agent 自己循环 query）
```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，正在等待"
         ↓
3. agent 循环 query（每60秒查一次）
   - 任务完成 → 立即回复
   - 未完成但已过20分钟 → query 最后一次，用最终结果回复
         ↓
4. 直接回复用户
```

### 外部 channel 场景（钉钉/Telegram/Discord 等，异步推送）
```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，有结果会通知你"
         ↓
3. sessions_spawn 启动子agent → 后台 poll（最多20分钟自动结束）
         ↓
4. 子agent 拿到结果后，用 message 工具主动推送给用户
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

### 方案 A：webchat — agent 自己循环 query

⚠️ **不要用 `poll` 命令！** poll 会阻塞进程，agent 无法控制节奏。

**正确做法：agent 自己循环调用 `query` 命令**。

⚠️ **实现关键：必须用 `exec` 的 `timeout` 参数控制等待，不要用 `process poll` 轮询输出！**
`process poll` 每次调用有延迟，反复 poll 会导致一轮循环实际耗时远超预期（教训：2026-03-06 一轮循环实际耗时 2-3 分钟而非 60 秒，8 轮下来超过 20 分钟）。

```
循环逻辑（最多 20 轮，每轮 60 秒，共 20 分钟）：

queryCount = 0

循环开始：
1. 运行命令（sleep + query 合并为一条 exec）：
   exec command="sleep 60 && python3 scripts/inquiry.py query '{taskId}'"  timeout=90
   
   ⚠️ 直接等 exec 返回，不要用 process poll！设 timeout=90 足够覆盖 60s sleep + query 时间。

2. queryCount += 1
3. 解析 JSON，检查 taskInfo.status：
   - FINISHED / FAILED / CANCELED → 结束循环，立即总结回复用户
   - RUNNING 且 queryCount < 20 → 回到步骤 1
   - RUNNING 且 queryCount >= 20 → 用当前结果回复用户（20 分钟到了，API 端任务一定已结束）
```

**关键规则：**
- 每次 query 间隔 **60 秒**（sleep 60 包含在 exec 命令中）
- **最多循环 20 次**（20 × 60秒 = 20 分钟），到了必须回复
- **不要用 `process poll` 等输出**，直接用 exec timeout 等命令完成
- 大多数询盘 2-5 分钟就能完成，少数供应商不回复才会等到 20 分钟

提交后先告知用户：
> 询盘已发送，正在等供应商回复，快的话几分钟，最多20分钟，请稍等... ⏳

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

拿到 query 的 JSON 结果后，按以下格式总结回复：

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
| `poll` | 轮询等结果（仅用于 sessions_spawn 子agent） | `inquiry.py poll "taskId"` |

## 注意事项

- `questionList` 固定填 `["自定义"]`，用户实际问题放入 `requirementContent`
- `isRequirementOriginal` 设为 `true`，原文发送
- **webchat 用 agent 自己循环 query（方案A）**，不要用 poll 阻塞命令
- 外部 channel 用 sessions_spawn 异步轮询（方案B），通过 message 工具主动推送结果
- 如果需要手动查询结果，可直接运行 `inquiry.py query "{taskId}"`
- **询盘任务 API 端最多执行 20 分钟**，到时间后一定有最终结果，所以 20 分钟后 query 一次即可兜底
- ⚠️ **20 分钟是硬上限，到了必须回复用户**，不管供应商有没有回完

## 教训记录

> **2026-03-05 ~ 03-06 连续踩坑：**
> 1. ❌ cron + delivery 方案：delivery 没配 channel → 报错；手算 UTC 时间错 → 延迟触发；配置都对了 announce 仍不送达
> 2. ❌ sessions_spawn + announce 方案：子agent 跑完了但用户看不到结果，必须用户主动发消息才能触发（且 announce 延迟不可控，有过延迟3小时的情况）
> 3. ❌ sessions_spawn + message 推送 webchat：webchat 不是 channel plugin，不支持 message 推送
> 4. ❌ webchat 同步 poll 方案：poll 阻塞进程，stdout 无中间输出，agent 无法给用户报进度，且 agent 容易提前放弃等待
> 5. ❌ webchat 循环 query 但无上限：agent 在循环里卡了10多分钟不给用户回复
> 6. ❌ webchat 循环 query 但用 process poll 等输出：每轮 poll 有延迟，实际一轮耗时 2-3 分钟而非 60 秒，8 轮超过 20 分钟
> 7. ✅ **最终方案**：webchat 用 agent 循环 query，exec timeout 等命令完成（不用 process poll），每轮严格 60 秒，最多 20 轮；外部 channel 用 sessions_spawn + message 主动推送

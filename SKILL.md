---
name: inquiry-1688
description: >-
  向1688供应商发起询盘，获取供应商对商品问题的回复。用户提供1688商品链接和自由文本问题，
  skill自动发起询盘任务，通过cron调度isolated session轮询结果（每30秒，最多20分钟），
  获取到回复后总结反馈给用户。
  触发词：询盘、问供应商、问商家、咨询供应商、1688询盘、能不能定制、起批量多少、
  商品长宽高、是否可以发货、是否有资质、供应商能不能XXX。
---

# 1688 询盘

向1688供应商发起询盘，异步等待结果，自动总结回复。

## 工作流程

```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 立即回复用户"已发起"
         ↓
3. cron 创建一次性定时任务（立即触发 isolated session）
         ↓
4. isolated session 运行 poll 命令 → 每30秒查一次，最多20分钟
         ↓
5. 结果 announce 回主 session → 总结展示
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

从响应中提取 `result.data` 作为 taskId。提交成功后立即告知用户：

> 询盘已发送给供应商，正在等待回复（最多20分钟），有结果会自动通知你 ✅

## Step 3: cron 触发 isolated session 轮询

使用 cron 创建一次性任务，**1分钟后触发**（给询盘一点初始处理时间）：

- **sessionTarget**: `isolated`
- **payload.kind**: `agentTurn`
- **payload.timeoutSeconds**: `1300`（略大于20分钟轮询时间）

cron message 模板：

```
请轮询1688询盘任务结果并总结。

执行步骤：
1. 运行轮询（每30秒查一次，最多20分钟）:
   python3 /home/admin/.openclaw/workspace/skills/inquiry-1688/scripts/inquiry.py poll "{taskId}"

2. 轮询结束后解析JSON结果，重点关注：
   - taskInfo.status（任务状态）
   - aiSummary（AI总结，markdown格式）
   - supplierCompare[].inquiryAnswers（各问题回复）
   - supplierCompare[].sellerInfo（供应商信息）
   - supplierCompare[].messages（完整聊天记录）

3. 按以下格式总结：

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

4. 如果超时仍未完成，说明当前进度，告知用户可稍后手动查询。

原始信息：
- 任务ID: {taskId}
- 商品链接: {链接}
- 询盘问题: {用户的问题}
```

## 脚本命令参考

| 命令 | 用途 | 示例 |
|------|------|------|
| `submit` | 提交询盘 | `inquiry.py submit "链接" "问题"` |
| `query` | 单次查询 | `inquiry.py query "taskId"` |
| `poll` | 轮询等结果 | `inquiry.py poll "taskId"` |

## 注意事项

- `questionList` 固定填 `["自定义"]`，用户实际问题放入 `requirementContent`
- `isRequirementOriginal` 设为 `true`，原文发送
- poll 命令会阻塞最多20分钟，必须在 isolated session 中运行
- cron payload 的 `timeoutSeconds` 设为 1300 以确保轮询不被截断

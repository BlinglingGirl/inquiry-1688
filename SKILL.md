---
name: inquiry-1688
description: >-
  向1688供应商发起询盘，获取供应商对商品问题的回复。用户提供1688商品链接和自由文本问题，
  skill自动发起询盘任务，20分钟后查询最终结果并回复用户。
  触发词：询盘、问供应商、问商家、咨询供应商、1688询盘、能不能定制、起批量多少、
  商品长宽高、是否可以发货、是否有资质、供应商能不能XXX。
---

# 1688 询盘

向1688供应商发起询盘，等待20分钟后获取最终结果。

**核心机制**：询盘任务提交后，API 端最多执行 20 分钟，到时间后任务一定结束。所以 **submit 后等 20 分钟，query 一次，直接拿最终结果**。不需要轮询。

## 工作流程

```
1. 提取：1688商品链接 + 询盘问题
         ↓
2. submit 提交询盘 → 获取 taskId → 告知用户"已发起，20分钟后给你结果"
         ↓
3. 等待 20 分钟（exec sleep 1200，yieldMs=1210000）
         ↓
4. query 一次拿最终结果 → 总结回复用户
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

## Step 3: 等待 20 分钟

```bash
exec command="sleep 1200 && python3 /path/to/scripts/inquiry.py query '{taskId}'" timeout=1300 yieldMs=1210000
```

⚠️ **关键参数**：
- `sleep 1200`：等待 20 分钟
- `timeout=1300`：略大于 20 分钟，确保不被 kill
- `yieldMs=1210000`：等够 20 分钟 + 10 秒余量后再返回结果，**不要让命令后台化**

## Step 4: 总结回复

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
| `query` | 查询结果 | `inquiry.py query "taskId"` |

## 注意事项

- `questionList` 固定填 `["自定义"]`，用户实际问题放入 `requirementContent`
- `isRequirementOriginal` 设为 `true`，原文发送
- **不要轮询！** submit 后只需等 20 分钟，query 一次就够
- 如果用户中途问"结果出来了吗"，可以提前 query 一次看看
- 如果需要手动查询结果，可直接运行 `inquiry.py query "{taskId}"`

## 教训记录

> **2026-03-05 ~ 03-06 连续踩坑：**
> 1. ❌ cron 方案：delivery 配置问题 + UTC 时间算错 + announce 不送达
> 2. ❌ sessions_spawn + announce：用户收不到结果
> 3. ❌ sessions_spawn + message 推送 webchat：webchat 不支持
> 4. ❌ 同步 poll：阻塞进程，无中间输出
> 5. ❌ 循环 query + process poll：每轮耗时远超预期，总时间超 20 分钟
> 6. ❌ 循环 query + yieldMs：逻辑复杂，仍有超时风险
> 7. ✅ **最终方案**：submit → sleep 1200（20分钟）→ query 一次 → 回复。最简单最可靠。

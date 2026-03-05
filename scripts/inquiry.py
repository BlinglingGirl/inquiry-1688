#!/usr/bin/env python3
"""
1688 Inquiry API — submit, query, and poll inquiry tasks.

Commands:
  submit    发起询盘任务（仅提交，返回taskId）
  query     单次查询询盘结果
  poll      轮询询盘结果（每30秒查一次，最多20分钟）

Auth: env ALPHASHOP_ACCESS_KEY / ALPHASHOP_SECRET_KEY (JWT HS256).
"""
import sys
import os
import json
import time
import re
import argparse
import requests
import jwt

BASE_URL = "https://api.alphashop.cn"
POLL_INTERVAL = 30      # 轮询间隔（秒）
POLL_TIMEOUT = 1200     # 最大轮询时间（秒）= 20分钟


# ── Auth ─────────────────────────────────────────────────────────────────────

def get_token():
    ak = os.environ.get("ALPHASHOP_ACCESS_KEY", "").strip()
    sk = os.environ.get("ALPHASHOP_SECRET_KEY", "").strip()
    if not ak or not sk:
        print("Error: Set ALPHASHOP_ACCESS_KEY and ALPHASHOP_SECRET_KEY env vars.", file=sys.stderr)
        sys.exit(1)
    now = int(time.time())
    token = jwt.encode(
        {"iss": ak, "exp": now + 1800, "nbf": now - 5},
        sk, algorithm="HS256", headers={"alg": "HS256"}
    )
    return token if isinstance(token, str) else token.decode("utf-8")


def call_api(path, body):
    url = "{}{}".format(BASE_URL, path)
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(get_token())
    }
    try:
        r = requests.post(url, json=body, headers=headers, timeout=120)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        print("HTTP Error: {}".format(e), file=sys.stderr)
        try:
            print("Response: {}".format(r.text), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print("Request Error: {}".format(e), file=sys.stderr)
        sys.exit(1)


# ── Extract product ID from URL or raw ID ────────────────────────────────────

def extract_product_id(url_or_id):
    m = re.search(r'offer/(\d+)', url_or_id)
    if m:
        return m.group(1)
    m = re.search(r'(\d{8,})', url_or_id)
    if m:
        return m.group(1)
    return url_or_id.strip()


# ── Check if task is finished ────────────────────────────────────────────────

def is_task_finished(resp):
    try:
        result = resp.get("result", {})
        if not result:
            return False
        data = result.get("data", {})
        if not data:
            return False
        status = data.get("taskInfo", {}).get("status", "")
        if status in ("FINISHED", "FAILED", "CANCELED"):
            return True
        suppliers = data.get("supplierCompare", [])
        if not suppliers:
            return False
        for s in suppliers:
            progress_list = s.get("questionProgress", [])
            if progress_list and all(q.get("isFinished", False) for q in progress_list):
                return True
        return False
    except Exception:
        return False


# ── Query Result (single shot) ───────────────────────────────────────────────

def query_result(task_id):
    return call_api("/inquiry.task.query.info/1.0", {"taskId": task_id})


# ── Submit ───────────────────────────────────────────────────────────────────

def cmd_submit(args):
    product_id = extract_product_id(args.item)
    body = {
        "questionList": ["自定义"],
        "requirementContent": args.question,
        "isRequirementOriginal": True,
        "itemList": [product_id]
    }
    if args.quantity:
        body["expectedOrderQuantity"] = args.quantity
    if args.address:
        body["addressText"] = args.address

    resp = call_api("/inquiry.task.submit.batchItem/1.0", body)
    print(json.dumps(resp, ensure_ascii=False, indent=2))


# ── Query (single shot) ─────────────────────────────────────────────────────

def cmd_query(args):
    resp = query_result(args.task_id)
    print(json.dumps(resp, ensure_ascii=False, indent=2))


# ── Poll (loop until finished or timeout) ────────────────────────────────────

def cmd_poll(args):
    task_id = args.task_id
    start = time.time()
    attempt = 0

    while True:
        elapsed = time.time() - start
        if elapsed >= POLL_TIMEOUT:
            print("Timeout after {} attempts ({:.0f}s). Returning last result.".format(attempt, elapsed), file=sys.stderr)
            resp = query_result(task_id)
            print(json.dumps(resp, ensure_ascii=False, indent=2))
            return

        time.sleep(POLL_INTERVAL)
        attempt += 1
        elapsed = time.time() - start
        print("Poll attempt {} | elapsed {:.0f}s / {}s".format(attempt, elapsed, POLL_TIMEOUT), file=sys.stderr)

        resp = query_result(task_id)
        if is_task_finished(resp):
            print("Task finished after {} attempts ({:.0f}s).".format(attempt, elapsed), file=sys.stderr)
            print(json.dumps(resp, ensure_ascii=False, indent=2))
            return


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="1688 Inquiry API CLI")
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # submit
    p_submit = sub.add_parser("submit", help="发起询盘任务")
    p_submit.add_argument("item", help="1688商品链接或商品ID")
    p_submit.add_argument("question", help="询盘问题（自由文本）")
    p_submit.add_argument("--quantity", type=int, help="期望订购量")
    p_submit.add_argument("--address", help="地址文本")

    # query
    p_query = sub.add_parser("query", help="单次查询询盘结果")
    p_query.add_argument("task_id", help="任务ID")

    # poll
    p_poll = sub.add_parser("poll", help="轮询询盘结果（每30秒，最多20分钟）")
    p_poll.add_argument("task_id", help="任务ID")

    args = parser.parse_args()
    if args.command == "submit":
        cmd_submit(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "poll":
        cmd_poll(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
PancakeSwap X 账号监测脚本
监测 @PancakeSwap 的最新推文，发现新的 IFO / Pre-Access / Launchpad / 新币申购活动时发送邮件通知
"""

import os
import sys
import json
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# ============================================================
# 邮件配置（从环境变量读取）
# ============================================================
EMAIL_CONFIG = {
    "enabled": os.environ.get("EMAIL_ENABLED", "true").lower() == "true",
    "smtp_server": os.environ.get("EMAIL_SMTP_SERVER", "smtp.qq.com"),
    "smtp_port": int(os.environ.get("EMAIL_SMTP_PORT", "465")),
    "use_ssl": os.environ.get("EMAIL_USE_SSL", "true").lower() == "true",
    "sender": os.environ.get("EMAIL_SENDER", "5660597@qq.com"),
    "password": os.environ.get("EMAIL_PASSWORD", ""),
    "receivers": [r.strip() for r in os.environ.get("EMAIL_RECEIVERS", "5660597@qq.com").split(",") if r.strip()],
}

# ============================================================
# 监测配置
# ============================================================
X_ACCOUNT = "PancakeSwap"
STATE_FILE = ".pancakeswap_last_tweets.json"

# 申购活动关键词（中英文）
KEYWORDS = [
    # 英文
    "IFO", "Initial Farm Offering", "Pre-Access", "pre-access", "pre access",
    "Launchpad", "launchpad", "new offering", "new token sale", "token sale",
    "subscription", "subscribe", "whitelist", "public sale", "private sale",
    "new project", "upcoming launch", "new launch", "farm offering",
    "commit CAKE", "commit cake", "raise funds", "fundraising",
    # 中文
    "申购", "新币", "发售", "众筹", "白名单", "预售", "上线", "首发",
]

# ============================================================
# 邮件发送
# ============================================================
def send_email(subject, body):
    """发送邮件通知"""
    cfg = EMAIL_CONFIG
    if not cfg.get("enabled"):
        print("  [邮件] 未启用，跳过发送")
        return False
    if not cfg.get("sender") or not cfg.get("password") or not cfg.get("receivers"):
        print("  [邮件] 配置不完整，跳过发送")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = ", ".join(cfg["receivers"])
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        if cfg["use_ssl"]:
            server = smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=30)
        else:
            server = smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=30)
            server.starttls()

        server.login(cfg["sender"], cfg["password"])
        server.sendmail(cfg["sender"], cfg["receivers"], msg.as_string())
        server.quit()
        print(f"  [邮件] 已发送至 {', '.join(cfg['receivers'])}")
        return True
    except Exception as e:
        print(f"  [邮件] 发送失败: {e}")
        return False

# ============================================================
# 状态管理
# ============================================================
def load_state():
    """加载已检测的推文状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen_tweet_ids": [], "last_check": None}

def save_state(state):
    """保存状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [状态] 保存失败: {e}")

# ============================================================
# X 推文抓取（使用 Playwright）
# ============================================================
def fetch_tweets_with_playwright():
    """使用 Playwright 抓取 X 账号最新推文"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [抓取] Playwright 未安装，尝试备用方案")
        return []

    tweets = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()

            url = f"https://x.com/{X_ACCOUNT}"
            print(f"  [抓取] 正在访问 {url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # 滚动加载更多推文
            for _ in range(3):
                page.evaluate("window.scrollBy(0, 800)")
                time.sleep(2)

            # 提取推文
            tweet_elements = page.query_selector_all('article[data-testid="tweet"]')
            print(f"  [抓取] 找到 {len(tweet_elements)} 条推文")

            for i, tweet in enumerate(tweet_elements[:15]):
                try:
                    # 提取推文文本
                    text_el = tweet.query_selector('div[data-testid="tweetText"]')
                    text = text_el.inner_text() if text_el else ""

                    # 提取推文链接
                    link_el = tweet.query_selector('a[href*="/status/"]')
                    link = link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = "https://x.com" + link

                    # 提取时间
                    time_el = tweet.query_selector("time")
                    tweet_time = time_el.get_attribute("datetime") if time_el else ""

                    # 提取推文 ID
                    tweet_id = ""
                    if "/status/" in link:
                        tweet_id = link.split("/status/")[1].split("/")[0].split("?")[0]

                    if text and tweet_id:
                        tweets.append({
                            "id": tweet_id,
                            "text": text,
                            "link": link,
                            "time": tweet_time,
                        })
                except Exception as e:
                    print(f"  [抓取] 解析第 {i} 条推文失败: {e}")
                    continue

            browser.close()
    except Exception as e:
        print(f"  [抓取] Playwright 抓取失败: {e}")

    return tweets

# ============================================================
# 备用方案：使用 X syndication API
# ============================================================
def fetch_tweets_with_api():
    """使用 X syndication API 作为备用方案"""
    import requests
    tweets = []
    try:
        url = f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={X_ACCOUNT}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and resp.text:
            data = resp.json()
            # 解析返回的 HTML 内容提取推文
            # 这个 API 返回的是嵌入用的 HTML，需要解析
            print(f"  [API] syndication 返回 {len(resp.text)} 字节")
    except Exception as e:
        print(f"  [API] syndication 失败: {e}")

    return tweets

# ============================================================
# 关键词匹配
# ============================================================
def match_keywords(text):
    """检查文本是否包含申购活动关键词"""
    matched = []
    text_lower = text.lower()
    for kw in KEYWORDS:
        if kw.lower() in text_lower:
            matched.append(kw)
    return matched

# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 55)
    print("  PancakeSwap 申购活动监测")
    print("=" * 55)
    print(f"  监测账号: @{X_ACCOUNT}")
    print(f"  监测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📧 邮件推送: {'已启用' if EMAIL_CONFIG.get('enabled') else '未启用'} → {', '.join(EMAIL_CONFIG['receivers'])}")
    print()

    # 加载状态
    state = load_state()
    seen_ids = set(state.get("seen_tweet_ids", []))
    print(f"  已记录推文: {len(seen_ids)} 条")

    # 抓取推文
    print()
    print("  正在抓取最新推文...")
    tweets = fetch_tweets_with_playwright()

    if not tweets:
        print("  Playwright 抓取失败，尝试备用方案...")
        tweets = fetch_tweets_with_api()

    if not tweets:
        print("  ⚠️ 无法获取推文，本次监测结束")
        state["last_check"] = datetime.now().isoformat()
        save_state(state)
        return

    print(f"  成功获取 {len(tweets)} 条最新推文")
    print()

    # 检测新的申购活动
    new_activities = []
    for tweet in tweets:
        if tweet["id"] in seen_ids:
            continue

        matched = match_keywords(tweet["text"])
        if matched:
            new_activities.append({
                **tweet,
                "matched_keywords": matched,
            })

    # 更新已见推文 ID
    for tweet in tweets:
        seen_ids.add(tweet["id"])
    state["seen_tweet_ids"] = list(seen_ids)[-200:]  # 只保留最近200条
    state["last_check"] = datetime.now().isoformat()
    save_state(state)

    # 输出结果
    print("-" * 55)
    if new_activities:
        print(f"  🚨 发现 {len(new_activities)} 条新的申购活动公告！")
        print()

        # 发送邮件
        subject = f"🚀 PancakeSwap 新申购活动: {new_activities[0]['matched_keywords'][0]}"
        body = f"发现 PancakeSwap 新的申购活动公告！\n\n"
        body += f"监测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += f"监测账号: @{X_ACCOUNT}\n\n"

        for i, activity in enumerate(new_activities, 1):
            body += f"{'='*50}\n"
            body += f"【活动 {i}】\n"
            body += f"匹配关键词: {', '.join(activity['matched_keywords'])}\n"
            body += f"发布时间: {activity['time']}\n"
            body += f"推文链接: {activity['link']}\n\n"
            body += f"推文内容:\n{activity['text']}\n\n"

        body += f"{'='*50}\n"
        body += f"请尽快访问 PancakeSwap 官网查看详情: https://pancakeswap.finance/ifo\n"
        body += f"\n本邮件由 PancakeSwap 监测脚本自动发送"

        print(f"  正在发送邮件通知...")
        send_email(subject, body)

        # 打印活动摘要
        for i, activity in enumerate(new_activities, 1):
            print(f"\n  【活动 {i}】匹配: {', '.join(activity['matched_keywords'])}")
            print(f"  时间: {activity['time']}")
            print(f"  链接: {activity['link']}")
            print(f"  内容: {activity['text'][:200]}...")
    else:
        print("  ✅ 未发现新的申购活动")
        print(f"  已扫描 {len(tweets)} 条最新推文，无关键词匹配")

    print()
    print("=" * 55)
    print("  监测完成")
    print("=" * 55)


if __name__ == "__main__":
    main()

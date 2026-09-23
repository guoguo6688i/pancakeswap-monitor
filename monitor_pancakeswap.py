#!/usr/bin/env python3
"""
PancakeSwap 申购活动监测脚本
多数据源监测：Google News RSS + X(Twitter)页面抓取 + 官网IFO页面
发现新的 IFO / Pre-Access / Launchpad / 新币申购活动时发送邮件通知
"""

import os
import sys
import json
import time
import smtplib
import hashlib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

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
    # 英文 - IFO相关
    "IFO", "Initial Farm Offering", "Pre-Access", "pre-access", "pre access",
    "Launchpad", "launchpad", "new offering", "new token sale", "token sale",
    "subscription", "subscribe", "whitelist", "public sale", "private sale",
    "new project", "upcoming launch", "new launch", "farm offering",
    "commit CAKE", "commit cake", "raise funds", "fundraising",
    "new token", "token launch", "IDO", "initial dex offering",
    # 中文
    "申购", "新币", "发售", "众筹", "白名单", "预售", "首发", "上线",
]

# Google News 搜索关键词组合
NEWS_QUERIES = [
    "PancakeSwap IFO",
    "PancakeSwap Launchpad",
    "PancakeSwap Pre-Access",
    "PancakeSwap new token offering",
    "PancakeSwap 申购",
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
    """加载已检测的状态"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen_ids": [], "last_check": None}

def save_state(state):
    """保存状态"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [状态] 保存失败: {e}")

def make_id(text, source):
    """生成内容唯一ID"""
    return hashlib.md5(f"{source}:{text}".encode()).hexdigest()[:16]

def parse_date(date_str):
    """解析日期字符串，返回 datetime 对象"""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

def is_recent(date_str, days=7):
    """检查日期是否在最近 N 天内"""
    dt = parse_date(date_str)
    if dt is None:
        return True  # 无法解析日期时保留
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff

# ============================================================
# 数据源1：Google News RSS
# ============================================================
def fetch_from_google_news():
    """从 Google News RSS 搜索 PancakeSwap 申购相关新闻"""
    import requests
    results = []

    for query in NEWS_QUERIES:
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url, headers=headers, timeout=15)

            if resp.status_code != 200 or not resp.text:
                print(f"  [News] 查询 '{query}' 返回状态 {resp.status_code}")
                continue

            # 解析 RSS
            root = ElementTree.fromstring(resp.text)
            items = root.findall(".//item")
            print(f"  [News] 查询 '{query}' 找到 {len(items)} 条新闻")

            recent_count = 0
            for item in items[:20]:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                source = item.findtext("source", "")

                # 只保留最近7天的新闻
                if not is_recent(pub_date, days=7):
                    continue

                # 清理标题（Google News 标题格式："标题 - 来源"）
                clean_title = re.sub(r'\s+-\s+[^-]+$', '', title).strip()

                if clean_title and link:
                    results.append({
                        "id": make_id(clean_title, "google_news"),
                        "title": clean_title,
                        "text": clean_title,
                        "link": link,
                        "time": pub_date,
                        "source": f"Google News ({source})" if source else "Google News",
                        "query": query,
                    })
                    recent_count += 1

            print(f"  [News]   其中最近7天: {recent_count} 条")
        except Exception as e:
            print(f"  [News] 查询 '{query}' 失败: {e}")
            continue

    return results

# ============================================================
# 数据源2：X(Twitter) 页面抓取（Playwright）
# ============================================================
def fetch_from_x():
    """使用 Playwright 抓取 X 账号最新推文"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  [X] Playwright 未安装，跳过")
        return []

    tweets = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
            """)

            page = context.new_page()
            url = f"https://x.com/{X_ACCOUNT}"
            print(f"  [X] 正在访问 {url}...")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(8)

            try:
                page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
            except Exception:
                pass

            for _ in range(3):
                page.evaluate("window.scrollBy(0, 600)")
                time.sleep(2)

            tweet_elements = page.query_selector_all('article[data-testid="tweet"]')
            if not tweet_elements:
                tweet_elements = page.query_selector_all('article')
            print(f"  [X] 找到 {len(tweet_elements)} 条推文")

            for tweet in tweet_elements[:15]:
                try:
                    text_el = tweet.query_selector('div[data-testid="tweetText"]')
                    text = text_el.inner_text() if text_el else ""
                    if not text:
                        text_els = tweet.query_selector_all('div[dir="auto"]')
                        text = " ".join([el.inner_text() for el in text_els if el.inner_text()])

                    link_el = tweet.query_selector('a[href*="/status/"]')
                    link = link_el.get_attribute("href") if link_el else ""
                    if link and not link.startswith("http"):
                        link = "https://x.com" + link

                    time_el = tweet.query_selector("time")
                    tweet_time = time_el.get_attribute("datetime") if time_el else ""

                    tweet_id = ""
                    if "/status/" in link:
                        tweet_id = link.split("/status/")[1].split("/")[0].split("?")[0]

                    if text and tweet_id:
                        tweets.append({
                            "id": make_id(tweet_id, "x"),
                            "title": text[:80],
                            "text": text,
                            "link": link,
                            "time": tweet_time,
                            "source": f"X (@{X_ACCOUNT})",
                        })
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        print(f"  [X] 抓取失败: {e}")

    return tweets

# ============================================================
# 数据源3：PancakeSwap 官网 IFO 页面
# ============================================================
def fetch_from_website():
    """监测 PancakeSwap 官网 IFO 页面变化"""
    import requests
    results = []
    try:
        url = "https://pancakeswap.finance/ifo"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 200 and resp.text:
            # 检查页面中是否有 IFO 相关内容
            text = resp.text
            ifo_keywords = ["upcoming", "active", "IFO", "offering"]
            found = [kw for kw in ifo_keywords if kw.lower() in text.lower()]

            if found:
                # 提取页面标题
                title_match = re.search(r'<title>([^<]+)</title>', text)
                title = title_match.group(1) if title_match else "PancakeSwap IFO 页面更新"

                results.append({
                    "id": make_id(f"ifo_page_{datetime.now().strftime('%Y%m%d')}", "website"),
                    "title": title,
                    "text": f"PancakeSwap IFO 页面包含关键词: {', '.join(found)}",
                    "link": url,
                    "time": datetime.now().isoformat(),
                    "source": "PancakeSwap 官网",
                })
                print(f"  [官网] IFO 页面检测到关键词: {', '.join(found)}")
            else:
                print("  [官网] IFO 页面未检测到活动关键词")
    except Exception as e:
        print(f"  [官网] 访问失败: {e}")

    return results

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
    print(f"  监测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📧 邮件推送: {'已启用' if EMAIL_CONFIG.get('enabled') else '未启用'} → {', '.join(EMAIL_CONFIG['receivers'])}")
    print()

    # 加载状态
    state = load_state()
    seen_ids = set(state.get("seen_ids", []))
    print(f"  已记录内容: {len(seen_ids)} 条")

    # 从多个数据源获取内容
    all_items = []

    print()
    print("  [数据源1] Google News RSS...")
    news_items = fetch_from_google_news()
    all_items.extend(news_items)

    print()
    print("  [数据源2] X(Twitter) 页面...")
    x_items = fetch_from_x()
    all_items.extend(x_items)

    print()
    print("  [数据源3] PancakeSwap 官网...")
    web_items = fetch_from_website()
    all_items.extend(web_items)

    print()
    print(f"  共获取 {len(all_items)} 条内容")

    # 去重
    unique_items = []
    seen_in_batch = set()
    for item in all_items:
        if item["id"] not in seen_in_batch:
            seen_in_batch.add(item["id"])
            unique_items.append(item)

    print(f"  去重后 {len(unique_items)} 条")

    # 检测新的申购活动
    new_activities = []
    for item in unique_items:
        if item["id"] in seen_ids:
            continue

        matched = match_keywords(item["text"])
        if matched:
            new_activities.append({
                **item,
                "matched_keywords": matched,
            })

    # 更新已见ID
    for item in unique_items:
        seen_ids.add(item["id"])
    state["seen_ids"] = list(seen_ids)[-500:]  # 保留最近500条
    state["last_check"] = datetime.now().isoformat()
    save_state(state)

    # 输出结果
    print()
    print("-" * 55)

    # 判断是否首次运行（基线建立）
    is_first_run = len(state.get("seen_ids", [])) == 0

    if new_activities:
        if is_first_run:
            print(f"  ℹ️ 首次运行，建立基线，发现 {len(new_activities)} 条历史活动（不发送邮件）")
            print(f"  后续运行发现新活动时将自动发送邮件通知")
        else:
            print(f"  🚨 发现 {len(new_activities)} 条新的申购活动公告！")
            print()

            # 发送邮件
            subject = f"🚀 PancakeSwap 新申购活动: {new_activities[0]['matched_keywords'][0]}"
            body = f"发现 PancakeSwap 新的申购活动公告！\n\n"
            body += f"监测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            body += f"数据来源: Google News / X / 官网\n\n"

            for i, activity in enumerate(new_activities, 1):
                body += f"{'='*50}\n"
                body += f"【活动 {i}】\n"
                body += f"匹配关键词: {', '.join(activity['matched_keywords'])}\n"
                body += f"来源: {activity.get('source', '未知')}\n"
                body += f"发布时间: {activity.get('time', '未知')}\n"
                body += f"链接: {activity['link']}\n\n"
                body += f"内容:\n{activity['text'][:500]}\n\n"

            body += f"{'='*50}\n"
            body += f"请尽快访问 PancakeSwap 官网查看详情: https://pancakeswap.finance/ifo\n"
            body += f"\n本邮件由 PancakeSwap 监测脚本自动发送"

            print(f"  正在发送邮件通知...")
            send_email(subject, body)

        # 打印活动摘要
        for i, activity in enumerate(new_activities, 1):
            print(f"\n  【活动 {i}】匹配: {', '.join(activity['matched_keywords'])}")
            print(f"  来源: {activity.get('source', '未知')}")
            print(f"  时间: {activity.get('time', '未知')}")
            print(f"  链接: {activity['link']}")
            print(f"  内容: {activity['text'][:200]}...")
    else:
        print("  ✅ 未发现新的申购活动")
        print(f"  已扫描 {len(unique_items)} 条内容，无关键词匹配")

    print()
    print("=" * 55)
    print("  监测完成")
    print("=" * 55)


if __name__ == "__main__":
    main()

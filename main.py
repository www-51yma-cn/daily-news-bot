import os
import json
import time
import requests
from openai import OpenAI
from ddgs import DDGS
from datetime import datetime

# ================== 配置区域 ==================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
WECHAT_WEBHOOK_KEY = os.environ.get('WECHAT_WEBHOOK_KEY')
WECHAT_WEBHOOK_URL = os.environ.get('WECHAT_WEBHOOK_URL')
SERVERCHAN_SENDKEY = os.environ.get('SERVERCHAN_SENDKEY')

# 搜索关键词
STOCK_KEYWORDS = [
    "今日股票推荐", "机构推荐个股", "A股热点板块", "短线金股",
    "宏观经济数据", "央行政策", "财经新闻 头条", "主力资金流向"
]

# 网站域名 -> 中文名称映射
SITE_NAMES = {
    "eastmoney.com": "东方财富",
    "10jqka.com.cn": "同花顺",
    "finance.sina.com.cn": "新浪财经",
    "stockstar.com": "证券之星",
    "cs.com.cn": "中国证券报",
    "stcn.com": "证券时报",
    "cls.cn": "财联社",
    "nbd.com.cn": "每日经济新闻"
}
TARGET_SITES = list(SITE_NAMES.keys())

HISTORY_FILE = "history.json"
CURRENT_DATETIME = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")

# AI 提示词（允许详细总结）
SYSTEM_PROMPT = f"""你是一个专业的股票财经分析师。当前时间是 {CURRENT_DATETIME}。
请根据我提供的搜索结果，提取出最重要的股票推荐信息、热点板块、经济新闻。
对于重点信息（如重要股票推荐、重大政策变化、市场大幅波动等），请适当展开详细说明，可以分析原因或影响。
每条信息标注来源网站名称。
最后按重要性排序，用清晰的格式呈现。"""

# ================== 1. 联网搜索 ==================
def search_news(keywords, sites, num_results_per_site=2):
    all_news = []
    with DDGS() as ddgs:
        for kw in keywords:
            for site in sites:
                query = f"{kw} site:{site}"
                print(f"正在搜索：{query}")
                try:
                    results = list(ddgs.text(query, region="cn", safesearch="moderate", max_results=num_results_per_site))
                    for r in results:
                        link = r.get('href')
                        if link:
                            source_name = SITE_NAMES.get(site, site)
                            all_news.append({
                                "title": r.get('title'),
                                "snippet": r.get('body'),
                                "link": link,
                                "source": source_name,
                                "timestamp": datetime.now().isoformat()
                            })
                except Exception as e:
                    print(f"搜索 {query} 时出错: {e}")
    unique = {}
    for item in all_news:
        link = item['link']
        if link not in unique:
            unique[link] = item
    return list(unique.values())

# ================== 2. AI 总结 ==================
def summarize_news(news_list, retries=2):
    if not news_list:
        return "今日暂无新财经资讯。"

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=30.0,
    )
    news_text = json.dumps(news_list, ensure_ascii=False, indent=2)
    user_prompt = f"请用中文总结以下最新新闻，形成一份简报。对于重要信息可以详细分析：\n\n{news_text}"

    for attempt in range(retries):
        try:
            print(f"正在调用 AI，第 {attempt + 1} 次...")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                stream=False,
                temperature=0.7,
                timeout=30.0,
            )
            summary = response.choices[0].message.content
            print("AI 总结成功")
            return summary
        except Exception as e:
            print(f"AI 总结失败 (尝试 {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                return f"AI 总结失败，错误：{e}\n\n原始新闻数据：\n{news_text[:2000]}"

# ================== 3. 历史记录管理 ==================
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return set(data.get("pushed_links", []))

def save_history(links):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"pushed_links": list(links)}, f, ensure_ascii=False, indent=2)

# ================== 4. 推送企业微信 ==================
def split_long_message(content, max_bytes=4000):
    if len(content.encode('utf-8')) <= max_bytes:
        return [content]
    messages = []
    paragraphs = content.split('\n')
    current_msg = ""
    for para in paragraphs:
        test_msg = current_msg + para + '\n'
        if len(test_msg.encode('utf-8')) <= max_bytes:
            current_msg = test_msg
        else:
            if current_msg:
                messages.append(current_msg)
                current_msg = ""
            if len(para.encode('utf-8')) > max_bytes:
                for i in range(0, len(para), max_bytes):
                    messages.append(para[i:i+max_bytes])
            else:
                current_msg = para + '\n'
    if current_msg:
        messages.append(current_msg)
    return messages

def send_to_wecom(content, msg_type="markdown"):
    if not WECHAT_WEBHOOK_KEY and not WECHAT_WEBHOOK_URL:
        print("未配置企业微信 Webhook")
        return False
    if WECHAT_WEBHOOK_URL:
        webhook_url = WECHAT_WEBHOOK_URL
    else:
        webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    max_len = 4096 if msg_type == "markdown" else 2048
    if len(content.encode('utf-8')) > max_len:
        content = content.encode('utf-8')[:max_len-100].decode('utf-8', errors='ignore') + "\n\n...（截断）"
    payload = {
        "msgtype": msg_type,
        "text" if msg_type == "text" else "markdown": {"content": content}
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        result = resp.json()
        if result.get('errcode') == 0:
            print("企业微信推送成功")
            return True
        else:
            print(f"企业微信推送失败: {result}")
            return False
    except Exception as e:
        print(f"推送异常: {e}")
        return False

def send_to_serverchan(content):
    if not SERVERCHAN_SENDKEY:
        return False
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    data = {"title": "【每日股票资讯】", "desp": content}
    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            print("Server酱推送成功")
            return True
    except Exception as e:
        print(f"Server酱异常: {e}")
    return False

def format_for_wecom(report):
    lines = report.split('\n')
    formatted = []
    for line in lines:
        if line.strip():
            formatted.append(line + "  ")
    separator = "\n<font color=\"comment\">---</font>\n"
    return separator.join(formatted)

# ================== 5. 提交历史到仓库 ==================
def commit_and_push():
    import subprocess
    result = subprocess.run(["git", "status", "--porcelain", HISTORY_FILE], capture_output=True, text=True)
    if not result.stdout.strip():
        print("没有需要提交的变更")
        return True
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@github-actions.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "News Bot"], check=True)
        subprocess.run(["git", "add", HISTORY_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"Update news history - {datetime.now().isoformat()}"], check=True)
        remote_url = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True, check=True).stdout.strip()
        token = os.environ.get("GITHUB_TOKEN")
        if token and remote_url.startswith("https://"):
            remote_url = remote_url.replace("https://", f"https://x-access-token:{token}@")
            subprocess.run(["git", "push", remote_url, "HEAD:main"], check=True)
        else:
            subprocess.run(["git", "push"], check=True)
        print("历史记录已提交并推送")
        return True
    except Exception as e:
        print(f"提交历史记录失败: {e}")
        return False

# ================== 主程序 ==================
if __name__ == "__main__":
    print("========== 股票新闻机器人启动 ==========")
    print(f"当前时间: {CURRENT_DATETIME}")

    old_links = load_history()
    print(f"已有历史新闻数: {len(old_links)}")

    all_news = search_news(STOCK_KEYWORDS, TARGET_SITES, num_results_per_site=2)
    print(f"本次搜索到 {len(all_news)} 条新闻")

    new_news = [item for item in all_news if item['link'] not in old_links]
    print(f"其中新新闻: {len(new_news)} 条")

    # 无论有无新新闻，都发送一条消息
    if not new_news:
        # 没有新新闻：发送“暂无新信息”消息
        no_news_msg = f"## 📭 暂无新财经资讯\n**{CURRENT_DATETIME}**\n\n未发现新的股票推荐或重要经济新闻，请稍后再查看。"
        if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
            formatted = format_for_wecom(no_news_msg)
            send_to_wecom(formatted, msg_type="markdown")
        elif SERVERCHAN_SENDKEY:
            send_to_serverchan(no_news_msg)
        print("没有新新闻，已推送‘暂无信息’消息")
        exit(0)

    # 有新新闻：AI 总结并推送
    report = summarize_news(new_news)

    if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
        title = f"## 📈 股市资讯简报\n**{CURRENT_DATETIME}**\n\n"
        full_report = title + report
        formatted = format_for_wecom(full_report)
        parts = split_long_message(formatted, max_bytes=4000)
        success = True
        for idx, part in enumerate(parts, 1):
            header = f"**【股市资讯】第{idx}/{len(parts)}部分**\n\n"
            if not send_to_wecom(header + part, msg_type="markdown"):
                success = False
        if not success and SERVERCHAN_SENDKEY:
            send_to_serverchan(report)
    elif SERVERCHAN_SENDKEY:
        send_to_serverchan(report)

    # 更新历史记录
    new_links = old_links.union({item['link'] for item in new_news})
    save_history(new_links)
    print(f"历史记录已更新，当前总数: {len(new_links)}")

    commit_and_push()
    print("========== 运行结束 ==========")

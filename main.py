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

# 限定搜索的热门炒股资讯网站（新增财联社、每日经济新闻）
TARGET_SITES = [
    "eastmoney.com",      # 东方财富
    "10jqka.com.cn",      # 同花顺
    "finance.sina.com.cn",# 新浪财经
    "stockstar.com",      # 证券之星
    "cs.com.cn",          # 中国证券报
    "stcn.com",           # 证券时报
    "cls.cn",             # 财联社
    "nbd.com.cn"          # 每日经济新闻
]

# 历史记录文件路径
HISTORY_FILE = "history.json"

# AI 提示词
SYSTEM_PROMPT = """你是一个专业的股票财经分析师。
请根据我提供的搜索结果，提取出最重要的股票推荐信息、热点板块、经济新闻。
每条信息用一句话概括，并附上来源网站。
最后按重要性排序，用清晰的格式呈现。"""

# ================== 1. 联网搜索（限定网站） ==================
def search_news(keywords, sites, num_results_per_site=2):
    """在指定网站内搜索关键词，返回新闻列表（含链接）"""
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
                            all_news.append({
                                "title": r.get('title'),
                                "snippet": r.get('body'),
                                "link": link,
                                "source": site,
                                "timestamp": datetime.now().isoformat()
                            })
                except Exception as e:
                    print(f"搜索 {query} 时出错: {e}")
    # 去重（基于链接）
    unique = {}
    for item in all_news:
        link = item['link']
        if link not in unique:
            unique[link] = item
    return list(unique.values())

# ================== 2. AI 总结 ==================
def summarize_news(news_list, retries=2):
    """调用 DeepSeek 总结新闻"""
    if not news_list:
        return "今日暂无新财经资讯。"

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=30.0,
    )

    news_text = json.dumps(news_list, ensure_ascii=False, indent=2)
    user_prompt = f"请用中文总结以下最新新闻，形成一份简报：\n\n{news_text}"

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
    """从本地文件加载已推送的链接集合"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return set(data.get("pushed_links", []))

def save_history(links):
    """保存已推送的链接集合到文件"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"pushed_links": list(links)}, f, ensure_ascii=False, indent=2)

# ================== 4. 推送企业微信（支持长消息拆分） ==================
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
    formatted = [line + "  " for line in lines if line.strip()]
    separator = "\n<font color=\"comment\">---</font>\n"
    return separator.join(formatted)

# ================== 主程序 ==================
def commit_and_push():
    """将 history.json 的变更提交并推送到仓库（需在 workflow 中配置 git）"""
    import subprocess
    try:
        subprocess.run(["git", "config", "user.email", "bot@example.com"], check=True)
        subprocess.run(["git", "config", "user.name", "News Bot"], check=True)
        subprocess.run(["git", "add", HISTORY_FILE], check=True)
        subprocess.run(["git", "commit", "-m", "Update news history"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("历史记录已提交到仓库")
    except Exception as e:
        print(f"提交历史记录失败: {e}")

if __name__ == "__main__":
    print("========== 股票新闻机器人启动 ==========")
    # 1. 加载已推送的历史链接
    old_links = load_history()
    print(f"已有历史新闻数: {len(old_links)}")
    
    # 2. 搜索最新新闻
    all_news = search_news(STOCK_KEYWORDS, TARGET_SITES, num_results_per_site=2)
    print(f"本次搜索到 {len(all_news)} 条新闻")
    
    # 3. 过滤出新新闻
    new_news = [item for item in all_news if item['link'] not in old_links]
    print(f"其中新新闻: {len(new_news)} 条")
    
    if not new_news:
        print("没有新新闻，跳过推送")
        exit(0)
    
    # 4. AI 总结新新闻
    report = summarize_news(new_news)
    
    # 5. 推送到企业微信（自动拆分）
    if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
        formatted = format_for_wecom(report)
        parts = split_long_message(formatted, max_bytes=4000)
        success = True
        for idx, part in enumerate(parts, 1):
            title = f"**【股票资讯】第{idx}/{len(parts)}部分**\n\n"
            if not send_to_wecom(title + part, msg_type="markdown"):
                success = False
        if not success and SERVERCHAN_SENDKEY:
            send_to_serverchan(report)
    elif SERVERCHAN_SENDKEY:
        send_to_serverchan(report)
    
    # 6. 更新历史记录并保存
    new_links = old_links.union({item['link'] for item in new_news})
    save_history(new_links)
    print(f"历史记录已更新，当前总数: {len(new_links)}")
    
    # 7. 提交并推送 history.json 到仓库（需要 git 权限）
    commit_and_push()
    
    print("========== 运行结束 ==========")

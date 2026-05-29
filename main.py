import os
import json
import time
import re
import requests
from datetime import datetime
from openai import OpenAI

# ================== 配置区域 ==================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
WECHAT_WEBHOOK_KEY = os.environ.get('WECHAT_WEBHOOK_KEY')
WECHAT_WEBHOOK_URL = os.environ.get('WECHAT_WEBHOOK_URL')
SERVERCHAN_SENDKEY = os.environ.get('SERVERCHAN_SENDKEY')

HISTORY_FILE = "history.json"

# 同花顺 API
THS_API_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=400"

# 财联社 API
CLS_API_URL = "https://www.cls.cn/api/cache?app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9"

# AI 提示词模板
SYSTEM_PROMPT = """你是一位专业A股投研分析师，结合基本面、资金面、题材面解读新闻快讯，为选股、择时、风控提供依据。

一、筛选标准
保留：国家级政策、行业供需/价格/监管变化、上市公司业绩/重组/增减持/风险公告、机构评级调整、北向/龙虎榜/大宗等资金异动、重要经济数据。
剔除：非财经资讯、公司常规公告、无实质内容的表态、重复旧闻。

二、分类体系（Markdown三级标题）
### 1. 宏观政策与经济数据
### 2. 行业产业链（含价格、产能、集采、技术、项目）
### 3. 上市公司重大公告
### 4. 机构研报、评级与调研观点
### 5. 市场资金、盘面与交易异动

三、单条解读格式
- 【时间】【来源】：事件简述 | 性质：利好/利空/题材催化/风险警示 | 关联：细分板块/核心个股 | 持续性：短期(1-3日)/中期(1周以上)

四、附加分析模块（放在所有分类条目之后）
1. 消息强度分级：按★★★（顶级）/★★（中等）/★（轻微）标注影响力度，排序展示高价值消息。
2. 产业链传导分析：说明利好/利空的上下游延伸标的。
3. 风控提示：列明潜在黑天鹅、利空个股/板块。
4. 简要操作提醒：区分短线题材、中线基本面机会的应对思路（可客观的预测涨跌，并给逻辑）。

全文使用Markdown排版，列表呈现，客观基于事实解读，可客观预测涨跌，并分析影响逻辑。"""

# ================== 1. 采集同花顺快讯 ==================
def fetch_10jqka_news():
    """直接调用同花顺快讯 API，从 digest 中提取括号内的来源，并清理摘要"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://news.10jqka.com.cn/",
    }
    try:
        resp = requests.get(THS_API_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"同花顺 API 请求失败，状态码: {resp.status_code}")
            return []
        data = resp.json()
        if data.get("code") != "200":
            print(f"同花顺 API 返回错误: {data.get('msg')}")
            return []
        news_list = data.get("data", {}).get("list", [])
        all_news = []
        for item in news_list:
            ctime = int(item.get("ctime", 0))
            ctime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctime))
            url = item.get("url") or f"https://news.10jqka.com.cn/{item.get('id')}.html"
            raw_digest = item.get("digest", "")

            # 从 digest 末尾提取括号内的来源
            source_match = re.search(r'（([^（）]+)）$', raw_digest)
            if source_match:
                source = source_match.group(1)
                snippet = re.sub(r'（[^（）]+）$', '', raw_digest).strip()
            else:
                source = "同花顺快讯"
                snippet = raw_digest

            all_news.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "snippet": snippet,
                "link": url,
                "source": source,
                "pub_date": ctime_str,
                "timestamp": datetime.now().isoformat(),
                "_ctime": ctime,
            })
        print(f"成功采集 {len(all_news)} 条同花顺快讯")
        return all_news
    except Exception as e:
        print(f"同花顺采集出错: {e}")
        return []

# ================== 2. 采集财联社快讯 ==================
def fetch_cls_news(page_size=30):
    """采集财联社电报快讯"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.cls.cn/",
    }
    try:
        resp = requests.get(CLS_API_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"财联社 API 请求失败，状态码: {resp.status_code}")
            return []
        data = resp.json()
        if data.get('errno') != 0:
            print(f"财联社 API 返回错误: {data.get('errmsg')}")
            return []
        news_list = data.get('data', {}).get('roll_data', [])[:page_size]
        all_news = []
        for item in news_list:
            ctime = int(item.get("ctime", 0))
            ctime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ctime))
            link = f"https://www.cls.cn/detail/{item.get('id')}"
            all_news.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "snippet": item.get("brief", ""),
                "link": link,
                "source": "财联社",
                "pub_date": ctime_str,
                "timestamp": datetime.now().isoformat(),
                "_ctime": ctime,
            })
        print(f"成功采集 {len(all_news)} 条财联社快讯")
        return all_news
    except Exception as e:
        print(f"财联社采集出错: {e}")
        return []

# ================== 3. 历史记录管理（去重） ==================
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return set(data.get("pushed_links", []))

def save_history(links):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"pushed_links": list(links)}, f, ensure_ascii=False, indent=2)

def commit_and_push():
    import subprocess
    result = subprocess.run(["git", "status", "--porcelain", HISTORY_FILE], capture_output=True, text=True)
    if not result.stdout.strip():
        print("没有需要提交的变更")
        return
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
    except Exception as e:
        print(f"提交历史记录失败: {e}")

# ================== 4. AI 智能筛选与总结 ==================
def ai_summarize_news(news_list, retries=2):
    if not news_list:
        return None
    if not DEEPSEEK_API_KEY:
        print("未配置 DEEPSEEK_API_KEY，跳过 AI 总结")
        return None

    news_text = ""
    for idx, item in enumerate(news_list, 1):
        news_text += f"{idx}. 标题：{item['title']}\n   摘要：{item['snippet']}\n   时间：{item['pub_date']}\n   来源：{item['source']}\n\n"

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=30.0)

    for attempt in range(retries):
        try:
            print(f"正在调用 AI 进行筛选总结（尝试 {attempt+1}/{retries}）...")
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"请处理以下新闻列表：\n{news_text}"}
                ],
                stream=False,
                temperature=0.5,
                timeout=30.0,
            )
            summary = response.choices[0].message.content
            print("AI 总结成功")
            return summary
        except Exception as e:
            print(f"AI 调用失败 (尝试 {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(5)
            else:
                return None

# ================== 5. 企业微信推送 ==================
def split_long_message(content, max_bytes=4000):
    if len(content.encode('utf-8')) <= max_bytes:
        return [content]
    messages, paragraphs, current_msg = [], content.split('\n'), ""
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
        print("未配置企业微信 Webhook，跳过推送")
        return False
    webhook_url = WECHAT_WEBHOOK_URL if WECHAT_WEBHOOK_URL else f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    max_len = 4096 if msg_type == "markdown" else 2048
    if len(content.encode('utf-8')) > max_len:
        content = content.encode('utf-8')[:max_len-100].decode('utf-8', errors='ignore') + "\n\n...（截断）"
    payload = {"msgtype": msg_type, "text" if msg_type == "text" else "markdown": {"content": content}}
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
    data = {"title": "【AI精选快讯】", "desp": content}
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

# ================== 6. 主程序 ==================
def main():
    # 时间窗口判断：北京时间 8:00-21:30 之外直接退出
    now = datetime.now()
    if now.hour < 8 or now.hour > 21 or (now.hour == 21 and now.minute >= 30):
        print(f"当前时间 {now.strftime('%H:%M')} 不在运行窗口 (8:00-21:30)，退出")
        return

    print("========== AI 智能快讯机器人启动 ==========")
    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
    print(f"当前时间: {current_time}")

    # 1. 采集同花顺新闻
    ths_news = fetch_10jqka_news()
    # 2. 采集财联社新闻
    cls_news = fetch_cls_news(page_size=30)
    # 3. 合并
    all_news = ths_news + cls_news
    print(f"总计采集 {len(all_news)} 条快讯")

    if not all_news:
        print("未采集到任何新闻，退出")
        return

    # 4. 按时间排序（最新在前）
    all_news.sort(key=lambda x: x['_ctime'], reverse=True)

    # 5. 加载历史去重
    old_links = load_history()
    print(f"历史已推送 {len(old_links)} 条")

    new_news = [item for item in all_news if item['link'] not in old_links]
    print(f"新新闻数量: {len(new_news)}")

    if not new_news:
        print("没有新新闻，发送暂无信息通知")
        no_news_msg = f"## 📭 暂无新财经资讯\n**{current_time}**\n\n未发现新的快讯。"
        if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
            send_to_wecom(format_for_wecom(no_news_msg), msg_type="markdown")
        elif SERVERCHAN_SENDKEY:
            send_to_serverchan(no_news_msg)
        return

    # 6. AI 总结
    ai_report = ai_summarize_news(new_news)
    if ai_report:
        final_report = f"## 🤖 AI 精选快讯简报\n**{current_time}**\n\n{ai_report}"
    else:
        print("AI 总结失败，使用原始列表降级推送")
        lines = [f"## 📈 原始快讯列表（未筛选）\n**{current_time}**\n"]
        for idx, item in enumerate(new_news, 1):
            lines.append(f"{idx}. **{item['title']}** ({item['pub_date']})")
            if item['snippet']:
                lines.append(f"   {item['snippet']}")
            lines.append(f"   来源: {item['source']}\n")
        final_report = "\n".join(lines)

    # 7. 推送
    if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
        formatted = format_for_wecom(final_report)
        parts = split_long_message(formatted, max_bytes=4000)
        for idx, part in enumerate(parts, 1):
            header = f"**【AI快讯简报】第{idx}/{len(parts)}部分**\n\n"
            send_to_wecom(header + part, msg_type="markdown")
    elif SERVERCHAN_SENDKEY:
        send_to_serverchan(final_report)

    # 8. 更新历史记录
    new_links = old_links.union({item['link'] for item in new_news})
    save_history(new_links)
    print(f"历史记录已更新，总数: {len(new_links)}")
    commit_and_push()

    print("========== 运行结束 ==========")

if __name__ == "__main__":
    main()

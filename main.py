import os
import json
import time
import requests
from datetime import datetime

# ================== 配置区域 ==================
# 从环境变量读取密钥（GitHub Secrets 中配置）
WECHAT_WEBHOOK_KEY = os.environ.get('WECHAT_WEBHOOK_KEY')
WECHAT_WEBHOOK_URL = os.environ.get('WECHAT_WEBHOOK_URL')
SERVERCHAN_SENDKEY = os.environ.get('SERVERCHAN_SENDKEY')

# 历史记录文件路径（用于去重）
HISTORY_FILE = "history.json"

# 同花顺快讯 API 地址（你提供的接口）
NEWS_API_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&tag=&track=website&pagesize=400"

# ================== 1. 采集同花顺快讯 ==================
def fetch_10jqka_news():
    """直接调用同花顺快讯 API 获取新闻列表"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://news.10jqka.com.cn/",
    }
    try:
        resp = requests.get(NEWS_API_URL, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"API 请求失败，状态码: {resp.status_code}")
            return []
        data = resp.json()
        if data.get("code") != "200":
            print(f"API 返回错误: {data.get('msg')}")
            return []
        news_list = data.get("data", {}).get("list", [])
        all_news = []
        for item in news_list:
            # 转换发布时间戳
            ctime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(item.get("ctime", 0))))
            # 生成唯一链接（用于去重）
            url = item.get("url")
            if not url:
                url = f"https://news.10jqka.com.cn/{item.get('id')}.html"
            all_news.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "snippet": item.get("digest", ""),
                "link": url,
                "source": "同花顺快讯",
                "pub_date": ctime,
                "timestamp": datetime.now().isoformat(),
            })
        print(f"成功采集 {len(all_news)} 条快讯")
        return all_news
    except Exception as e:
        print(f"采集出错: {e}")
        return []

# ================== 2. 历史记录管理（去重） ==================
def load_history():
    """加载已推送的链接集合"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return set(data.get("pushed_links", []))

def save_history(links):
    """保存已推送的链接集合到文件"""
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump({"pushed_links": list(links)}, f, ensure_ascii=False, indent=2)

def commit_and_push():
    """将 history.json 的变更提交到 Git 仓库（用于 GitHub Actions）"""
    import subprocess
    # 检查是否有变更
    result = subprocess.run(["git", "status", "--porcelain", HISTORY_FILE], capture_output=True, text=True)
    if not result.stdout.strip():
        print("没有需要提交的变更")
        return
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@github-actions.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "News Bot"], check=True)
        subprocess.run(["git", "add", HISTORY_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"Update news history - {datetime.now().isoformat()}"], check=True)
        # 获取远程 URL 并注入 GITHUB_TOKEN 进行推送
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

# ================== 3. 企业微信推送（支持长消息拆分） ==================
def split_long_message(content, max_bytes=4000):
    """将长文本按最大字节数拆分，尽量保持段落完整"""
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
            # 如果单个段落超长，暴力切割
            if len(para.encode('utf-8')) > max_bytes:
                for i in range(0, len(para), max_bytes):
                    messages.append(para[i:i+max_bytes])
            else:
                current_msg = para + '\n'
    if current_msg:
        messages.append(current_msg)
    return messages

def send_to_wecom(content, msg_type="markdown"):
    """推送消息到企业微信群"""
    if not WECHAT_WEBHOOK_KEY and not WECHAT_WEBHOOK_URL:
        print("未配置企业微信 Webhook，跳过推送")
        return False
    # 构造 webhook URL
    if WECHAT_WEBHOOK_URL:
        webhook_url = WECHAT_WEBHOOK_URL
    else:
        webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"
    # 企业微信单条消息长度限制
    max_len = 4096 if msg_type == "markdown" else 2048
    if len(content.encode('utf-8')) > max_len:
        content = content.encode('utf-8')[:max_len-100].decode('utf-8', errors='ignore') + "\n\n...（消息过长已截断）"
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
    """通过 Server酱 推送到个人微信（备用通道）"""
    if not SERVERCHAN_SENDKEY:
        return False
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    data = {"title": "【快讯简报】", "desp": content}
    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            print("Server酱推送成功")
            return True
        else:
            print(f"Server酱推送失败，状态码: {resp.status_code}")
            return False
    except Exception as e:
        print(f"Server酱异常: {e}")
        return False

def format_for_wecom(report):
    """优化企业微信 Markdown 在手机端的换行显示"""
    lines = report.split('\n')
    formatted = []
    for line in lines:
        if line.strip():
            formatted.append(line + "  ")   # 每行末尾加两个空格强制换行
    separator = "\n<font color=\"comment\">---</font>\n"
    return separator.join(formatted)

# ================== 4. 生成简报（纯文本，不使用 AI） ==================
def generate_report(news_list, current_time):
    """根据新新闻生成 Markdown 格式的简报"""
    if not news_list:
        return None
    lines = [f"## 📈 同花顺快讯简报\n**{current_time}**\n"]
    for idx, news in enumerate(news_list, 1):
        lines.append(f"{idx}. **{news['title']}** ({news['pub_date']})")
        if news['snippet']:
            lines.append(f"   {news['snippet']}")
        lines.append(f"   来源: {news['source']}\n")
    return "\n".join(lines)

# ================== 5. 主程序 ==================
def main():
    print("========== 新闻机器人启动 ==========")
    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
    print(f"当前时间: {current_time}")

    # 1. 采集新闻
    all_news = fetch_10jqka_news()
    print(f"采集到 {len(all_news)} 条快讯")

    if not all_news:
        print("未采集到任何新闻，退出")
        return

    # 2. 加载已推送历史
    old_links = load_history()
    print(f"历史已推送 {len(old_links)} 条")

    # 3. 过滤出新新闻（基于链接去重）
    new_news = [item for item in all_news if item['link'] not in old_links]
    print(f"新新闻数量: {len(new_news)}")

    # 4. 如果没有新新闻，发送“暂无新信息”通知
    if not new_news:
        print("没有新新闻，发送暂无信息通知")
        no_news_msg = f"## 📭 暂无新财经资讯\n**{current_time}**\n\n未发现同花顺快讯有新的内容。"
        if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
            formatted = format_for_wecom(no_news_msg)
            send_to_wecom(formatted, msg_type="markdown")
        elif SERVERCHAN_SENDKEY:
            send_to_serverchan(no_news_msg)
        return

    # 5. 生成简报
    report = generate_report(new_news, current_time)
    if not report:
        print("生成简报失败")
        return

    # 6. 推送（优先企业微信，支持长消息拆分）
    if WECHAT_WEBHOOK_KEY or WECHAT_WEBHOOK_URL:
        formatted_report = format_for_wecom(report)
        parts = split_long_message(formatted_report, max_bytes=4000)
        success_all = True
        for idx, part in enumerate(parts, 1):
            header = f"**【快讯简报】第{idx}/{len(parts)}部分**\n\n"
            if not send_to_wecom(header + part, msg_type="markdown"):
                success_all = False
        # 如果企业微信全部失败，尝试 Server酱 备用
        if not success_all and SERVERCHAN_SENDKEY:
            print("企业微信推送失败，尝试 Server酱...")
            send_to_serverchan(report)
    elif SERVERCHAN_SENDKEY:
        # 没有企业微信配置，直接用 Server酱
        send_to_serverchan(report)
    else:
        print("未配置任何推送通道，无法发送")

    # 7. 更新历史记录
    new_links = old_links.union({item['link'] for item in new_news})
    save_history(new_links)
    print(f"历史记录已更新，当前总数: {len(new_links)}")

    # 8. 提交历史记录到仓库（GitHub Actions 环境使用）
    commit_and_push()

    print("========== 运行结束 ==========")

if __name__ == "__main__":
    main()

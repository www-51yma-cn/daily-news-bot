import os
import requests
import json
import time
from openai import OpenAI
from ddgs import DDGS

# ================== 配置区域 ==================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
# 企业微信机器人 Webhook Key（只需要 key= 后面的参数）
WECHAT_WEBHOOK_KEY = os.environ.get('WECHAT_WEBHOOK_KEY')
# 完整 Webhook URL（可选，如果直接存完整 URL 就用这个）
WECHAT_WEBHOOK_URL = os.environ.get('WECHAT_WEBHOOK_URL')
# 备用：Server酱（可选，留空则不启用）
SERVERCHAN_SENDKEY = os.environ.get('SERVERCHAN_SENDKEY')

# 消息长度限制（字节）
MAX_TEXT_LEN = 2048   # 文本消息最大长度
MAX_MARKDOWN_LEN = 4096  # Markdown 消息最大长度

# 在这里修改你想追踪的关键词
STOCK_KEYWORDS = ["协鑫集成", "铜陵有色", "南山铝业", "金开新能", "三峡能源", "光伏政策", "AI算力"]

# AI 的提示词
SYSTEM_PROMPT = """你是一个专业的财经新闻分析师。
请根据我提供的搜索结果，总结出最重要的几条新闻。
每条新闻用一句话概括，语言简洁，并附上来源。
最后用清晰的格式呈现。"""


# ================== 1. 联网搜索 ==================
def search_news(keywords, num_results=3):
    """使用 DuckDuckGo 搜索新闻"""
    all_news = []
    with DDGS() as ddgs:
        for kw in keywords:
            print(f"正在搜索：{kw}")
            try:
                results = list(ddgs.text(f"{kw} 最新消息", region="cn", safesearch="moderate", max_results=num_results))
                for r in results:
                    all_news.append({
                        "title": r.get('title'),
                        "snippet": r.get('body'),
                        "link": r.get('href'),
                        "source": r.get('href').split('/')[2] if r.get('href') else '未知'
                    })
            except Exception as e:
                print(f"搜索 {kw} 时出错: {e}")
    return all_news


# ================== 2. AI 总结 ==================
def summarize_news(news_list, retries=2):
    """调用 DeepSeek 大模型总结新闻，带超时和重试机制"""
    if not news_list:
        return "今天没有搜索到相关新闻。"

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=30.0,
    )

    news_text = json.dumps(news_list, ensure_ascii=False, indent=2)
    user_prompt = f"请用中文总结以下最新新闻，形成一份简报：\n\n{news_text}"

    for attempt in range(retries):
        try:
            print(f"正在尝试调用 AI，第 {attempt + 1} 次...")
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
            print("AI 调用成功。")
            return summary
        except Exception as e:
            print(f"AI 总结失败 (尝试 {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                print("等待 5 秒后重试...")
                time.sleep(5)
            else:
                return f"AI 总结在重试 {retries} 次后依然失败，错误：{e}\n\n以下是原始新闻数据：\n\n{news_text}"


# ================== 3. 企业微信推送 ==================
def send_to_wecom(content, msg_type="markdown"):
    """
    使用企业微信机器人推送消息
    msg_type: "text" 或 "markdown"
    """
    if not WECHAT_WEBHOOK_KEY and not WECHAT_WEBHOOK_URL:
        print("未配置企业微信 Webhook，跳过推送")
        return False

    # 处理内容长度限制
    if msg_type == "text" and len(content.encode('utf-8')) > MAX_TEXT_LEN:
        content = content[:MAX_TEXT_LEN - 100] + "\n\n...（消息过长已截断）"
    elif msg_type == "markdown" and len(content.encode('utf-8')) > MAX_MARKDOWN_LEN:
        content = content[:MAX_MARKDOWN_LEN - 100] + "\n\n...（消息过长已截断）"

    # 构建请求体
    if msg_type == "text":
        payload = {
            "msgtype": "text",
            "text": {
                "content": content,
                "mentioned_list": ["@all"]  # 可选：@所有人
            }
        }
    else:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }

    # 构建 Webhook URL
    if WECHAT_WEBHOOK_URL:
        webhook_url = WECHAT_WEBHOOK_URL
    else:
        webhook_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={WECHAT_WEBHOOK_KEY}"

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        result = response.json()

        if result.get('errcode') == 0:
            print(f"企业微信推送成功！")
            return True
        elif result.get('errcode') == 45009:
            print(f"企业微信推送失败：API 频率超限，请稍后重试。错误码：{result}")
            return False
        else:
            print(f"企业微信推送失败，错误信息：{result}")
            return False
    except Exception as e:
        print(f"企业微信推送出错: {e}")
        return False


# ================== 4. 备用：Server酱推送 ==================
def send_to_serverchan(content):
    """通过 Server酱 推送到微信（备用通道）"""
    if not SERVERCHAN_SENDKEY:
        return False

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"
    data = {
        "title": "【每日财经资讯】",
        "desp": content
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("Server酱 推送成功！")
            return True
        else:
            print(f"Server酱 推送失败，状态码：{response.status_code}")
            return False
    except Exception as e:
        print(f"Server酱 推送出错: {e}")
        return False


# ================== 主程序 ==================
def format_for_wecom(report):
    """
    将报告格式化为适合企业微信 Markdown 的格式
    """
    lines = report.split('\n')
    formatted_lines = []

    for line in lines:
        # 防止手机端换行失效，每行末尾添加两个空格
        if line.strip():
            formatted_lines.append(line + "  ")

    # 使用 <font color="comment">---</font> 作为分隔线强制换行
    separator = "\n<font color=\"comment\">---</font>\n"

    return separator.join(formatted_lines)


if __name__ == "__main__":
    print("========== 新闻机器人启动 ==========")

    # Step 1: 联网搜索
    news_list = search_news(STOCK_KEYWORDS, num_results=3)
    print(f"找到 {len(news_list)} 条新闻")

    # Step 2: AI 总结
    report = summarize_news(news_list)
    print("总结完成，正在推送...")

    # Step 3: 推送到企业微信
    formatted_report = format_for_wecom(report)
    push_success = send_to_wecom(formatted_report, msg_type="markdown")

    # Step 4: 如果企业微信推送失败，尝试备用通道（Server酱）
    if not push_success and SERVERCHAN_SENDKEY:
        print("企业微信推送失败，尝试使用 Server酱 备用通道...")
        send_to_serverchan(report)

    print("========== 运行结束 ==========")

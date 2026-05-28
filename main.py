import requests
import json
import os
from openai import OpenAI
from ddgs import DDGS

# ================== 配置区域 ==================
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
PUSH_KEY = os.environ.get('SERVERCHAN_SENDKEY')

# 在这里修改你想追踪的关键词（股票、新闻等）
STOCK_KEYWORDS = ["协鑫集成", "铜陵有色", "南山铝业", "金开新能", "三峡能源", "光伏政策", "AI算力"]

# AI 的提示词（可以改成你喜欢的风格）
SYSTEM_PROMPT = """你是一个专业的财经新闻分析师。
请根据我提供的搜索结果，总结出最重要的几条新闻。
每条新闻用一句话概括，语言简洁，并附上来源。
最后用清晰的格式呈现。"""

# ================== 1. 联网搜索（使用 ddgs） ==================
def search_news(keywords, num_results=3):
    """使用 DuckDuckGo 搜索新闻"""
    all_news = []
    with DDGS() as ddgs:
        for kw in keywords:
            print(f"正在搜索：{kw}")
            try:
                # 搜索网页（包含新闻）
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
def summarize_news(news_list):
    """调用 DeepSeek 大模型总结新闻"""
    if not news_list:
        return "今天没有搜索到相关新闻。"

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    news_text = json.dumps(news_list, ensure_ascii=False, indent=2)
    user_prompt = f"请用中文总结以下最新新闻，形成一份简报：\n\n{news_text}"

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            stream=False,
            temperature=0.7
        )
        summary = response.choices[0].message.content
        return summary
    except Exception as e:
        print(f"AI 总结失败: {e}")
        return f"AI 总结失败，请查看原始新闻：\n\n{news_text}"

# ================== 3. 推送到微信 ==================
def send_to_wechat(content):
    """通过 Server酱 推送到微信"""
    if not PUSH_KEY:
        print("未配置 PUSH_KEY，无法推送")
        return False
    url = f"https://sctapi.ftqq.com/{PUSH_KEY}.send"
    data = {
        "title": "【每日财经资讯】",
        "desp": content
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("推送成功！")
            return True
        else:
            print(f"推送失败，状态码：{response.status_code}")
            return False
    except Exception as e:
        print(f"推送出错: {e}")
        return False

# ================== 主程序 ==================
if __name__ == "__main__":
    print("========== 新闻机器人启动 ==========")
    news_list = search_news(STOCK_KEYWORDS, num_results=3)
    print(f"找到 {len(news_list)} 条新闻")
    report = summarize_news(news_list)
    print("总结完成，正在推送...")
    send_to_wechat(report)
    print("========== 运行结束 ==========")

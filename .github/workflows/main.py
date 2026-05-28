import requests
import json
import os
from openai import OpenAI
import feedparser

# ================== 配置区域 ==================
SEARCH_ENGINE_ID = "你的 谷歌可编程搜索引擎 ID"  # 你获得的搜索ID
GOOGLE_API_KEY = "你的 谷歌自定义搜索 API Key"  # 你申请的API Key
DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY')
PUSH_KEY = os.environ.get('SERVERCHAN_SENDKEY')

# 在这里修改你想追踪的股票或新闻关键词，用逗号隔开
STOCK_KEYWORDS = ["协鑫集成", "铜陵有色", "南山铝业", "金开新能", "三峡能源", "科技新闻", "光伏政策", "美联储"]

# AI 总结的指示语，你可以根据喜好修改
SYSTEM_PROMPT = """你是一个专业的新闻分析师，擅长总结和提炼信息。
请根据我提供的搜索结果，提取最重要的几条新闻。
要求：每条新闻用一句话概括，语言简洁、客观，并附上来源。最终结果需要清晰易读。"""

# ================== 功能函数：1. 联网搜索 ==================
def search_news(keywords, num_results=3):
    """使用 Google 可编程搜索引擎搜索新闻"""
    all_news = []
    for kw in keywords:
        print(f"正在搜索：{kw}")
        # 构建搜索URL
        search_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={SEARCH_ENGINE_ID}&q={kw}&num={num_results}"
        try:
            response = requests.get(search_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                for item in items:
                    all_news.append({
                        "title": item['title'],
                        "snippet": item.get('snippet', ''),
                        "link": item['link'],
                        "source": item.get('displayLink', '')
                    })
            else:
                print(f"搜索 {kw} 失败，状态码：{response.status_code}")
        except Exception as e:
            print(f"搜索 {kw} 时发生错误: {e}")
    return all_news

# ================== 功能函数：2. AI 总结 ==================
def summarize_news(news_list):
    """调用 DeepSeek 大模型来总结新闻"""
    if not news_list:
        return "抱歉，今天没有搜索到相关的新闻。"

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    news_text = json.dumps(news_list, ensure_ascii=False, indent=2)
    user_prompt = f"请用中文总结以下最新的股票和财经新闻，形成一份简报。\n\n{news_text}"

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
        print(f"调用 AI 总结失败: {e}")
        return f"AI 总结失败，请查看原始新闻。\n\n{news_text}"

# ================== 功能函数：3. 推送到微信 ==================
def send_to_wechat(content):
    """通过 Server酱 将消息推送到微信"""
    if not PUSH_KEY:
        print("未配置 PUSH_KEY，无法推送")
        return False
    url = f"https://sctapi.ftqq.com/{PUSH_KEY}.send"
    data = {
        "title": "【您的专属财经早报】",
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
        print(f"推送时发生错误: {e}")
        return False

# ================== 主程序逻辑 ==================
if __name__ == "__main__":
    print("========== 财经早报机器人启动 ==========")
    # Step 1: 联网搜索
    raw_news = search_news(STOCK_KEYWORDS, num_results=3)
    print(f"共搜索到 {len(raw_news)} 条原始新闻")
    # Step 2: AI 总结
    final_report = summarize_news(raw_news)
    print("新闻总结完成")
    # Step 3: 推送到微信
    send_to_wechat(final_report)
    print("========== 财经早报机器人运行结束 ==========")

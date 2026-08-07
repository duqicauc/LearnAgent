import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv() # 加载环境变量
client = OpenAI(
    api_key = os.getenv("DEEPSEEK_API_KEY"),
    base_url = "https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[
        {"role": "user", "content": "你好"}
    ],
    extra_body={
       "thinking":{"type":"disabled"}
    },
)

print(response.choices[0].message.content)

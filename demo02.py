import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # 加载环境变量
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

messages = []
print("=== 多轮对话已启动（输入 'exit' 或 'quit' 结束）===")

while True:
    user_input = input("\n你: ")
    if user_input.lower() in ("exit", "quit"):
        print("再见！")
        break

    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=messages,
        extra_body={"thinking": {"type": "disabled"}},
    )

    assistant_reply = response.choices[0].message.content
    messages.append({"role": "assistant", "content": assistant_reply})

    print(f"\nAI: {assistant_reply}")

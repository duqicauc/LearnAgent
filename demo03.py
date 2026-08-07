import os
import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

DB_PATH = Path(__file__).parent / "users.json"

with open(DB_PATH, "r", encoding="utf-8") as f:
    USERS_DB = json.load(f)

# ── 工具定义（以 JSON Schema 形式注册给 AI） ──
tools = [
    {
        "type": "function",
        "function": {
            "name": "query_users",
            "description": "从用户数据库中查询用户信息，支持按姓名、部门、城市、技能等条件筛选，可返回全部或指定条件匹配的用户列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "按姓名精确匹配",
                    },
                    "department": {
                        "type": "string",
                        "description": "按部门筛选，如：工程部、产品部、设计部、市场部",
                    },
                    "city": {
                        "type": "string",
                        "description": "按所在城市筛选",
                    },
                    "skill": {
                        "type": "string",
                        "description": "按技能关键词筛选（匹配 skills 列表中的任一技能）",
                    },
                    "min_salary": {
                        "type": "integer",
                        "description": "最低薪资",
                    },
                    "only_active": {
                        "type": "boolean",
                        "description": "是否只返回在职用户",
                    },
                },
                "additionalProperties": False,
            },
        },
    }
]


def query_users(
    name: str = None,
    department: str = None,
    city: str = None,
    skill: str = None,
    min_salary: int = None,
    only_active: bool = False,
) -> str:
    """根据条件筛选用户数据库，返回 JSON 格式结果。"""
    results = []
    for user in USERS_DB:
        if name and user["name"] != name:
            continue
        if department and user["department"] != department:
            continue
        if city and user["city"] != city:
            continue
        if skill and skill not in user["skills"]:
            continue
        if min_salary is not None and user["salary"] < min_salary:
            continue
        if only_active and not user["active"]:
            continue
        results.append(user)

    return json.dumps(results, ensure_ascii=False, indent=2)


# ── 工具函数映射 ──
TOOL_MAP = {
    "query_users": query_users,
}


# ── Agent 循环 ──
def run_agent():
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个用户数据库查询助手。"
                "当用户询问员工信息时，使用 query_users 工具从数据库中检索，"
                "然后用自然语言汇总结果回复用户。"
            ),
        }
    ]

    print("=== 用户数据库 Agent 已启动（输入 'exit' 或 'quit' 结束）===")

    while True:
        user_input = input("\n你: ")
        if user_input.lower() in ("exit", "quit"):
            print("再见！")
            break

        messages.append({"role": "user", "content": user_input})

        # 第 1 步：调用 API，传入 tools
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=tools,
            extra_body={"thinking": {"type": "disabled"}},
        )

        message = response.choices[0].message

        # 第 2 步：检查是否需要调用工具
        if message.tool_calls:
            # 将 assistant 消息（含 tool_calls）加入上下文
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                }
            )

            # 第 3 步：执行所有工具调用
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)

                if func_name not in TOOL_MAP:
                    tool_result = json.dumps(
                        {"error": f"未知工具: {func_name}"}, ensure_ascii=False
                    )
                else:
                    print(f"\n  [🔧 调用工具] {func_name}({func_args})")
                    tool_result = TOOL_MAP[func_name](**func_args)
                    print(f"  [📦 工具结果] {tool_result[:200]}...")

                # 第 4 步：将工具结果回灌到消息中
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": tool_result,
                    }
                )

            # 第 5 步：再次调用 API，让 AI 基于工具结果生成最终回复
            response = client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=messages,
                extra_body={"thinking": {"type": "disabled"}},
            )

            final_reply = response.choices[0].message.content
        else:
            final_reply = message.content

        messages.append({"role": "assistant", "content": final_reply})
        print(f"\nAI: {final_reply}")


if __name__ == "__main__":
    run_agent()

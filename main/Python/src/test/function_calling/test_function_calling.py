import openai
import json

# OpenAI APIキーを設定
openai.api_key = ''

# 受け取ったデータ
received_data_from_whisper = "枕のidで10番目を動かして"

# ツールの定義
tools = [
    {
        "type": "function",
        "function": {
            "name": "move_pillow",
            "description": "指定された枕IDに基づいて、枕を新しい位置に移動します。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pillow_id": {
                        "type": "string",
                        "description": "移動する枕の一意のID。",
                    },
                },
                "required": ["pillow_id"],
                "additionalProperties": False,
            },
        }
    }
]

# メッセージの準備
messages = [
    {"role": "system", "content": "あなたは役立つカスタマーサポートアシスタントです。次のユーザーのリクエストに基づいて、必要な関数を呼び出してください。"},
    {"role": "user", "content": received_data_from_whisper}
]

# API呼び出し
response = openai.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=tools,
)

print(response)
print(type(response))

print("===========================\n")

# JSON形式でファイルに保存
with open('response.json', 'w', encoding='utf-8') as f:
    json.dump(response.to_dict(), f, ensure_ascii=False, indent=4)  # to_dict()で辞書形式に変換

# 関数名と引数の取得
if response.choices and len(response.choices) > 0:
    # 最初の選択肢を取得
    first_choice = response.choices[0]

    # tool_callsが存在するか確認
    if hasattr(first_choice.message, 'tool_calls') and len(first_choice.message.tool_calls) > 0:
        tool_call = first_choice.message.tool_calls[0]
        
        # 関数名を取得
        function_name = tool_call.function.name  # 関数名を取得

        # 引数を取得し、辞書型に変換
        arguments = json.loads(tool_call.function.arguments)  # 引数を辞書に変換

        # 出力
        print(f"Function Name: {function_name}")
        print(f"Arguments: {arguments}")
    else:
        print("Tool call not found in the response.")
else:
    print("No choices available in the response.")
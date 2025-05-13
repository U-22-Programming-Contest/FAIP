#! python3.7

import argparse
import os
import numpy as np
import speech_recognition as sr
import whisper
import torch
import pyttsx3

from datetime import datetime, timedelta
from queue import Queue
from time import sleep
from sys import platform

import openai
import json

def generate_pillow_height_response(text):
    """
    枕の高さに応じた文章を生成する関数
    """
    # GPT-4に枕の高さに関する説明文を生成させる
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "あなたは枕の高さを調整するAIアシスタントです。"},
            {"role": "user", "content": f"ユーザーが '{text}' と言いました。これに基づいて、あなたは枕をどれだけ調整したかを非常に簡潔に述べてください"}
        ]
    )
    
    # 生成された説明文を取得
    message = response.choices[0].message.content
    return message

def speak_text(text):
    """
    生成された文章を読み上げる関数
    """
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)  # 話速の調整
    engine.say(text)
    engine.runAndWait()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="base", help="Model to use",
                        choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("--non_english", action='store_true',
                        help="Don't use the english model.")
    parser.add_argument("--energy_threshold", default=1000,
                        help="Energy level for mic to detect.", type=int)
    parser.add_argument("--record_timeout", default=5,  # ここを2から5に変更
                        help="How real time the recording is in seconds.", type=float)
    parser.add_argument("--phrase_timeout", default=3,
                        help="How much empty space between recordings before we "
                             "consider it a new line in the transcription.", type=float)
    if 'linux' in platform:
        parser.add_argument("--default_microphone", default='pulse',
                            help="Default microphone name for SpeechRecognition. "
                                 "Run this with 'list' to view available Microphones.", type=str)
    args = parser.parse_args()

    phrase_time = None
    data_queue = Queue()
    recorder = sr.Recognizer()
    recorder.energy_threshold = args.energy_threshold
    recorder.dynamic_energy_threshold = False

    if 'linux' in platform:
        mic_name = args.default_microphone
        if not mic_name or mic_name == 'list':
            print("Available microphone devices are: ")
            for index, name in enumerate(sr.Microphone.list_microphone_names()):
                print(f"Microphone with name \"{name}\" found")
            return
        else:
            for index, name in enumerate(sr.Microphone.list_microphone_names()):
                if mic_name in name:
                    source = sr.Microphone(sample_rate=16000, device_index=index)
                    break
    else:
        source = sr.Microphone(sample_rate=16000)

    model = args.model
    audio_model = whisper.load_model(model)

    transcription = ['']

    with source:
        recorder.adjust_for_ambient_noise(source)

    def record_callback(_, audio: sr.AudioData) -> None:
        data = audio.get_raw_data()
        data_queue.put(data)

    recorder.listen_in_background(source, record_callback, phrase_time_limit=args.record_timeout)

    print("モデルが読み込まれました。\n")

    ##### function calling

    # OpenAI APIキーを設定
    openai.api_key = os.getenv('OPENAI_API_KEY')

    # ツールの定義
    tools = [
        {
            "type": "function",
            "function": {
                "name": "change_pillow_height",
                "description": "枕の高さを変更する関数",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pillow_height": {
                            "type": "string",
                            "description": "枕の高さを実数値で指定します。ユーザーが発話した副詞（例: 'ちょっと', 'もう少し', 'もっと' など）に応じて、自動的に値が決定されます。枕を高くしたいときは 0から1の範囲で値が設定され、枕を低くしたいときは -1から0 の範囲で設定されます。弱い表現（'ちょっと' など）は低い値、強い表現（'もっと' など）は高い値に対応します。"
                        },
                    },
                    "required": ["pillow_height"],
                    "additionalProperties": False,
                },
            }
        }
    ]

    ######

    pillow_air_pressure_value = 0

    while True:
        try:
            now = datetime.utcnow()
            if not data_queue.empty():
                phrase_complete = False
                if phrase_time and now - phrase_time > timedelta(seconds=args.phrase_timeout):
                    phrase_complete = True
                phrase_time = now
                
                audio_data = b''.join(data_queue.queue)
                data_queue.queue.clear()
                
                audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

                # デバッグ: 音声データの長さを表示
                print(f"取得した音声データのバイト数: {len(audio_data)}")

                # Whisperでのトランスクリプションを取得 (言語を日本語に指定)
                result = audio_model.transcribe(audio_np, fp16=torch.backends.mps.is_available(), language="ja")
                text = result['text'].strip()

                # デバッグ: トランスクリプトを表示
                print(f"トランスクリプト: {text}")

                ##### function calling

                received_data_from_whisper = text

                # メッセージの準備
                messages = [
                    {"role": "system", "content": "あなたはAI枕です。ユーザの意図を読み取って枕の高さを調節してください"},
                    {"role": "user", "content": received_data_from_whisper}
                ]

                # API呼び出し
                response = openai.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    tools=tools,
                )

                # JSON形式でファイルに保存
                with open('response.json', 'w', encoding='utf-8') as f:
                    json.dump(response.to_dict(), f, ensure_ascii=False, indent=4)  # to_dict()で辞書形式に変換

                # 関数名と引数の取得
                if response.choices and len(response.choices) > 0:
                    # 最初の選択肢を取得
                    first_choice = response.choices[0]

                    # tool_callsが存在するか確認
                    if hasattr(first_choice.message, 'tool_calls') and (first_choice.message.tool_calls != None):
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
                        pillow_air_pressure_value = 0
                        continue
                else:
                    print("No choices available in the response.")

                ################

                if phrase_complete:
                    transcription.append(text)
                else:
                    transcription[-1] = text

                os.system('cls' if os.name == 'nt' else 'clear')
                # for line in transcription:
                #     print(counter)
                #     print(line)
                #     print(f"Function Name: {function_name}")
                #     print(f"Arguments: {arguments}")
   
                print(f"Function Name: {function_name}")
                print(f"Arguments: {arguments}")

                try:
                    # argumentsが辞書であり、'pillow_height'キーを取得して数値に変換
                    pillow_height_str = arguments.get('pillow_height', '0')  # キーがない場合のデフォルトは '0'
                    
                    # pillow_height_strが文字列であることを確認し、数値に変換
                    pillow_air_pressure_value = float(pillow_height_str)  # 文字列を数値に変換
                except (ValueError, TypeError):
                    # 数値変換に失敗した場合は0を代入
                    pillow_air_pressure_value = 0

                print(pillow_air_pressure_value)

                generated_text = generate_pillow_height_response(text)

                print(f"生成された文章: {generated_text}")

                speak_text(generated_text)
                
                print('', end='', flush=True)
            else:
                sleep(0.25)
        except KeyboardInterrupt:
            break

    print("\n\nトランスクリプション:")
    for line in transcription:
        print(line)

if __name__ == "__main__":
    main()

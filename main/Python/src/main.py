import serial
import time
import threading
import numpy as np
import argparse
import os
import speech_recognition as sr
import whisper
import torch
import pyttsx3
import openai
import json
from datetime import datetime, timedelta
from queue import Queue
from time import sleep
from sys import platform
from pkg import bluetooth_server
from pkg import space_separated_parser 
from pkg import dnn_air_pressure_model
from pkg import dnn_sleep_position_model

def generate_pillow_height_response(text):
    """
    枕の高さに応じた文章を生成する関数
    """

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "あなたは枕の高さを調整するAIアシスタントです。"},
            {"role": "user", "content": f"ユーザーが '{text}' と言いました。これに基づいて、あなたは枕をどれくらい調整するのかを数値なしで非常に簡潔に述べてください"}
        ]
    )
    
    message = response.choices[0].message.content
    return message

def speak_text(text):
    """
    生成された文章を読み上げる関数
    """
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)  
    engine.say(text)
    engine.runAndWait()

def inputFromTerminal():
    print("小型ポンプ停止コマンド : S")
    while True:
        user_input = input()
        if user_input == "S":
            user_input = user_input + "\n" 
            ser.write(user_input.encode("utf-8"))
            print("Python send :" + user_input)

def main():

    # コマンドライン引数の設定
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small", help="Model to use",
                        choices=["tiny", "base", "small", "medium", "large"])
    parser.add_argument("--non_english", action='store_true',
                        help="Don't use the english model.")
    parser.add_argument("--energy_threshold", default=1000,
                        help="Energy level for mic to detect.", type=int)
    parser.add_argument("--record_timeout", default=5,  
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
                            "description": "枕の高さを実数値で指定します。ユーザーが発話した副詞（例: 'ちょっと', 'もう少し', 'もっと', 'さらに', 'かなり', 'もっと', 'もっともっと', '一段と', など）に応じて、自動的に値が決定されます。枕を高くしたいときは 0から0.3の範囲で値が設定され、枕を低くしたいときは -0.3から0 の範囲で設定されます。弱い表現（'ちょっと' など）は低い値、強い表現（'もっと' など）は高い値に対応します。"
                        },
                    },
                    "required": ["pillow_height"],
                    "additionalProperties": False,
                },
            }
        }
    ]

    pillow_air_pressure_value = 0

    # 別スレッドで実行
    inputThread = threading.Thread(target=inputFromTerminal)
    inputThread.start()
        
    ser = serial.Serial("COM5", 9600, timeout=0.1)

    server = bluetooth_server.BluetoothServer(ser)
    parser = space_separated_parser.SpaceSeparatedParser()

    dnn_model = dnn_air_pressure_model.DnnAirPressureModel((4,), 4)
    dnn_model.load_model('../model/dnn_air_pressure_model/pressure_model_widgets.h5')

    # 通信が確立されるまで処理を待つ
    while True:

        # Arduinoから受け取る
        val_byte = ser.readline()
        val_string = val_byte.decode("utf-8")
        print("Python receive :" + val_string)

        # 通信を確立するための処理
        ser.write("request connection\n".encode("utf-8"))
        print("Python send :" + "request connection\n")
        time.sleep(1)

        if(val_string == "connection established\n"):
            break


    while True:

        # リクエストをPython側から送る処理
        request = "request loadcell value\n"
        ser.write(request.encode("utf-8"))
        print("Python send :" + request)

        while True:

            # Arduinoから受け取る
            val_byte = ser.readline()
            val_string = val_byte.decode("utf-8")
            print("Python receive :" + val_string)

            time.sleep(1)

            val_spilited = val_string.split()

            if(val_spilited[0] == "response"):
                if(parser.loadsMessage(val_string)):
                    id = parser.get("id")
                    response = f"retval 0 id {str(id[0])}\n"
                    ser.write(response.encode("utf-8"))
                    print("Python send :" + response)
                    break
                else:
                    id = parser.get("id")
                    response = f"retval -1 id {str(id[0])}\n"
                    ser.write(response.encode("utf-8"))
                    print("Python send :" + response)

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
                result = audio_model.transcribe(audio_np, fp16=torch.backends.mps.is_available())
                text = result['text'].strip()

                # デバッグ: トランスクリプトを表示
                print(f"トランスクリプト: {text}")

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
                        pillow_air_pressure_value += 0
                        continue
                else:
                    print("No choices available in the response.")

                if phrase_complete:
                    transcription.append(text)
                else:
                    transcription[-1] = text

                os.system('cls' if os.name == 'nt' else 'clear')
   
                # 関数名と引数の表示
                print(f"Function Name: {function_name}")
                print(f"Arguments: {arguments}")

                try:
                    # argumentsが辞書であり、'pillow_height'キーを取得して数値に変換
                    pillow_height_str = arguments.get('pillow_height', '0')  # キーがない場合のデフォルトは '0'
                    
                    # pillow_height_strが文字列であることを確認し、数値に変換
                    pillow_air_pressure_value += float(pillow_height_str)  # 文字列を数値に変換
                except (ValueError, TypeError):
                    # 数値変換に失敗した場合は0を代入
                    pillow_air_pressure_value += 0

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
        
        # ロードセルの値を使って推論処理
        loadcell_list = parser.get("value")
        new_data = np.array([loadcell_list])
        predicted_air_pressure = dnn_model.predict(new_data) + pillow_air_pressure_value
        server.setAirPressureRslt(predicted_air_pressure)
        ser.write("nofitication prediction completed\n".encode("utf-8"))
        print("Python send :" + "nofitication prediction completed\n")

        # リクエストがArduino側から来る時の処理
        while True:

            # Arduinoから受け取る
            val_byte = ser.readline()
            val_string = val_byte.decode("utf-8")
            print("Python receive :" + val_string)

            if(val_string == "request predictedAirPressure value\n"):
                server.responseMessage()

                start_time = time.time()

                # 5秒成功処理が来なかったら再送
                while True:

                    val_byte = ser.readline()
                    val_string = val_byte.decode("utf-8")
                    print("Python receive :" + val_string)

                    val_spilited = val_string.split()

                    if len(val_spilited) > 0 and val_spilited[0] == "retval":

                        if val_string == f"retval 0 id {server.getId()}\n":
                            break

                        MAX_WAIT_TIME_SEC = 5 
                        if time.time() - start_time > MAX_WAIT_TIME_SEC:
                            print("time out : resend\n")
                            server.resendMessage()
                            break
                
                break

        # 小型ポンプの終了通知が来るまで処理を中断する
        while True:
            # Arduinoから受け取る
            val_byte = ser.readline()
            val_string = val_byte.decode("utf-8")
            print("Python receive :" + val_string)

            if (val_string == "nofitication air inflation completed\n"):
                break


if __name__ == "__main__":
    main()
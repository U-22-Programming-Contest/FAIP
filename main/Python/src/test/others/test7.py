import pyttsx3

# pyttsx3エンジンの初期化
engine = pyttsx3.init()

# 読み上げるテキスト
text = "これを読みます"

# 読み上げるテキストを設定
engine.say(text)

# 読み上げを実行
engine.runAndWait()

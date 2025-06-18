from flask import Flask, request, jsonify
from logger import logger
import requests
import os
import gc
import psutil
import time
import threading
from openai import OpenAI, RateLimitError, APIError, Timeout, AuthenticationError
from pydub import AudioSegment

app = Flask(__name__)

ACCESS_TOKEN = "EAAIdbZCyeyLoBOxELG4tXyWbTEFUotybXqvxhUhldUm8vVRVYafi8dt6zKgvbzKN9Lps3JPjVtLsvJZAF9a93ZB9ariMQzBoAR1ra7Ar8ckVIElFb8oKkgovZBiK1hdcOijMaaLRgG89vZB4msxnO086fd1i5NRwRpQIsWZBaEXNnt1yR8GArnyYzZBAP3up30OMyz1DP5p1R8ZAZBDSuZBZA0dzovXvzOhAGv6sdSTmCD0nWFgAZCcBXMwZD"
API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")

client = OpenAI(api_key=openai_api_key)
logger.info(f"\ud83d\udd10 OpenAI API key начинается на: {openai_api_key[:5]}..., длина: {len(openai_api_key)}")

SKIP_AI_PHRASES = ["ок", "спасибо", "понятно", "ясно", "пока", "привет", "здрасте", "да", "нет"]

@app.after_request
def after_request_cleanup(response):
    gc.collect()
    log_memory_usage()
    cleanup_temp_files()
    return response

def log_memory_usage():
    process = psutil.Process()
    mem_mb = process.memory_info().rss / 1024 / 1024
    logger.info(f"\ud83e\udde0 Используемая память: {mem_mb:.2f} MB")

def cleanup_temp_files():
    tmp_path = "/tmp"
    if not os.path.exists(tmp_path):
        return
    for fname in os.listdir(tmp_path):
        if fname.endswith((".wav", ".mp3", ".ogg")):
            try:
                os.remove(os.path.join(tmp_path, fname))
                logger.info(f"\ud83e\udd79 Удален временный файл: {fname}")
            except Exception as e:
                logger.warning(f"\u274c Ошибка удаления файла {fname}: {e}")

@app.route('/', methods=['GET'])
def home():
    return "Сервер работает!"

@app.route("/ping")
def ping():
    return "OK", 200

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logger.info("WEBHOOK VERIFIED")
            return challenge, 200
        else:
            logger.error("VERIFICATION FAILED")
            return "Verification failed", 403

    elif request.method == 'POST':
        data = request.json
        logger.info("Получено сообщение: %s", data)

        if data.get('object') == 'whatsapp_business_account':
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})

                    for message in value.get('messages', []):
                        handle_message(
                            message,
                            value['metadata']['phone_number_id'],
                            value['metadata']['display_phone_number'],
                            value.get('contacts', [])
                        )

                    for status in value.get('statuses', []):
                        handle_status(status)

        return jsonify({"status": "success"}), 200

def handle_message(message, phone_number_id, bot_display_number, contacts):
    from_number = message.get("from")

    if from_number.endswith(bot_display_number[-9:]):
        logger.info("\ud83d\udd01 Эхо-сообщение от самого себя — пропущено")
        return

    normalized_number = normalize_for_meta(from_number)
    name = contacts[0].get("profile", {}).get("name") if contacts else "друг"

    if message.get("type") == "text":
        text = message.get("text", {}).get("body", "").strip()
        process_text_message(text, normalized_number, phone_number_id, name)

    elif message.get("type") == "audio":
        logger.info("\ud83c\udfbc Аудио передаётся на фон для обработки")
        threading.Thread(target=handle_audio_async, args=(message, phone_number_id, normalized_number, name)).start()

def handle_audio_async(message, phone_number_id, normalized_number, name):
    try:
        audio_id = message["audio"]["id"]
        logger.info(f"\ud83c\udfbf Обработка голосового файла, media ID: {audio_id}")
        text = transcribe_voice_message(audio_id, phone_number_id, normalized_number)
        if not text:
            return
        process_text_message(text, normalized_number, phone_number_id, name)
    except Exception as e:
        logger.error(f"\u274c Ошибка фоновой обработки аудио: {e}")

def process_text_message(text, normalized_number, phone_number_id, name):
    if not text:
        return

    logger.info(f"\ud83d\udcec Сообщение от {normalized_number}: {text}")

    if text.lower() in SKIP_AI_PHRASES:
        return

    if len(text) > 500:
        text = text[:500]

    try:
        response = get_ai_response(text)
        send_text_message(phone_number_id, normalized_number, response)
        return

    except AuthenticationError as e:
        logger.error(f"\ud83d\udd10 Ошибка авторизации OpenAI: {e}")

    except RateLimitError:
        logger.warning("\u26a0\ufe0f Превышен лимит OpenAI")
        send_text_message(phone_number_id, normalized_number, "Сервер перегружен. Попробуйте позже.")
        return

    except (APIError, Timeout) as e:
        logger.error(f"\u26d4\ufe0f Сетевая ошибка OpenAI: {e}")
        send_text_message(phone_number_id, normalized_number, "Техническая ошибка. Повторите позже.")
        return

    except Exception as e:
        logger.error(f"\ud83e\udd16 Неизвестная ошибка OpenAI: {e}")

    category = extract_category(text)
    if name and category:
        sent = send_template_message(phone_number_id, normalized_number, "test_template_1", [name, category])
        if sent:
            return

    send_text_message(phone_number_id, normalized_number, "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!")

def transcribe_voice_message(audio_id, phone_number_id, normalized_number):
    try:
        url = f"https://graph.facebook.com/v15.0/{audio_id}"
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        media_url = resp.json().get("url")

        media_resp = requests.get(media_url, headers=headers)
        media_resp.raise_for_status()
        audio_path = "/tmp/audio.ogg"
        with open(audio_path, "wb") as f:
            f.write(media_resp.content)

        audio = AudioSegment.from_file(audio_path)
        duration_sec = len(audio) / 1000
        logger.info(f"\u23f1\ufe0f Длительность аудио: {duration_sec:.1f} секунд")
        if duration_sec > 60:
            logger.warning("\u26a0\ufe0f Аудио превышает 60 секунд")
            send_text_message(phone_number_id, normalized_number, "Пожалуйста, пришлите голосовое сообщение не длиннее 1 минуты")
            return None

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        logger.info(f"\ud83d\udd8d\ufe0f Распознано: {transcript}")
        return transcript.strip()

    except Exception as e:
        logger.error(f"\u274c Ошибка транскрибации аудио: {e}")
        return None

def get_ai_response(prompt):
    start = time.time()
    response = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[
            {"role": "system", "content": "Ты ассистент иллюзиониста Арсения. Отвечай осмысленно, дружелюбно и кратко."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=150,
        timeout=20
    )
    end = time.time()
    logger.info(f"\ud83d\udd52 Время генерации OpenAI: {end - start:.2f} сек")
    logger.info(f"\ud83d\udcc8 Использовано токенов: {response.usage.total_tokens}")
    return response.choices[0].message.content.strip()

def extract_category(text):
    lowered = text.lower()
    if "взросл" in lowered:
        return "взрослое"
    if "детск" in lowered:
        return "детское"
    if "семейн" in lowered:
        return "семейное"
    return "наше"

def normalize_for_meta(number):
    if number.startswith('77'):
        return '787' + number[2:]
    if number.startswith('79'):
        return '789' + number[2:]
    return number

def send_text_message(phone_number_id, to, text):
    url = API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"\u27a1\ufe0f Отправка текста на {to}")
    logger.info("API WhatsApp ответ: %s %s", response.status_code, response.text)

def send_template_message(phone_number_id, to, template_name, variables):
    url = API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": "ru"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": var} for var in variables]
                }
            ]
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"\u27a1\ufe0f Отправка шаблона на {to}")
    logger.info("API WhatsApp ответ: %s %s", response.status_code, response.text)
    return response.status_code == 200

def handle_status(status):
    logger.info("\ud83d\udce5 Статус: %s", status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

import os
import gc
import psutil
import time
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, abort
from logger import logger
import requests
from openai import OpenAI, RateLimitError, APIError, Timeout, AuthenticationError
from pydub import AudioSegment

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE_NAME = "tokens"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json"
}

def load_token_from_supabase():
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE_NAME}?select=token&order=updated_at.desc&limit=1"
    response = requests.get(url, headers=SUPABASE_HEADERS)
    data = response.json()
    if data:
        return data[0]["token"]
    return ""

def save_token_to_supabase(token: str):
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE_NAME}"
    payload = {"token": token}
    response = requests.post(url, json=payload, headers=SUPABASE_HEADERS)
    return response.status_code == 201

# ======= ЛОКАЛЬНЫЙ ЛОГГЕР ДЛЯ ПЕРВОГО ЭТАПА ЗАПУСКА ========
os.makedirs("tmp", exist_ok=True)
logging.basicConfig(
    filename=f"tmp/app_start_{datetime.now():%Y-%m-%d}.log",
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("myapp")
logger.propagate = False
logger.info("🟢 app.py импортирован")

app = Flask(__name__)

API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")
META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не заданы")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("📢 Telegram-уведомление отправлено")
        else:
            logger.warning(f"❌ Ошибка Telegram: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"💥 Исключение при отправке Telegram-сообщения: {e}")

client = OpenAI(api_key=openai_api_key)
logger.info(f"🔐 OpenAI API key начинается на: {openai_api_key[:5]}..., длина: {len(openai_api_key)}")

SKIP_AI_PHRASES = ["ок", "спасибо", "понятно", "ясно", "пока", "привет", "здрасте", "да", "нет"]
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
WHATSAPP_TOKEN = load_token_from_supabase()
logger.info(f"🔍 Загружен токен из Supabase: начинается на {WHATSAPP_TOKEN[:8]}..., длина: {len(WHATSAPP_TOKEN)}")

form_template = """
<!DOCTYPE html>
<html>
<head><title>Обновить токен</title></head>
<body>
  <h2>Обновление токена WhatsApp</h2>
  {% if message %}<p style=\"color:green\">{{ message }}</p>{% endif %}
  <form method=\"POST\">
    Пароль: <input type=\"password\" name=\"password\"><br><br>
    Новый токен:<br>
    <textarea name=\"token\" rows=\"6\" cols=\"80\"></textarea><br><br>
    <input type=\"submit\" value=\"Сохранить\">
  </form>
</body>
</html>
"""

@app.route("/admin/token", methods=["GET", "POST"])
def update_token():
    global WHATSAPP_TOKEN
    message = None
    if request.method == "POST":
        password = request.form.get("password")
        if password != ADMIN_PASSWORD:
            abort(403)
        token = request.form.get("token", "").strip()
        logger.info(f"📥 Токен из формы (repr): {repr(token)}")
        if token:
            save_token_to_supabase(token)
            WHATSAPP_TOKEN = token
            message = "✅ Токен успешно сохранён!"
    return render_template_string(form_template, message=message)

def get_token():
    return WHATSAPP_TOKEN

def check_token_validity():
    token = get_token()
    logger.info(f"🔍 Проверка токена: начинается на {token[:8]}..., длина: {len(token)}")
    url = f"https://graph.facebook.com/oauth/access_token_info?client_id={META_APP_ID}&client_secret={META_APP_SECRET}&access_token={token}"
    try:
        resp = requests.get(url, timeout=10)
        logger.info(f"📡 Meta ответ: {resp.status_code} {resp.text}")
        if resp.status_code != 200:
            logger.warning("❌ Токен недействителен! Сообщаем в Telegram...")
            send_telegram_alert("❗️Токен WhatsApp недействителен. Зайдите в админку и обновите его.")
        else:
            logger.info("✅ Токен действителен")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при проверке токена: {e}")
        send_telegram_alert(f"⚠️ Ошибка при проверке токена WhatsApp: {e}")


def start_token_check_loop():
    def loop():
        while True:
            check_token_validity()
            time.sleep(86400)  # раз в сутки
    threading.Thread(target=loop, daemon=True).start()

# запуск проверки токена при старте
start_token_check_loop()
def cleanup_temp_files():
    tmp_path = "/tmp"
    if os.path.exists(tmp_path):
        for fname in os.listdir(tmp_path):
            if fname.endswith(('.wav', '.mp3', '.ogg')):
                try:
                    os.remove(os.path.join(tmp_path, fname))
                    logger.info(f"🥹 Удален временный файл: {fname}")
                except Exception as e:
                    logger.warning(f"❌ Ошибка удаления файла {fname}: {e}")
    for fname in os.listdir("tmp"):
        if fname.startswith("app_start_") and fname.endswith(".log"):
            try:
                os.remove(os.path.join("tmp", fname))
            except Exception as e:
                logger.warning(f"❌ Ошибка удаления старого лога {fname}: {e}")

def start_memory_cleanup_loop():
    def loop():
        while True:
            time.sleep(600)
            gc.collect()
            process = psutil.Process()
            mem_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"🧠 Используемая память: {mem_mb:.2f} MB")
    threading.Thread(target=loop, daemon=True).start()

start_memory_cleanup_loop()
def log_memory_usage():
    process = psutil.Process()
    mem_mb = process.memory_info().rss / 1024 / 1024
    logger.info(f"Используемая память: {mem_mb:.2f} MB")

def cleanup_temp_files():
    tmp_path = "/tmp"
    if not os.path.exists(tmp_path):
        return
    for fname in os.listdir(tmp_path):
        if fname.endswith((".wav", ".mp3", ".ogg")):
            try:
                os.remove(os.path.join(tmp_path, fname))
                logger.info(f"🥹 Удален временный файл: {fname}")
            except Exception as e:
                logger.warning(f"❌ Ошибка удаления файла {fname}: {e}")

@app.route('/', methods=['GET'])
def home():
    logger.info("🏠 Запрос GET /")
    return "Сервер работает!"

@app.route("/ping")
def ping():
    logger.info("🔔 Запрос PING")
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
        logger.info("🔁 Эхо-сообщение от самого себя — пропущено")
        return

    normalized_number = normalize_for_meta(from_number)
    name = contacts[0].get("profile", {}).get("name") if contacts else "друг"

    if message.get("type") == "text":
        text = message.get("text", {}).get("body", "").strip()
        process_text_message(text, normalized_number, phone_number_id, name)

    elif message.get("type") == "audio":
        logger.info("🎤 Аудио передаётся на фон для обработки")
        threading.Thread(target=handle_audio_async, args=(message, phone_number_id, normalized_number, name), daemon=True).start()

def handle_audio_async(message, phone_number_id, normalized_number, name):
    try:
        audio_id = message["audio"]["id"]
        logger.info(f"🎿 Обработка голосового файла, media ID: {audio_id}")

        url = f"https://graph.facebook.com/v15.0/{audio_id}"
        headers = {"Authorization": f"Bearer {get_token()}"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        media_url = resp.json().get("url")

        media_resp = requests.get(media_url, headers=headers, timeout=30)
        media_resp.raise_for_status()
        audio_path = "/tmp/audio.ogg"
        with open(audio_path, "wb") as f:
            f.write(media_resp.content)

        audio = AudioSegment.from_file(audio_path)
        duration_sec = len(audio) / 1000
        logger.info(f"⏱️ Длительность аудио: {duration_sec:.1f} секунд")

        if duration_sec > 60:
            logger.warning("⚠️ Аудио превышает 60 секунд")
            send_text_message(phone_number_id, normalized_number,
                              "Пожалуйста, пришлите голосовое сообщение не длиннее 1 минуты.")
            return

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
        logger.info(f"📝 Распознано: {transcript}")
        text = transcript.strip()

        if text:
            process_text_message(text, normalized_number, phone_number_id, name)

    except Exception as e:
        logger.error(f"❌ Ошибка фоновой обработки аудио: {e}")

def process_text_message(text, normalized_number, phone_number_id, name):
    if not text:
        return

    logger.info(f"📬 Сообщение от {normalized_number}: {text}")

    if text.lower() in SKIP_AI_PHRASES:
        return

    if len(text) > 500:
        text = text[:500]

    try:
        response = get_ai_response(text)
        send_text_message(phone_number_id, normalized_number, response)
        return

    except AuthenticationError as e:
        logger.error(f"🔐 Ошибка авторизации OpenAI: {e}")

    except RateLimitError:
        logger.warning("⚠️ Превышен лимит OpenAI")
        send_text_message(phone_number_id, normalized_number, "Сервер перегружен. Попробуйте позже.")
        return

    except (APIError, Timeout) as e:
        logger.error(f"⛔️ Сетевая ошибка OpenAI: {e}")
        send_text_message(phone_number_id, normalized_number, "Техническая ошибка. Повторите позже.")
        return

    except Exception as e:
        logger.error(f"🤖 Неизвестная ошибка OpenAI: {e}")

    category = extract_category(text)
    if name and category:
        sent = send_template_message(phone_number_id, normalized_number, "test_template_1", [name, category])
        if sent:
            return

    send_text_message(phone_number_id, normalized_number, "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!")

def get_ai_response(prompt):
    try:
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
        logger.info(f"🕒 Время генерации OpenAI: {end - start:.2f} сек")
        logger.info(f"📈 Использовано токенов: {response.usage.total_tokens}")
        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.exception(f"❌ Ошибка при обращении к OpenAI: {e}")
        return "Извините, сейчас не могу ответить. Попробуйте чуть позже."

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
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    resp_text = response.text[:500] + "..." if len(response.text) > 500 else response.text
    logger.info(f"➡️ WhatsApp {to}, статус: {response.status_code}, ответ: {resp_text}")

def send_template_message(phone_number_id, to, template_name, variables):
    url = API_URL.format(phone_number_id=phone_number_id)
    headers = {
        "Authorization": f"Bearer {get_token()}",
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
    logger.info(f"➡️ Отправка шаблона на {to}")
    logger.info("API WhatsApp ответ: %s %s", response.status_code, response.text)
    return response.status_code == 200

def handle_status(status):
    logger.info("📥 Статус: %s", status)

if __name__ == '__main__':
    logging.debug("🚀 Запуск Flask-приложения через __main__")
    try:
        logger.info("📡 Старт сервера Flask...")
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        logging.exception("💥 Ошибка при запуске Flask-приложения")

import gevent.monkey
gevent.monkey.patch_all(subprocess=True, ssl=True)
# ----- ENV sanity check --------------------------------------------------
from utils.env_check import check_env
check_env()                       # только логируем, не падаем
# ------------------------------------------------------------------------
import os
import gc
import psutil
import time
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string, abort
from logger import logger
from rollover_scheduler import start_rollover_scheduler
start_rollover_scheduler()
import requests
from openai import OpenAI
from pydub import AudioSegment
from utils.supabase_token import load_token_from_supabase, save_token_to_supabase, ping_supabase
from utils.upload_materials_to_meta_and_update_registry import \
        upload_materials_to_meta_and_update_registry
import json, tempfile, textwrap
from router import route_message
from state.state import save_if_absent      # понадобится, чтобы один раз сохранить номер

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE_NAME = "tokens"

# ======= ЛОКАЛЬНЫЙ ЛОГГЕР ДЛЯ ПЕРВОГО ЭТАПА ЗАПУСКА ========
os.makedirs("tmp", exist_ok=True)
logger.info("🟢 app.py импортирован")

# ─── Глушим «болтливые» библиотеки ──────────────────────────────────────────────
NOISY_LOGGERS = ("botocore", "boto3", "urllib3", "s3transfer", "apscheduler")
for _name in NOISY_LOGGERS:
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.WARNING)   # или ERROR, если совсем тишина нужна
    _lg.propagate = False

# Дополнительно для boto3 можно:
try:
    import boto3
    boto3.set_stream_logger("", logging.WARNING)
except Exception:
    pass

app = Flask(__name__)

# Один путь логгирования в консоль — через gunicorn.error.
# Поэтому flask-логгер настраиваем так:
flask_log = app.logger
flask_log.setLevel(logging.INFO)
flask_log.handlers.clear()      # убираем дефолтный StreamHandler Flask
flask_log.propagate = True      # отправляем записи в root (файл)

API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")
META_APP_ID = os.getenv("META_APP_ID")
META_APP_SECRET = os.getenv("META_APP_SECRET")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def _write_gcp_key():
    raw_json = os.getenv("GCP_VISION_KEY_JSON")
    if not raw_json:
        raise RuntimeError("GCP_VISION_KEY_JSON env var is missing")

    # создаём временный файл
    tmpdir = tempfile.gettempdir()
    key_path = os.path.join(tmpdir, "gcp-key.json")

    # если Render сохранил как one‑line, попробуем красиво отформатировать
    try:
        parsed = json.loads(raw_json)
        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        # ключ уже многострочный — пишем как есть
        pretty = textwrap.dedent(raw_json)

    with open(key_path, "w", encoding="utf-8") as f:
        f.write(pretty)

    # важное — сообщить Vision SDK, где лежит ключ
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = key_path
    logger.info(f"GCP credentials written to {key_path}")

_write_gcp_key()

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

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
try:
    WHATSAPP_TOKEN = load_token_from_supabase()
    logger.info(f"🔍 Загружен токен из Supabase: начинается на {WHATSAPP_TOKEN[:8]}..., длина: {len(WHATSAPP_TOKEN)}")
except Exception as e:
    logger.error(f"❌ Не удалось получить токен из Supabase: {e}")
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
    if WHATSAPP_TOKEN:
        logger.warning("⚠️ Используем токен из ENV (fallback).")
    else:
        logger.critical("💥 Нет токена WhatsApp. Бот не сможет отвечать.")

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
    check_token_validity()
    message = "✅ Токен успешно сохранён!"
    return render_template_string(form_template, message=message)

def get_token():
    return WHATSAPP_TOKEN

def check_token_validity():
    token = get_token()
    logger.info(f"🔍 Проверка токена: начинается на {token[:8]}..., длина: {len(token)}")
    test_url = f"https://graph.facebook.com/v15.0/me?access_token={token}"
    try:
        resp = requests.get(test_url, timeout=10)
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
            time.sleep(14400)  # раз в 4 часа
    threading.Thread(target=loop, daemon=True).start()

def start_media_upload_loop():
    from utils.upload_materials_to_meta_and_update_registry import \
            upload_materials_to_meta_and_update_registry

    def loop():
        while True:
            token = get_token()                      # всегда самый новый
            try:
                logger.info("⏫ Ежедневная загрузка материалов…")
                upload_materials_to_meta_and_update_registry(token)
            except Exception as e:
                logger.error(f"💥 Ошибка загрузки материалов: {e}")
            time.sleep(86400)
    threading.Thread(target=loop, daemon=True).start()
    
# запуск проверки токена при старте
start_token_check_loop()
start_media_upload_loop()
def start_supabase_ping_loop(interval_hours: int = 12):
    def loop():
        while True:
            try:
                ping_supabase()
            except Exception as e:
                logger.warning(f"⚠️ Supabase ping error: {e}")
            time.sleep(interval_hours * 3600)
    threading.Thread(target=loop, daemon=True).start()

start_supabase_ping_loop()

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
    guni = logging.getLogger("gunicorn.error")
    def loop():
        while True:
            time.sleep(600)
            gc.collect()
            mb = psutil.Process().memory_info().rss / 1024 / 1024
            msg = f"🧠 Использованная память {mb:.2f} MB"
            # Пишем ТОЛЬКО в один логгер (gunicorn.error) — попадёт в консоль Render.
            # В файл запись придёт через propagate root? Нет. Поэтому дублируем в root вручную.
            logging.getLogger().info(msg)   # в файл
            guni.info(msg)                  # в консоль
    threading.Thread(target=loop, daemon=True).start()
start_memory_cleanup_loop()
def log_memory_usage():
    process = psutil.Process()
    mem_mb = process.memory_info().rss / 1024 / 1024
    logger.info(f"Используемая память: {mem_mb:.2f} MB")

@app.route('/', methods=['GET'])
def home():
    logger.info("🏠 Запрос GET /")
    return "Сервер работает!"

@app.route("/debug/upload-log")
def manual_log_upload():
    from logger import upload_to_s3_manual
    upload_to_s3_manual()
    return "Загрузка выполнена (если файл был)", 200

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
        # ➊ Сырой payload, чтобы увидеть реальный user_id и убедиться,
        #    что он совпадает с ADMIN_NUMBERS
        logger.info("📩 webhook raw json: %s", request.get_json())

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

@app.route("/debug/mem")
def debug_mem():
    import psutil, gc
    gc.collect()
    mb = psutil.Process().memory_info().rss / 1024 / 1024
    msg = f"🧠 (manual) {mb:.2f} MB"
    logging.getLogger().info(msg)           # файл
    logging.getLogger("gunicorn.error").info(msg)  # консоль
    return f"{mb:.2f} MB", 200

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
        threading.Thread(
            target=handle_audio_async,
            args=(message, phone_number_id, normalized_number, name),
            daemon=True
        ).start()
    elif message.get("type") in ("image", "document"):
        logger.info("🖼 Получено media‑сообщение (%s)", message["type"])
        threading.Thread(
            target=handle_media_async,
            args=(message, phone_number_id, normalized_number),
            daemon=True
        ).start()

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

def handle_media_async(message, phone_number_id, user_id):
    """
    Универсальная обработка входящего media (image/document):
      1. Получаем временный URL.
      2. Классификация:
         - Явные маркеры оплаты -> пробуем как чек.
         - Явные маркеры именинника -> фото именинника.
         - Пустая / нейтральная подпись -> сначала пытаемся валидировать как чек;
           если невалидно/ошибка -> фото (если нет) иначе fallback как потенциальный чек.
      3. Переходим в block7 (пусть там едет общая логика вопросов / повторных касаний).
    """
    from state.state import get_state, update_state
    from utils.check_payment_validity import validate_payment
    import tempfile, os

    media_type  = message["type"]
    media_obj   = message[media_type]
    media_id    = media_obj.get("id")
    caption     = media_obj.get("caption") or ""
    caption_low = caption.lower().strip()

    headers = {"Authorization": f"Bearer {get_token()}"}

    # --- 1. Получаем file_url ---
    try:
        meta_url  = f"https://graph.facebook.com/v17.0/{media_id}"
        meta_resp = requests.get(meta_url, headers=headers, timeout=10)
        meta_resp.raise_for_status()
        file_url = meta_resp.json()["url"]
    except Exception as e:
        logger.error(f"[media] cannot obtain URL for media {media_id}: {e}")
        return

    st = get_state(user_id) or {}

    payment_markers = ("чек", "kaspi", "оплат", "перевод", "transaction", "payment", "банк", "bank")
    celebrant_markers = ("именин", "ребен", "ребён", "сын", "доч", "дочь",
                         "мальчик", "девоч", "child", "birthday", "фото")

    def has_payment_markers(c: str) -> bool:
        return any(w in c for w in payment_markers)

    def has_celebrant_markers(c: str) -> bool:
        if has_payment_markers(c):
            return False
        return any(w in c for w in celebrant_markers)

    # ----- локальные хелперы (ОБЪЯВЛЕНЫ ДО ИСПОЛЬЗОВАНИЯ) -----
    def _store_raw_payment_stub():
        update_state(user_id, {
            "payment_proof_url": file_url,
            "payment_media_id": media_id,
            "last_message_ts": time.time()
        })
        logger.info(f"[media] stored potential payment (stub) user={user_id}")

    def _store_celebrant_photo():
        update_state(user_id, {
            "celebrant_photo_id": media_id,
            "celebrant_photo_url": file_url,
            "has_photo": True,
            "last_message_ts": time.time()
        })
        logger.info(f"[media] stored celebrant photo user={user_id}")

    stored = False

    # --- Ветка 1: явные маркеры оплаты ---
    if (not stored) and (not st.get("payment_proof_url")) and has_payment_markers(caption_low):
        _store_raw_payment_stub()
        stored = True

    # --- Ветка 2: явные маркеры именинника ---
    if (not stored) and (not st.get("celebrant_photo_id")) and has_celebrant_markers(caption_low):
        _store_celebrant_photo()
        stored = True

    # --- Ветка 3: неоднозначно / пусто ---
    if not stored:
        empty_or_neutral = (
            caption_low == "" or
            (not has_payment_markers(caption_low) and not has_celebrant_markers(caption_low))
        )

        if empty_or_neutral:
            if not st.get("payment_proof_url"):
                # сначала пробуем валидировать как чек
                try:
                    r = requests.get(file_url, timeout=20)
                    r.raise_for_status()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(r.content)
                        tmp_path = tmp.name
                    result = validate_payment(tmp_path, min_amount=30000)
                    os.remove(tmp_path)

                    if result.get("valid"):
                        update_state(user_id, {
                            "payment_proof_url": file_url,
                            "payment_media_id": media_id,
                            "payment_valid": True,
                            "payment_issues": result.get("issues", []),
                            "last_message_ts": time.time()
                        })
                        logger.info(f"[media] ambiguous -> validated as payment user={user_id}")
                        stored = True
                    else:
                        # невалидно: используем как фото (если нет)
                        if not st.get("celebrant_photo_id"):
                            _store_celebrant_photo()
                            stored = True
                        else:
                            _store_raw_payment_stub()
                            stored = True
                except Exception as e:
                    logger.error(f"[media] ambiguous validation error user={user_id}: {e}")
                    # не удалось проверить — сохраняем как потенциальный чек
                    if not st.get("payment_proof_url"):
                        _store_raw_payment_stub()
                        stored = True
            else:
                # чек уже есть, можно принять как фото
                if not st.get("celebrant_photo_id"):
                    _store_celebrant_photo()
                    stored = True

    # --- Fallback ---
    if not stored:
        _store_raw_payment_stub()

    # --- Переход в block7 ---
    from router import route_message
    route_message("", user_id, force_stage="block7")

def process_text_message(text: str,
                         normalized_number: str,
                         phone_number_id: str,
                         name: str | None):
    """
    Теперь просто отдаём текст в движок сценария.
    """
    if not text:
        return

    # 1) гарантируем, что в state уже лежит нормализованный номер
    save_if_absent(normalized_number,
                   normalized_number=normalized_number,
                   raw_number=normalized_number,   # можно поправить под себя
                   client_name=name or "")

    # 2) пускаем сообщение в роутер
    try:
        route_message(text, normalized_number, client_name=name)
    except Exception as e:
        logger.exception(f"💥 Ошибка route_message для {normalized_number}: {e}")
        # last‑chance fallback, чтобы клиент не остался без ответа
        send_text_message(phone_number_id, normalized_number,
                          "Техническая ошибка. Попробуйте позже.")

def normalize_for_meta(number):
    if number.startswith('77'):
        return '787' + number[2:]
    if number.startswith('79'):
        return '789' + number[2:]
    return number

def send_text_message(phone_number_id, to, text):
    url = API_URL.format(phone_number_id=phone_number_id)
    headers = {"Authorization": f"Bearer {get_token()}", 
               "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    resp_text = response.text[:500] + "..." if len(response.text) > 500 else response.text
    logger.info(f"➡️ WhatsApp {to}, статус: {response.status_code}, ответ: {resp_text}")


def handle_status(status):
    logger.info("📥 Статус: %s", status)

if __name__ == '__main__':
    logger.debug("🚀 Запуск Flask-приложения через __main__")
    try:
        logger.info("📡 Старт сервера Flask...")
        app.run(host='0.0.0.0', port=5000)
    except Exception as e:
        logger.exception("💥 Ошибка при запуске Flask-приложения")

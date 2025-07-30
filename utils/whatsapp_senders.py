import os, requests, logging
from importlib import import_module
log = logging.getLogger(__name__)

PHONE_ID = os.getenv("PHONE_NUMBER_ID")
API_URL  = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"

def _headers():
    # импорт внутри функции, чтобы избежать циклической зависимости
    app = import_module("app")          # app.get_token() кэширует актуальный токен
    return {
        "Authorization": f"Bearer {app.get_token()}",
        "Content-Type":  "application/json",
    }

def send_text(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    _post(payload, "text")
    url = API_URL.format(phone_number_id=PHONE_NUMBER_ID)
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    logger.info("➡️ WhatsApp %s, статус: %s, ответ: %s",
                to, resp.status_code, resp.text[:400])
    return resp        # полезно вернуть, если понадобится проверять

def send_image(to: str, media_id: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"id": media_id}
    }
    _post(payload, "image")

def send_document(to: str, media_id: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {"id": media_id}
    }
    _post(payload, "document")

def send_video(to: str, media_id: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": {"id": media_id}
    }
    _post(payload, "video")

def _post(payload, tag):
    try:
        resp = requests.post(API_URL, json=payload, headers=_headers(), timeout=30)
        resp.raise_for_status()
        log.info(f"➡️ WA {tag} ok → {payload['to']}")
    except requests.RequestException as e:
        log.error(f"❌ WA {tag} to {payload['to']}: {e} • payload={payload}")


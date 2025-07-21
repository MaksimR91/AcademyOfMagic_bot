import os, requests, logging
from utils.supabase_token import load_token_from_supabase
log = logging.getLogger(__name__)

PHONE_ID = os.getenv("PHONE_NUMBER_ID")
API_URL  = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"

def _headers():
    return {
        "Authorization": f"Bearer {load_token_from_supabase()}",
        "Content-Type":  "application/json"
    }

def send_text(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body}
    }
    _post(payload, "text")

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


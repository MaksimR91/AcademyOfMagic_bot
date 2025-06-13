from flask import Flask, request, jsonify
from logger import logger
import requests

app = Flask(__name__)

ACCESS_TOKEN = "EAAIdbZCyeyLoBO4mL6jbKTPp3RsCZA18zLpgxZBEJTDuQlfR2LdK1fInh9iG0Q607Aopi6iRJ2N7gTaSo51Tt2pp1aJLJWLZA5LHGgXZAnwf2sCJ1orvBiHNCIF9e0GQLrlFI7KPS7wjkZAPhpLsiRMj9wN9lT2sbahqP40BshGVIj2cH2xHcKOZA6xXOcrNZBHtr7d6pMMHqShRIGi8ydYiNz0ELMWOBRgZD"
VERIFY_TOKEN = "magicBotWebhook2025_9Jr4cT"
API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"

@app.route('/', methods=['GET'])
def home():
    return "Сервер работает!"

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
                    messages = value.get('messages', [])
                    if messages:
                        phone_number_id = value['metadata']['phone_number_id']
                        for message in messages:
                            from_number = message['from']
                            normalized_number = normalize_for_meta(from_number)

                            send_text_message(
                                phone_number_id,
                                normalized_number,
                                "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!"
                            )

        return jsonify({"status": "success"}), 200

def normalize_for_meta(number):
    if number.startswith('770'):
        return '78' + number[2:]
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
        "text": {
            "body": text
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"➡️ Отправка на {to}")
    logger.info("Ответ API WhatsApp: %s %s", response.status_code, response.text)

from logger import logger, S3TimedRotatingFileHandler

# Временный тест ротации и загрузки в Яндекс
logger.info("🔁 Пробуем doRollover через app.py (временно)")
for handler in logger.handlers:
    if isinstance(handler, S3TimedRotatingFileHandler):
        handler.doRollover()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
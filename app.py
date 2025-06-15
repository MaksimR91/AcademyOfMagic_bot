from flask import Flask, request, jsonify
from logger import logger
import requests

app = Flask(__name__)

ACCESS_TOKEN = "EAAIdbZCyeyLoBOxxy2S2mlFpAiS9Vrl64FCu9MSwbQN7yWRneFY8k8ZAUyBuxaezT5ORSLnY6mkhF0OzrakdkZA7aGNiaZCMWbdMoIvn15Mz2cuAYZAtTK393hwMhpWQvPy6Bm1Y01LJmEWifni4tIIamM2rWmUzvGc4r4nGKeaHj2mYNjWPpRuAXzG6C6gGKOG4JYBzWMZAgjcSQF7cQePxGyKmjx68TKQq9dxJ2fYWfAuZCtHuPAZD"
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

                    # Входящие сообщения
                    for message in value.get('messages', []):
                        handle_message(
                            message,
                            value['metadata']['phone_number_id'],
                            value['metadata']['display_phone_number']
                        )

                    # Статусы (доставлено, прочитано и т.п.)
                    for status in value.get('statuses', []):
                        handle_status(status)

        return jsonify({"status": "success"}), 200

def handle_message(message, phone_number_id, bot_display_number):
    from_number = message.get("from")

    # ⛔️ Эхо-фильтр — сообщение от самого бота
    if from_number.endswith(bot_display_number[-9:]):
        logger.info("🔁 Эхо-сообщение от самого себя — пропущено")
        return

    # ⚠️ Фильтр пустых сообщений (например, статус или стикер)
    text = message.get("text", {}).get("body")
    if not text:
        logger.info("📎 Сообщение без текста — пропущено")
        return

    normalized_number = normalize_for_meta(from_number)
    logger.info(f"📩 Новое сообщение от {normalized_number}: {text}")

    # 🔠 Извлекаем имя
    name = message.get("profile", {}).get("name", "друг")

    # 🎯 Ищем ключевые слова
    if "детск" in text.lower():
        show_type = "детское"
    elif "взросл" in text.lower():
        show_type = "взрослое"
    elif "семейн" in text.lower():
        show_type = "семейное"
    else:
        show_type = "наше"

    # 📬 Отправляем шаблон
    send_template_message(
        phone_number_id,
        normalized_number,
        "test_template_1",
        [name, show_type]
    )

    # ✉️ И обычное сообщение (на будущее)
    send_text_message(
        phone_number_id,
        normalized_number,
        f"Привет, {name}! Мы получили твой запрос. Интересует {show_type} шоу, верно?"
    )

def handle_status(status):
    logger.info("📥 Получен статус: %s", status)

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
    logger.info(f"➡️ Отправка текста на {to}")
    logger.info("Ответ API WhatsApp: %s %s", response.status_code, response.text)

def send_template_message(phone_number_id, to, template_name, parameters):
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
                    "parameters": [
                        {"type": "text", "text": param} for param in parameters
                    ]
                }
            ]
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"➡️ Отправка шаблона на {to}")
    logger.info("Ответ API WhatsApp: %s %s", response.status_code, response.text)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

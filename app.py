from flask import Flask, request, jsonify
from logger import logger
import requests
import os
from openai import OpenAI, OpenAIError

app = Flask(__name__)

# Конфигурация
ACCESS_TOKEN = "EAAIdbZCyeyLoBOxbGz6yhlvCxciZBAo0iTpR6ZAtSE9sQUybecx0M606FZAtq8ZB9oPmU7NEz8beJCDLj6obZBjA3SXUcJ2WdZBousBelgSdf5PPQ2NGs1KzzNjiijbwrBBLaAhfAu2U8eUf2WzCjslZC8wkXZA68YGnDAIv7UwVMWCU8EZBTniyYjl2zZBWP4i0CyfUrPdPZCeDiZCZAmbZBY4BgqODah2C3x53oMDSCJC3tBAF7OGfZAbiZCnYZD"
API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")

client = OpenAI(api_key=openai_api_key)

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

    text = message.get("text", {}).get("body")
    if not text:
        logger.info("📎 Сообщение без текста — пропущено")
        return

    name = contacts[0].get("profile", {}).get("name") if contacts else "друг"
    category = extract_category(text)
    normalized_number = normalize_for_meta(from_number)

    logger.info(f"📩 Новое сообщение от {normalized_number}: {text}")

    # Пытаемся получить ответ от ИИ
    try:
        response = get_ai_response(text)
        send_text_message(phone_number_id, normalized_number, response)
        return
    except Exception as e:
        logger.warning(f"🤖 Ошибка генерации ответа ИИ: {e}")

    # Пробуем отправить шаблон
    if name and category:
        sent = send_template_message(
            phone_number_id,
            normalized_number,
            "test_template_1",
            [name, category]
        )
        if sent:
            return

    # Если всё сломалось — fallback
    send_text_message(
        phone_number_id,
        normalized_number,
        "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!"
    )

def get_ai_response(prompt):
    chat_completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Ты ассистент иллюзиониста Арсения. Отвечай осмысленно, дружелюбно и кратко."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=300
    )
    return chat_completion.choices[0].message.content.strip()

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
        "text": {
            "body": text
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"➡️ Отправка текста на {to}")
    logger.info("Ответ API WhatsApp: %s %s", response.status_code, response.text)

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
            "language": {
                "code": "ru"
            },
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
    logger.info("Ответ API WhatsApp: %s %s", response.status_code, response.text)

    return response.status_code == 200

def handle_status(status):
    logger.info("📥 Получен статус: %s", status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
from flask import Flask, request, jsonify
from logger import logger
import requests
import os
from openai import OpenAI, RateLimitError, APIError, Timeout, AuthenticationError  # ⬅️ добавлен AuthenticationError

app = Flask(__name__)

ACCESS_TOKEN = "EAAIdbZCyeyLoBOzWYoEwiqYtC184ujYfMPQrHo9lp1YKiO4SO5PZB9oPengNIZA0BqLkxhR87bHJqnDgAo9WmdcrQ7M7h4fGZApChpYKItpHSNfW0cPnzuP6ifIyH3e66QvWADnMfZBik9uc40DkxwMeBJCHety9RYnA8KZAPVrBiqPZBjZCtBdKRDbOY4jzem6zeAZCxcTF1pZAhXgY72PvMkyGAwZCvBW3d5VtMNNEaD4zxFvlDMpGNoZD"
API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")

client = OpenAI(api_key=openai_api_key)
logger.info(f"🔐 OpenAI API key начинается на: {openai_api_key[:5]}..., длина: {len(openai_api_key)}")

SKIP_AI_PHRASES = ["ок", "спасибо", "понятно", "ясно", "пока", "привет", "здрасте", "да", "нет"]

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
        logger.info("🔁 Эхо-сообщение от самого себя — пропущено")
        return

    text = message.get("text", {}).get("body", "").strip()
    if not text:
        logger.info("📎 Сообщение без текста — пропущено")
        return

    name = contacts[0].get("profile", {}).get("name") if contacts else "друг"
    category = extract_category(text)
    normalized_number = normalize_for_meta(from_number)

    logger.info(f"📬 Новое сообщение от {normalized_number}: {text}")

    if text.lower() in SKIP_AI_PHRASES:
        logger.info("📅 Сообщение в списке фильтрации, OpenAI не вызывается")
        return

    if len(text) > 500:
        text = text[:500]

    try:
        # 💬 Попытка получить ответ от OpenAI
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

    # Продолжаем по алгоритму после ошибки
    if name and category:
        sent = send_template_message(phone_number_id, normalized_number, "test_template_1", [name, category])
        if sent:
            return

    send_text_message(phone_number_id, normalized_number, "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!")

def get_ai_response(prompt):
    response = client.chat.completions.create(
        model="gpt-3.5-turbo-0125",
        messages=[
            {"role": "system", "content": "Ты ассистент иллюзиониста Арсения. Отвечай осмысленно, дружелюбно и кратко."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=150
    )
    logger.info(f"📈 Использовано токенов: {response.usage.total_tokens}")
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
        "text": {
            "body": text
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    logger.info(f"➡️ Отправка текста на {to}")
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
    logger.info(f"➡️ Отправка шаблона на {to}")
    logger.info("API WhatsApp ответ: %s %s", response.status_code, response.text)
    return response.status_code == 200

def handle_status(status):
    logger.info("📥 Статус: %s", status)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)



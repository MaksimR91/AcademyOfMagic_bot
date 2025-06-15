from flask import Flask, request, jsonify
from logger import logger
import requests
import os
from openai import OpenAI, RateLimitError, APIError, Timeout  # подключаем нужные ошибки

app = Flask(__name__)

# Конфигурация
ACCESS_TOKEN = "EAAIdbZCyeyLoBOxbGz6yhlvCxciZBAo0iTpR6ZAtSE9sQUybecx0M606FZAtq8ZB9oPmU7NEz8beJCDLj6obZBjA3SXUcJ2WdZBousBelgSdf5PPQ2NGs1KzzNjiijbwrBBLaAhfAu2U8eUf2WzCjslZC8wkXZA68YGnDAIv7UwVMWCU8EZBTniyYjl2zZBWP4i0CyfUrPdPZCeDiZCZAmbZBY4BgqODah2C3x53oMDSCJC3tBAF7OGfZAbiZCnYZD"  # ⚠️ замени на актуальный
API_URL = "https://graph.facebook.com/v15.0/{phone_number_id}/messages"
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
openai_api_key = os.getenv("OPENAI_APIKEY")

# Инициализация клиента OpenAI
client = OpenAI(api_key=openai_api_key)
logger.info(f"🔐 OpenAI API key начинается на: {openai_api_key[:5]}..., длина: {len(openai_api_key)}")


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
                    value = change.get('value', {}



from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

ACCESS_TOKEN = "EAAIdbZCyeyLoBOZCH7opFR4kX10PwkYeKnacye3diREsZBp7LZBkBIqR0neuJDpwfFftXtwYmktdwlw4bNLjkiXpRYOgDkZAPgZBivqzMIDwZC3tOeZBu71gdcgBnijHBhye07cRKZCQPxQKNNBYWTppCvMVZChYC0zHmSm0yx8Q71iZBuwrxMHykPi8PBb2JwsGkSfOjYhEIm5gxSsrMvpF1bD7INkG5w6xvEZD"
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
            print("WEBHOOK VERIFIED")
            return challenge, 200
        else:
            return "Verification failed", 403

    elif request.method == 'POST':
        data = request.json
        print("Получено сообщение:", data)

        if data.get('object') == 'whatsapp_business_account':
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    if messages:
                        phone_number_id = value['metadata']['phone_number_id']
                        for message in messages:
                            from_number = message['from']

                            # Фикс восьмёрки для Meta-тестового ада
                            if from_number.startswith('770'):
                                from_number = '78' + from_number[2:]

                            # Отправляем ответ
                            send_text_message(phone_number_id, from_number, "Привет, долбоеб мой друг! Что хотел, долбоеб мой друг!")

        return jsonify({"status": "success"}), 200

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
    print("Ответ API WhatsApp:", response.status_code, response.text)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
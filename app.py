from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "Сервер работает!"

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        verify_token = 'magicBotWebhook2025_9Jr4cT'
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and token == verify_token:
            print("WEBHOOK VERIFIED")
            return challenge, 200
        else:
            return "Verification failed", 403

    elif request.method == 'POST':
        data = request.json
        print("Получено сообщение:", data)
        return jsonify({"status": "success", "received": data}), 200
from utils.ask_openai import ask_openai
def load_global_prompt():
    with open("prompts/global_prompt.txt", encoding="utf-8") as f:
        return f.read()
def wants_handover_ai(user_message):
    global_prompt = load_global_prompt()
    
    classification_prompt = global_prompt + f"""

Вот сообщение клиента: "{user_message}"

Нужно определить, относится ли сообщение к одному из следующих случаев:

- Клиент хочет поговорить с Арсением напрямую (например, просит связаться, передать ему сообщение, пишет что хочет обсудить лично и т.п.);
- Клиент обсуждает изменение стоимости, условий оплаты или запрашивает скидку (например, предлагает другую сумму, спрашивает можно ли оплатить частично, интересуется снижением стоимости, говорит что дорого и т.п.).

Если хотя бы один из пунктов применим — ответьте "да".  
Если нет — ответьте "нет".

Ответьте строго "да" или "нет", без пояснений.
"""
    response = ask_openai(classification_prompt).strip().lower()
    return response.startswith("да")
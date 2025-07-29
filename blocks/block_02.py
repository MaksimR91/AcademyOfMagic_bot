import time
from utils.ask_openai import ask_openai
from utils.wants_handover_ai import wants_handover_ai
from state.state import get_state, update_state
from utils.reminder_engine import plan

# Пути к промптам
GLOBAL_PROMPT_PATH = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH = "prompts/block02_prompt.txt"
REMINDER_PROMPT_PATH = "prompts/block02_reminder_1_prompt.txt"
REMINDER_2_PROMPT_PATH = "prompts/block02_reminder_2_prompt.txt"
# Время до повторного касания (4 часа)
DELAY_TO_BLOCK_2_1_HOURS = 4
DELAY_TO_BLOCK_2_2_HOURS = 12
FINAL_TIMEOUT_HOURS = 4

def load_prompt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def proceed_to_block(stage_name, user_id):
    from router import route_message
    route_message("", user_id, force_stage=stage_name)

def handle_block2(message_text, user_id, send_reply_func):
    if wants_handover_ai(message_text):
        # Клиент просит живого человека на этапе 2
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block2"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    # Склейка промптов
    global_prompt = load_prompt(GLOBAL_PROMPT_PATH)
    stage_prompt = load_prompt(STAGE_PROMPT_PATH)
    full_prompt = global_prompt + "\n\n" + stage_prompt + f'\n\nСообщение клиента: "{message_text}"'

    # Ответ ассистента клиенту
    reply_to_client = ask_openai(full_prompt)
    send_reply_func(reply_to_client)

    update_state(
        user_id,
        {
            "stage": "block2",
            "last_message_ts": time.time(),
            "event_description": message_text.strip(),   # <-- новая строка
        },
    )
    # Классификация типа шоу (второй промпт)
    classification_prompt = global_prompt + f"""

Клиент рассказал следующее о мероприятии: "{message_text}"

Определите тип шоу строго по этим правилам:
- День рождения: 1–3 года — семейное, 4–14 лет — детское, 15+ — взрослое.
- Детский сад — детское шоу.
- Если примерно поровну детей и взрослых — семейное.
- Свадьба — взрослое.
- Всё остальное — нестандартное шоу.
Если не удаётся понять — ответьте "неизвестно".

Ответьте одной из фраз: "детское", "взрослое", "семейное", "нестандартное", "неизвестно". Никаких пояснений не давайте.
"""

    show_type = ask_openai(classification_prompt).strip().lower()

    if show_type == "детское":
        next_block = "block3a"
    elif show_type == "взрослое":
        next_block = "block3b"
    elif show_type == "семейное":
        next_block = "block3c"
    elif show_type == "нестандартное":
        next_block = "block3d"
    else:
        update_state(user_id, {"stage": "block2", "last_message_ts": time.time()})
        plan(user_id,
        "blocks.block_02:send_first_reminder_if_silent",   # <‑‑ путь к функции
        DELAY_TO_BLOCK_2_1_HOURS * 3600)
        return
    update_state(user_id, {"show_type": show_type})
    from router import route_message
    route_message("", user_id, force_stage=next_block)

def send_first_reminder_if_silent(user_id, send_reply_func):
    state = get_state(user_id)
    if not state or state.get("stage") != "block2":
        return  # Клиент уже ответил или сменился блок — ничего не делаем

    global_prompt = load_prompt(GLOBAL_PROMPT_PATH)
    reminder_prompt = load_prompt(REMINDER_PROMPT_PATH)
    full_prompt = global_prompt + "\n\n" + reminder_prompt

    reply = ask_openai(full_prompt)
    send_reply_func(reply)

    update_state(user_id, {"stage": "block2", "last_message_ts": time.time()})

    # Подготовка таймера на второе напоминание через 12 часов (в блок 2.2)
    plan(user_id,
    "blocks.block_02:send_second_reminder_if_silent",   # <‑‑ путь к функции
    DELAY_TO_BLOCK_2_2_HOURS * 3600)
    

def send_second_reminder_if_silent(user_id, send_reply_func):
    state = get_state(user_id)
    if not state or state.get("stage") != "block2":
        return  # Клиент уже ответил — ничего не делаем

    global_prompt = load_prompt(GLOBAL_PROMPT_PATH)
    reminder_prompt = load_prompt(REMINDER_2_PROMPT_PATH)
    full_prompt = global_prompt + "\n\n" + reminder_prompt

    reply = ask_openai(full_prompt)
    send_reply_func(reply)

    update_state(user_id, {"stage": "block2", "last_message_ts": time.time()})

    # Финальный таймер — если клиент не ответит ещё 4 часа, уходим в block9
    def finalize_if_still_silent():
        state = get_state(user_id)
        if not state or state.get("stage") != "block2":
            return  # Ответил — всё ок
        update_state(user_id, {"handover_reason": "no_response_after_2_2", "scenario_stage_at_handover": "block2"})
        from router import route_message
        route_message("", user_id, force_stage="block9")

    plan(user_id,
    "blocks.block_02:finalize_if_still_silent",   # <‑‑ путь к функции
    FINAL_TIMEOUT_HOURS * 3600)

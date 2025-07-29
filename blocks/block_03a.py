import time
import re
from utils.ask_openai import ask_openai
from utils.wants_handover_ai import wants_handover_ai
from utils.schedule import load_schedule_from_s3, check_date_availability
from state.state import get_state, update_state, save_if_absent
from utils.reminder_engine import plan

# Пути к промптам
GLOBAL_PROMPT_PATH = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH = "prompts/block03a_prompt.txt"
REMINDER_1_PROMPT_PATH = "prompts/block03_reminder_1_prompt.txt"
REMINDER_2_PROMPT_PATH = "prompts/block03_reminder_2_prompt.txt"

# Тайминги
DELAY_TO_BLOCK_3_1_HOURS = 4   # первое напоминание через 4 ч
DELAY_TO_BLOCK_3_2_HOURS = 12  # второе — ещё через 12 ч
FINAL_TIMEOUT_HOURS     = 4    # финал через 4 ч после второго

# Флаг, чтобы избежать повторной проверки даты и времени для пользователя
DATE_DECISION_FLAGS = {}

def load_prompt(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def handle_block3a(message_text, user_id, send_reply_func, client_request_date):
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    global_prompt = load_prompt(GLOBAL_PROMPT_PATH)
    stage_prompt = load_prompt(STAGE_PROMPT_PATH)
    # достанем сохранённое описание из блока 2 (если оно есть)
    state_data = get_state(user_id) or {}
    prev_info = state_data.get("event_description", "")
    full_prompt = (
         global_prompt
         + "\n\n"
         + stage_prompt
         + f"\n\nОбщая информация от клиента (ранее): {prev_info}"
         + f"\n\nТекущая дата: {client_request_date}."
         + f"\n\nСообщение клиента: \"{message_text}\""
     )

    reply = ask_openai(full_prompt)
    send_reply_func(reply)

    # ===== Проверка даты и времени при каждом сообщении =====
    if user_id not in DATE_DECISION_FLAGS or not DATE_DECISION_FLAGS[user_id]:
        match_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", message_text)
        match_time = re.search(r"\b(\d{1,2}:\d{2})\b", message_text)

        pl_text = message_text.lower()
        place_type   = None
        if any(w in pl_text for w in ("дом", "квартира", "house", "home")):
             place_type = "home"
        elif "сад" in pl_text:            # детский сад / садовый участок
             place_type = "garden"
        elif any(w in pl_text for w in ("кафе", "ресторан", "cafe", "restaurant")):
            place_type = "cafe"
            # ── сохраняем всё, что смогли вытащить ───────────────────────────
        extracted = {}
        if place_type:
            extracted["place_type"] = place_type
        if match_date:
            extracted["event_date"] = match_date.group(1)
        if match_time:
            extracted["event_time"] = match_time.group(1)

        # возможное количество гостей
        m_guests = re.search(r"\b(\d{1,3})\s+(?:гостей|человек)\b", pl_text)
        if m_guests:
            extracted["guests_count"] = m_guests.group(1)

        # пишем только если поля ещё пусты
        if extracted:
            save_if_absent(user_id, **extracted)
        if match_date and match_time:
            date_str = match_date.group(1)
            time_str = match_time.group(1)
            schedule = load_schedule_from_s3()
            availability = check_date_availability(date_str, time_str, schedule)
            availability_prompt = (
            global_prompt
            + f"""
            Клиент ранее написал: "{message_text}"
            Дата мероприятия: {date_str}
            Время мероприятия: {time_str}
            Текущая дата: {client_request_date}

            СТАТУС:{availability}

            Напиши клиенту:
            если СТАТУС:available — фразу "дата и время свободны – Арсений сможет выступить".
            если СТАТУС:need_handover или occupied — вежливо сообщи, что "Арсений свяжется с вами по поводу даты и времени выступления позднее".
            """
            )

            availability_reply = ask_openai(availability_prompt)
            send_reply_func(availability_reply)

    # Проставим флаг на основе статуса
            if availability == "available":
                DATE_DECISION_FLAGS[user_id] = "available"
            elif availability in ("need_handover", "occupied"):
                DATE_DECISION_FLAGS[user_id] = "handover"
                update_state(user_id, {"handover_reason": "early_date_or_busy", "scenario_stage_at_handover": "block3"})
                from router import route_message
                return route_message("", user_id, force_stage="block9")

# ===== Переходы в другие блоки =====
    lower_reply = reply.lower()

    # 2. если собрана вся инфо
    if "вся информация собрана" in lower_reply:
        if DATE_DECISION_FLAGS.get(user_id) == "available":
            from router import route_message
            return route_message("", user_id, force_stage="block4")
        elif DATE_DECISION_FLAGS.get(user_id) == "handover":
            update_state(user_id, {"handover_reason": "early_date_or_busy", "scenario_stage_at_handover": "block3"})
            from router import route_message
            return route_message("", user_id, force_stage="block9")

    # 3. явный запрос хенд-овера (ИИ)
    if "время занято" in lower_reply or "передайте арсению" in lower_reply:
         update_state(user_id, {"handover_reason": "early_date_or_busy", "scenario_stage_at_handover": "block3"})
         from router import route_message
         return route_message("", user_id, force_stage="block9")

    # ===== Продолжаем диалог =====
    update_state(user_id, {"stage": "block3a", "last_message_ts": time.time(), "last_bot_question": reply})
    plan(user_id,
    "blocks.block_03a:send_first_reminder_if_silent",   # <‑‑ путь к функции
    DELAY_TO_BLOCK_3_1_HOURS * 3600)
    
def send_first_reminder_if_silent(user_id, send_reply_func):
    state = get_state(user_id)
    if not state or state.get("stage") != "block3a":
        return  # Клиент уже ответил

    global_prompt   = load_prompt(GLOBAL_PROMPT_PATH)
    reminder_prompt = load_prompt(REMINDER_1_PROMPT_PATH)
    last_q = state.get("last_bot_question", "")
    full_prompt = global_prompt + "\n\n" + reminder_prompt + f'\n\nПоследний вопрос бота: "{last_q}"'

    reply = ask_openai(full_prompt)
    send_reply_func(reply)

    update_state(user_id, {"stage": "block3a", "last_message_ts": time.time()})

    # ставим таймер на второе напоминание
    plan(user_id,
    "blocks.block_03a:send_second_reminder_if_silent",   # <‑‑ путь к функции
    DELAY_TO_BLOCK_3_2_HOURS * 3600)


def send_second_reminder_if_silent(user_id, send_reply_func):
    state = get_state(user_id)
    if not state or state.get("stage") != "block3a":
        return  # Клиент ответил

    global_prompt   = load_prompt(GLOBAL_PROMPT_PATH)
    reminder_prompt = load_prompt(REMINDER_2_PROMPT_PATH)
    last_q = state.get("last_bot_question", "")
    full_prompt = global_prompt + "\n\n" + reminder_prompt + f'\n\nПоследний вопрос бота: "{last_q}"'

    reply = ask_openai(full_prompt)
    send_reply_func(reply)

    update_state(user_id, {"stage": "block3a", "last_message_ts": time.time()})

    # финальный таймер — ещё 4 ч тишины → block9
    def finalize_if_still_silent():
        state = get_state(user_id)
        if not state or state.get("stage") != "block3a":
            return
        update_state(user_id, {"handover_reason": "no_response_after_3_2", "scenario_stage_at_handover": "block3"})
        from router import route_message
        route_message("", user_id, force_stage="block9")
    plan(user_id,
    "blocks.block_03a:finalize_if_still_silent",   # <‑‑ путь к функции
    FINAL_TIMEOUT_HOURS * 3600)
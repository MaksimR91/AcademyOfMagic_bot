# blocks/block05.py
import time
from threading import Timer
from utils.ask_openai import ask_openai
from utils.wants_handover_ai import wants_handover_ai
from state.state import get_state, update_state, save_if_absent
from logger import logger
import re

GLOBAL_PROMPT_PATH   = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH    = "prompts/block05_prompt.txt"          # «основной» (ответ на возражение)
REM1_PROMPT_PATH     = "prompts/block05_reminder_1_prompt.txt"
REM2_PROMPT_PATH     = "prompts/block05_reminder_2_prompt.txt"

DELAY_TO_REM1_HOURS  = 4     # первое касание
DELAY_TO_REM2_HOURS  = 12    # второе
FINAL_TIMEOUT_HOURS  = 4     # затем hand-over
MAX_OBJECTION_ROUNDS = 3     # сколько раз подряд пытаемся закрыть возражение
# ----------------------------------------------------------------------

def _load(p): 
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

# ----------------------------------------------------------------------
def handle_block5(message_text: str, user_id: str, send_reply_text):
    """
    • message_text может быть пустым, если сюда прыгнули force_stage'ом из block4  
    • send_reply_text – lambda-обёртка из router'а
    """

    # --- прямой запрос Арсению ----------------------------------------
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block5"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    st = get_state(user_id) or {}

    # ------------------------------------------------------------------
    # 1. классифицируем: refusal | objection | yes
    classify_prompt = (
        "Определи реакцию клиента.\n\n"
        f'Сообщение: "{message_text}"\n\n'
        "Варианты ответа строго:\n"
        "yes            – готов купить / согласен\n"
        "refusal        – окончательный отказ\n"
        "objection      – сомнение / возражение / всё остальное\n"
    )
    label = ask_openai(classify_prompt).strip().lower()

    from router import route_message
    if label == "yes":
         # можно (не обязательно) сбросить счётчик
        update_state(user_id, {"objection_round": 0})
        return route_message("", user_id, force_stage="block6a")
    if label == "refusal":
        update_state(user_id, {"objection_round": 0})
        return route_message("", user_id, force_stage="block6b")
    # Любое иное (включая неожиданные ответы GPT) трактуем как возражение
    if label not in ("objection", "yes", "refusal"):
        label = "objection"

    # ---- лимит числа итераций возражений ----------------------------------
    objection_round = (st.get("objection_round") or 0) + 1
    if objection_round > MAX_OBJECTION_ROUNDS:
        # эскалация: не удалось закрыть возражение
        update_state(user_id, {
            "handover_reason": "objection_not_resolved",
            "scenario_stage_at_handover": "block5",
            "objection_round": objection_round,
        })
        return route_message("", user_id, force_stage="block9")

    # ------------------------------------------------------------------
    # 2. перед тем как отвечать на возражение – вытянем полезные факты
    #    (чтобы не потерять их к моменту block6a)
    extracted = {}
    low = message_text.lower()

    # пример: клиент между делом указывает гостей
    m = re.search(r"\b(\d{1,3})\s*(?:гост[ея]|человек|чел)\b", low)
    if m:
        extracted["guests_count"] = m.group(1)

    # пример: может назвать пакет прямо в возражении
    if   "базовый"  in low: extracted["package"] = "базовый"
    elif "восторг"  in low: extracted["package"] = "восторг"
    elif "фурор"    in low: extracted["package"] = "фурор"

    if extracted:
        save_if_absent(user_id, **extracted)
    # ------------------------------------------------------------------
    # 3. это возражение → спросим у GPT как ответить
    objection_prompt = (
        _load(GLOBAL_PROMPT_PATH) + "\n\n" +
        _load(STAGE_PROMPT_PATH)  + "\n\n" +
        f'Сообщение клиента: "{message_text}"'
    )
    reply = ask_openai(objection_prompt)
    send_reply_text(reply)

    update_state(user_id, {
        "stage": "block5",
        "last_bot_question": reply,
        "last_message_ts": time.time(),
        "rem1_sent": False,
        "rem2_sent": False,
        "objection_round": objection_round
    })

    # запускаем 4-часовой таймер
    Timer(DELAY_TO_REM1_HOURS * 3600,
          lambda: _reminder1_if_silent(user_id, send_reply_text)
          ).start()

# ----------------------------------------------------------------------
def _reminder1_if_silent(user_id, send_reply_text):
    st = get_state(user_id)
    if not st or st.get("stage") != "block5" or st.get("rem1_sent"):
        return
    if time.time() - st.get("last_message_ts", 0) < DELAY_TO_REM1_HOURS*3600:
        return

    prompt = (_load(GLOBAL_PROMPT_PATH) + "\n\n" +
              _load(REM1_PROMPT_PATH)   + "\n\n" +
              f'Последний вопрос бота: "{st.get("last_bot_question","")}"')
    txt = ask_openai(prompt)
    send_reply_text(txt)

    update_state(user_id, {
        "last_bot_question": txt,
        "last_message_ts":   time.time(),
        "rem1_sent":        True,
    })

    # таймер на 12 часов
    Timer(DELAY_TO_REM2_HOURS * 3600,
          lambda: _reminder2_if_silent(user_id, send_reply_text)
          ).start()

# ----------------------------------------------------------------------
def _reminder2_if_silent(user_id, send_reply_text):
    st = get_state(user_id)
    if (not st or st.get("stage") != "block5"
        or not st.get("rem1_sent") or st.get("rem2_sent")):
        return
    if time.time() - st.get("last_message_ts", 0) < DELAY_TO_REM2_HOURS*3600:
        return

    prompt = (_load(GLOBAL_PROMPT_PATH) + "\n\n" +
              _load(REM2_PROMPT_PATH)   + "\n\n" +
              f'Последний вопрос бота: "{st.get("last_bot_question","")}"')
    txt = ask_openai(prompt)
    send_reply_text(txt)

    update_state(user_id, {
        "last_bot_question": txt,
        "last_message_ts":   time.time(),
        "rem2_sent":        True,
    })

    # финальный 4-часовой таймер → block9 (handover)
    Timer(FINAL_TIMEOUT_HOURS * 3600,
          lambda: _finalize_if_silent(user_id)
          ).start()

# ----------------------------------------------------------------------
def _finalize_if_silent(user_id):
    st = get_state(user_id)
    if (st and st.get("stage") == "block5" and
        st.get("rem2_sent") and
        time.time() - st.get("last_message_ts",0) >= FINAL_TIMEOUT_HOURS*3600):
        update_state(user_id, {"handover_reason": "no_response_after_5_2", "scenario_stage_at_handover": "block5"})
        from router import route_message
        route_message("", user_id, force_stage="block9")

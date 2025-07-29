import time
import json
from utils.reminder_engine import plan
from utils.ask_openai import ask_openai
from utils.wants_handover_ai import wants_handover_ai
from state.state import get_state, update_state
from utils.constants import REQUIRED_FIELDS
from logger import logger

# ---- промпты ---------------------------------------------------------------
GLOBAL_PROMPT_PATH = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH  = "prompts/block08_prompt.txt"
REM1_PROMPT_PATH   = "prompts/block08_reminder_1_prompt.txt"
REM2_PROMPT_PATH   = "prompts/block08_reminder_2_prompt.txt"

# ---- тайминги --------------------------------------------------------------
REMINDER1_DELAY_HOURS = 4    # 8.1
REMINDER2_DELAY_HOURS = 12   # 8.2
FINAL_TIMEOUT_HOURS   = 4    # после 8.2 -> block9

# ---------------------------------------------------------------------------
def _load(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------------------------------------
def handle_block8(message_text: str, user_id: str, send_text_func):
    """
    Финальное подтверждение резюме брони.
    Входы:
      • из block7 force_stage="" (message_text="") -> нужно спросить подтверждение
      • диалоговые ответы клиента -> классифицируем
    """

    # --- прямой запрос на handover ------------------------------------
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block8"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    st = get_state(user_id) or {}

    # ----- первый вход (из block7) ------------------------------------
    if not message_text.strip():
        if st.get("resume_sent"):
            _ask_confirm_only(user_id, st, send_text_func)
        else:
            _send_resume_and_ask_confirm(user_id, st, send_text_func, is_repeat=False)
            update_state(user_id, {"resume_sent": True})
        _schedule_reminder1(user_id, send_text_func)
        return

    # ----- клиент отвечает --------------------------------------------
    label = _classify_reaction(message_text)
    logger.info(f"[block8] reaction={label} for user={user_id}")

    if label == "confirm":
        _send_thanks_and_close(user_id, send_text_func, confirmed=True)
        update_state(user_id, {"handover_reason": "confirmed_booking",
                               "scenario_stage_at_handover": "block8",
                               "reminder1_sent": False,
                               "reminder2_sent": False})
        _goto(user_id, "block9")
        return

    if label == "error_with_detail":
        _apply_corrections_from_text(user_id, message_text)
        st = get_state(user_id) or {}
        # сбрасываем reminder-флаги, т.к. начинается новый цикл подтверждения
        edit_round = st.get("edit_round", 0) + 1
        update_state(user_id, {"reminder1_sent": False,
                               "reminder2_sent": False,
                               "edit_round": edit_round})
        _send_resume_and_ask_confirm(user_id, st, send_text_func, is_repeat=True)
        _schedule_reminder1(user_id, send_text_func)
        return

    if label == "error_no_detail":
        # клиент говорит "что-то не так" без деталей -> один раз спросим, что именно
        if st.get("asked_what_wrong"):
            # уже спрашивали - эскалация
            update_state(user_id, {"handover_reason": "cannot_resolve_resume", "scenario_stage_at_handover": "block8"})
            _send_thanks_and_close(user_id, send_text_func, confirmed=False, escalate=True)
            _goto(user_id, "block9")
            return

        _ask_what_wrong(user_id, send_text_func)
        update_state(user_id, {"asked_what_wrong": True,
                               "reminder1_sent": False,
                               "reminder2_sent": False,
                               "last_message_ts": time.time()})
        _schedule_reminder1(user_id, send_text_func)
        return

    # если ничего не распознали - безопасно переспросим (1 раз),
    # затем эскалация
    if st.get("unclr_round", 0) >= 1:
        update_state(user_id, {"handover_reason": "unclear_in_block8", "scenario_stage_at_handover": "block8"})
        _send_thanks_and_close(user_id, send_text_func, confirmed=False, escalate=True)
        _goto(user_id, "block9")
        return

    # первая непонятка -> мягко попросим перепроверить
    _ask_confirm_only(user_id, st, send_text_func)
    update_state(user_id, {"unclr_round": st.get("unclr_round", 0) + 1,
                           "last_message_ts": time.time()})
    _schedule_reminder1(user_id, send_text_func)
    return

# ---------------------------------------------------------------------------
def _classify_reaction(text: str) -> str:
    """
    Быстрая классификация реакции клиента на резюме.
    Возвращает: confirm | error_with_detail | error_no_detail | unclear
    """
    low = text.lower()

    # простые эвристики (дешёвый фильтр перед GPT)
    if any(w in low for w in ("всё верно", "все верно", "ок", "подтвержд", "подходит", "годится", "так и есть")):
        return "confirm"
    if any(w in low for w in ("не верно", "неверно", "ошиб", "не то", "не так", "дата", "время", "адрес", "гостей", "пакет")):
        # возможно сразу деталь
        pass  # дадим слово GPT для точности

    # GPT-классификация
    prompt = (
        "Классифицируй реакцию клиента на резюме.\n"
        f'Сообщение: "{text}"\n\n'
        "Ответь одним словом из списка:\n"
        "confirm            – клиент подтверждает, что всё верно.\n"
        "error_with_detail  – клиент сообщает, что есть ошибка, и указывает какую (или даёт инфо для исправления).\n"
        "error_no_detail    – клиент говорит, что есть ошибка, но не поясняет какую.\n"
        "unclear            – не удалось понять.\n"
    )
    try:
        label = ask_openai(prompt).strip().lower()
        if label not in ("confirm", "error_with_detail", "error_no_detail", "unclear"):
            label = "unclear"
        return label
    except Exception as e:
        logger.error(f"[block8] classify GPT error: {e}")
        return "unclear"

# ---------------------------------------------------------------------------
def _apply_corrections_from_text(user_id: str, text: str):
    from utils.ai_extract import ai_extract_fields
    st = get_state(user_id) or {}
    data, refused = ai_extract_fields(text, st)

    if data:
        cleaned = {}
        for k, v in data.items():
            if v is None:
                continue
            if isinstance(v, str):
                v_strip = v.strip().lower()
                if v_strip in ("", "не знаю", "не уверена", "не уверен", "нет инфо", "—", "-", "n/a", "na", "null"):
                    continue
            cleaned[k] = v

        if cleaned:
            for k, v in cleaned.items():
                logger.info(f"[block8] correction {k}: {st.get(k)!r} -> {v!r} (user={user_id})")
            update_state(user_id, cleaned)

    if refused:
        prev = set(st.get("refused_fields", []))
        update_state(user_id, {"refused_fields": list(prev.union(refused))})

# ---------------------------------------------------------------------------
def _send_resume_and_ask_confirm(user_id: str, st: dict, send_text_func, is_repeat: bool):
    resume = _build_resume_text(st)
    mode = "repeat" if is_repeat else "initial"
    prompt = (
        _load(GLOBAL_PROMPT_PATH)
        + "\n\n" + _load(STAGE_PROMPT_PATH)
        + f"\n\nРежим: {mode}"
        + "\n\nРезюме заказа:\n"
        + resume
        + "\n\nСформируй короткое сообщение клиенту с просьбой подтвердить или указать правки."
    )
    try:
        txt = ask_openai(prompt)
    except Exception as e:
        logger.error(f"[block8] resume prompt error: {e}")
        txt = ("Проверьте, пожалуйста, резюме: всё ли верно? Если что-то поправить — напишите.")
    # сначала само резюме, потом текст
    send_text_func(resume)
    send_text_func(txt)

    update_state(
        user_id,
        {
            "stage": "block8",
            "resume_sent": True,
            "last_bot_question": txt,
            "last_message_ts": time.time(),
        },
    )

# ---------------------------------------------------------------------------
def _ask_confirm_only(user_id: str, st: dict, send_text_func):
    """
    Когда резюме уже отправлено в block7: мягко попросим подтвердить.
    """
    prompt = (
        _load(GLOBAL_PROMPT_PATH)
        + "\n\n" + _load(STAGE_PROMPT_PATH)
        + (
            "\n\nСитуация: резюме заказа было отправлено ранее (в предыдущем сообщении). "
            "Сформулируй короткое дружелюбное напоминание: пожалуйста, подтвердите, всё ли указано верно, "
            "или напишите, что нужно поправить."
        )
    )
    try:
        txt = ask_openai(prompt)
    except Exception as e:
        logger.error(f"[block8] ask_confirm_only error: {e}")
        txt = "Пожалуйста, подтвердите, что всё верно в резюме выше, или напишите, что поправить."
    send_text_func(txt)
    update_state(user_id, {"stage": "block8", "last_bot_question": txt, "last_message_ts": time.time()})

# ---------------------------------------------------------------------------
def _ask_what_wrong(user_id: str, send_text_func):
    prompt = (
        _load(GLOBAL_PROMPT_PATH)
        + "\n\n" + _load(STAGE_PROMPT_PATH)
        + (
            "\n\nСитуация: клиент написал, что в резюме есть ошибка, но не уточнил. "
            "Один раз вежливо попроси указать, что именно нужно исправить."
        )
    )
    try:
        txt = ask_openai(prompt)
    except Exception as e:
        logger.error(f"[block8] ask_what_wrong error: {e}")
        txt = "Подскажите, пожалуйста, что именно нужно поправить в резюме?"

    # ---- добавили сохранение последнего вопроса ----
    send_text_func(txt)
    update_state(
        user_id,
        {
            "last_bot_question": txt,
            "last_message_ts": time.time()
        }
    )

# ---------------------------------------------------------------------------
def _build_resume_text(st: dict) -> str:
    lines = []
    lines.append("📋 *Резюме заказа*")
    lines.append(f"Имя: {st.get('client_name','—')}")
    lines.append(f"Пакет: {st.get('package','—')}")
    lines.append(f"Дата/время: {st.get('event_date','—')} {st.get('event_time','')}")
    lines.append(f"Место: {st.get('address','—')}")
    lines.append(f"Гостей: {st.get('guests_count','—')}")
    if st.get("special_wishes"):
        lines.append(f"Пожелания: {st['special_wishes']}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
def _schedule_reminder1(user_id: str, send_text_func):
    """Поставить таймер на 8.1 (4ч)."""
    plan(
        user_id,
        "blocks.block_08:_reminder1_if_silent",   # модуль с подчёркиванием
        REMINDER1_DELAY_HOURS               # задержка уже в секундах
    )
# ---------------------------------------------------------------------------
def _reminder1_if_silent(user_id: str, send_text_func):
    st = get_state(user_id)
    if not st or st.get("stage") != "block8" or st.get("reminder1_sent"):
        return
    if time.time() - st.get("last_message_ts", 0) < REMINDER1_DELAY_HOURS * 3600:
        return
    prompt = _load(GLOBAL_PROMPT_PATH) + "\n\n" + _load(REM1_PROMPT_PATH)
    try:
        txt = ask_openai(prompt)
    except Exception:
        txt = "Напоминаю: проверьте, пожалуйста, данные. Если нужно поправить — дайте знать."
    send_text_func(txt)
    update_state(user_id, {"reminder1_sent": True, "last_bot_question": txt, "last_message_ts": time.time()})
    plan(
        user_id,
        "blocks.block_08:_reminder2_if_silent",   # модуль с подчёркиванием
        REMINDER2_DELAY_HOURS               # задержка уже в секундах
    )

# ---------------------------------------------------------------------------
def _reminder2_if_silent(user_id: str, send_text_func):
    st = get_state(user_id)
    if (not st or st.get("stage") != "block8"
        or not st.get("reminder1_sent")
        or st.get("reminder2_sent")):
        return
    if time.time() - st.get("last_message_ts", 0) < REMINDER2_DELAY_HOURS * 3600:
        return
    prompt = _load(GLOBAL_PROMPT_PATH) + "\n\n" + _load(REM2_PROMPT_PATH)
    try:
        txt = ask_openai(prompt)
    except Exception:
        txt = ("Я пока закрываю бронь, т.к. не получил подтверждения. "
               "Если тема актуальна, напишите — постараемся помочь.")
    send_text_func(txt)
    update_state(user_id, {"reminder2_sent": True, "last_bot_question": txt, "last_message_ts": time.time()})
    # финальный таймер 4ч -> проверка тишины перед handover
    plan(
        user_id,
        "blocks.block_08:_finalize_if_silent_8",   # модуль с подчёркиванием
        FINAL_TIMEOUT_HOURS               # задержка уже в секундах
    )

# ---------------------------------------------------------------------------
def _send_thanks_and_close(user_id: str, send_text_func, *, confirmed: bool, escalate: bool=False):
    """
    Сообщение при финальном подтверждении или эскалации.
    """
    if confirmed:
        # финальное спасибо
        prompt = (
            _load(GLOBAL_PROMPT_PATH)
            + "\n\n" + _load(STAGE_PROMPT_PATH)
            + "\n\nСитуация: клиент подтвердил резюме. Поблагодари и скажи, что при необходимости Арсений свяжется ближе к дате."
        )
    elif escalate:
        prompt = (
            _load(GLOBAL_PROMPT_PATH)
            + "\n\n" + _load(STAGE_PROMPT_PATH)
            + "\n\nСитуация: не удаётся согласовать резюме. Поблагодари и скажи, что передаёшь Арсению."
        )
    else:
        prompt = (
            _load(GLOBAL_PROMPT_PATH)
            + "\n\n" + _load(STAGE_PROMPT_PATH)
            + "\n\nСитуация: завершение без подтверждения. Поблагодари и скажи, что передаёшь Арсению."
        )
    try:
        txt = ask_openai(prompt)
    except Exception:
        if confirmed:
            txt = "Отлично, всё подтвердили. Спасибо! Если понадобятся уточнения, Арсений свяжется ближе к дате."
        else:
            txt = "Хорошо, я передам информацию Арсению. Он свяжется с вами позднее. Спасибо!"
    send_text_func(txt)

# ---------------------------------------------------------------------------
def _goto_with_reason(user_id: str, stage: str, reason: str):
    update_state(user_id, {"handover_reason": reason})
    _goto(user_id, stage)

# ---------------------------------------------------------------------------
def _goto(user_id: str, next_stage: str):
    update_state(user_id, {"stage": next_stage, "last_message_ts": time.time()})
    from router import route_message
    route_message("", user_id, force_stage=next_stage)
# ---------------------------------------------------------------------------
def _finalize_if_silent_8(user_id: str):
    """
    Финальная проверка молчания после второго напоминания (8.2) перед hand‑over.
    Условие: всё ещё block8, отправлено второе напоминание, прошло >= FINAL_TIMEOUT_HOURS,
    и пользователь не ответил.
    """
    st = get_state(user_id)
    if not st:
        return
    if st.get("stage") != "block8":
        return
    if not st.get("reminder2_sent"):
        return
    # достаточное молчание
    if time.time() - st.get("last_message_ts", 0) < FINAL_TIMEOUT_HOURS * 3600:
        return

    # Можно добавить защиту: если вдруг всё подтверждено (редкий случай),
    # то не эскалируем. Например:
    # if st.get("handover_reason") == "confirmed_booking": return

    update_state(user_id, {"handover_reason": "no_response_after_8_2", "scenario_stage_at_handover": "block8"})
    _goto(user_id, "block9")
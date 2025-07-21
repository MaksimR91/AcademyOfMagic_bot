import time
import json
import re
from threading import Timer
from utils.ask_openai         import ask_openai
from utils.wants_handover_ai  import wants_handover_ai
from state.state              import get_state, update_state, save_if_absent
from utils.constants import REQUIRED_FIELDS, FLAG_SUFFIX, MAX_Q_ATTEMPTS
from logger                   import logger
from utils.check_payment_validity import validate_payment
from utils.ai_extract import ai_extract_fields

# ────────── файлы‑промпты ───────────────────────────────────────────────────
GLOBAL_PROMPT_PATH   = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH    = "prompts/block07_prompt.txt"

REM1_PROMPT_PATH     = "prompts/block07_reminder_1_prompt.txt"
REM2_PROMPT_PATH     = "prompts/block07_reminder_2_prompt.txt"
REMINDER_2_DELAY_HOURS = 12     # между 7.1 и 7.2
# ────────── тайминги ────────────────────────────────────────────────────────
REMINDER_HOURS       = 4          # первое (и единственное) повторное касание
FINAL_TIMEOUT_HOURS  = 4          # после ремайндера → block9

# ────────── утилита для чтения файла ────────────────────────────────────────
def _load(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

# ------------------------------------------------------------------
def _recalc_flags(st: dict) -> dict:
    """
    Высчитывает <field>_ok по текущему состоянию.
    Логику «частично/полностью» можно расширять.
    """
    res = {}
    # --- дата / время раздельно ------------------------------------
    res["event_date_ok"]  = bool(re.match(r"\d{4}-\d{2}-\d{2}$", str(st.get("event_date",""))))
    res["event_time_ok"]  = bool(re.match(r"\d{2}:\d{2}$",      str(st.get("event_time",""))))
    # --- остальные просто not None/"" ------------------------------
    for f in REQUIRED_FIELDS:
        if f in ("event_date","event_time"): continue
        res[f + FLAG_SUFFIX] = bool(st.get(f))
    return res

# ────────────────────────────────────────────────────────────────────────────
def handle_block7(
    message_text:   str,
    user_id:        str,
    send_text_func,                 # λ‑обёртка из router.py
):
    """
    Этап 7: получаем ответы + чек, валидируем, решаем дальнейший переход.
    """

    # 0) прямой запрос к Арсению
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block7"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    # ------------------------------------------------------------------    
    state = get_state(user_id) or {}

    # --- AI‑парсер --------------------------------------------------
    if message_text.strip():
        extracted_ai, refused = ai_extract_fields(message_text, state)
        if extracted_ai:
            save_if_absent(user_id, **extracted_ai)

        # отмечаем отказанные поля
        if refused:
            prev = set(state.get("refused_fields", []))
            update_state(user_id, {"refused_fields": list(prev.union(refused))})
    _harvest_quick_facts(message_text, user_id)

    state = get_state(user_id) or {}      # свежий снап после сохранений
    # ─── 1. пересчитываем флаги completeness ────────────────────────
    flags = _recalc_flags(state)
    update_state(user_id, flags)
    # сразу берём «обновлённое» состояние
    state = {**state, **flags}

    # ────── (B) Проверяем, приложил ли клиент чек ──────────────────────
    # Предполагаем, что в  state уже лежит URL файла WhatsApp
    proof_url  = state.get("payment_proof_url")      # кладётся в handler-е MEDIA
    if proof_url and "payment_valid" not in state:   # ещё не проверяли
        try:
            import requests, tempfile, os
            r = requests.get(proof_url, timeout=20)
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(r.content)
                tmp_path = tmp.name

            result = validate_payment(tmp_path, min_amount=30_000)
            update_state(user_id, {
                "payment_valid":  result["valid"],
                "payment_issues": result["issues"],
            })
            os.remove(tmp_path)
        except Exception as e:
            logger.error(f"[block7] payment validation failed: {e}")
            update_state(user_id, {"payment_valid": False,
                                   "payment_issues": ["Ошибка проверки"]})
    
    # ── таймеры повторных касаний ───────────────────────────────────
    def _set_timer_if_needed():
        st = get_state(user_id)
        # если уже перешли в другой блок или недавно ответил – выходим
        if (not st or st.get("stage") != "block7" or
            time.time() - st.get("last_message_ts", 0) < REMINDER_HOURS*3600):
            return
        # если больше нечего спрашивать и чек валиден – напоминания не нужны
        if (all(st.get(f+FLAG_SUFFIX) for f in REQUIRED_FIELDS)
            and st.get("payment_valid")):
            return
        # если уже отправляли 1‑е напоминание – ждём 2‑е
        if st.get("reminder1_sent") and not st.get("reminder2_sent"):
            delay = REMINDER_2_DELAY_HOURS * 3600
            Timer(delay,
                  lambda: _reminder2_if_silent(user_id, send_text_func)
            ).start()
        # иначе ставим таймер на 7.1
        elif not st.get("reminder1_sent"):
            Timer(REMINDER_HOURS * 3600,
                  lambda: _reminder1_if_silent(user_id, send_text_func)
            ).start()
    proof_ok  = bool(state.get("payment_valid"))
    has_proof = bool(state.get("payment_proof_url"))
# ───  Бронирование даты сразу после валидного чека  ────────────
    if proof_ok and not state.get("slot_reserved"):
        from utils.schedule import reserve_slot
        try:
            dt_ok = reserve_slot(state.get("event_date"),
                                 state.get("event_time"))
        except Exception as e:
            logger.error(f"[block7] reserve_slot error: {e}")
            dt_ok = False

        if not dt_ok:
            send_text_func(
                "Оплату получил, спасибо! Сейчас уточню расписание и окончательно "
                "подтвержу дату. Арсений свяжется с вами в ближайшее время."
            )
            update_state(user_id, {"handover_reason": "reserve_failed", "scenario_stage_at_handover": "block7"})
            _goto(user_id, "block9")
            return

        update_state(user_id, {"slot_reserved": True})
        state["slot_reserved"] = True

    refused_fields = set(state.get("refused_fields", []))
    missing = [
        f for f in REQUIRED_FIELDS
        if not state.get(f + FLAG_SUFFIX, False) and f not in refused_fields
    ]

    # --- лимит попыток ----------------------------------------------
    q_attempts = state.get("question_round", 0)
    if q_attempts >= MAX_Q_ATTEMPTS and missing:
        update_state(user_id, {"handover_reason": "missing_required_fields", "scenario_stage_at_handover": "block7"})
        _goto(user_id, "block9")
        return
 # ────── (D) решаем, куда идти ──────────────────────────────────────
    if proof_ok and state.get("slot_reserved") and missing:
        # 1) фиксируем бронь в одном коротком сообщении
        send_text_func("✅ Дата и время забронированы! Осталось уточнить ещё пару деталей:")

        # 2) формируем вопросы (need_action='questions_only_confirmed')
        reply = _compose_reply(state, missing, "questions_only_confirmed")
        send_text_func(reply)

        update_state(user_id, {
            **state,
            "stage": "block7",
            "last_bot_question": reply,
            "last_message_ts": time.time(),
            "question_round": q_attempts + 1,
        })
        _set_timer_if_needed()
        return
    if proof_ok and state.get("slot_reserved") and not missing:
        _send_booking_summary(user_id, state, send_text_func)
        _goto(user_id, "block8")
        return
    # если чек сомнительный – сразу хенд‑овер
    if has_proof and not proof_ok:
         update_state(user_id, {"handover_reason": "payment_invalid", "scenario_stage_at_handover": "block7"})
         _goto(user_id, "block9")
         return

    # если чек не прислали, но данные есть – деликатно просим чек
    if missing and not has_proof:
        need_action = "questions_and_payment"
    elif missing:
        need_action = "questions_only"
    else:
        need_action = "payment_only"

    reply = _compose_reply(state, missing, need_action)
    send_text_func(reply)

    update_state(user_id, {
        **state,
        "stage": "block7",
        "last_bot_question": reply,
        "last_message_ts":   time.time(),
        "question_round": q_attempts + 1,          # счётчик попыток
    })

    _set_timer_if_needed()

# ════════════════════════════════════════════════════════════════════════════
def _harvest_quick_facts(text: str, user_id: str):
    """
    Пытаемся вытащить «простой» ответ без GPT:
    возраст / фото? / видел ли шоу и т.п.
    """
    if not text:
        return
    low = text.lower()
    extracted = {}

    # возраст виновника (цифра + "лет")
    m = re.search(r"\b(\d{1,2})\s*лет\b", low)
    if m:
        extracted["celebrant_age"] = m.group(1)

    # видели шоу?
    if "видел" in low or "уже был" in low:
        extracted["saw_show_before"] = True

    if extracted:
        save_if_absent(user_id, **extracted)

# ---------------------------------------------------------------------------
def _compose_reply(state: dict, missing: list[str], need_action: str) -> str:
    """
    Кормим GPT компактным промптом с JSON‑снимком состояния и
    флагом, что именно нужно (вопросы и/или чек).
    """
    state_json = json.dumps({k: state.get(k) for k in REQUIRED_FIELDS},
                            ensure_ascii=False, indent=2)
    flags_json = json.dumps({k+FLAG_SUFFIX: state.get(k+FLAG_SUFFIX)
                             for k in REQUIRED_FIELDS},
                            ensure_ascii=False, indent=2)
    system_prompt = (
         _load(GLOBAL_PROMPT_PATH)
         + "\n\n" + _load(STAGE_PROMPT_PATH)
         + "\n\nДанные клиента (JSON):\n```json\n" + state_json + "\n```"
         + "\n\nФлаги заполненности:\n```json\n" + flags_json + "\n```"
         + f"\n\nНужно сделать: {need_action}"
         + (f"\nНедостающие поля: {', '.join(missing)}" if missing else "")
    )
    try:
        return ask_openai(system_prompt)
    except Exception as e:
        logger.error(f"[block7] GPT error: {e}")
        # fallback — простое сообщение
        return (
            "Благодарю! Для окончательного бронирования нужно ответить на пару "
            "вопросов и прислать фото/скрин чека (50 % предоплаты)."
        )

# ---------------------------------------------------------------------------
def _send_booking_summary(user_id: str, st: dict, send_text_func):
    summary_lines = [
        f"✅ *Бронь подтверждена!*",
        f"Имя клиента: {st.get('client_name','—')}",
        f"Пакет: {st.get('package','—')}",
        f"Дата/время: {st.get('event_date','—')} {st.get('event_time','')}",
        f"Место: {st.get('address','—')}",
        f"Гостей: {st.get('guests_count','—')}",
    ]
    if st.get("special_wishes"):
        summary_lines.append(f"Пожелания: {st['special_wishes']}")
    send_text_func("\n".join(summary_lines))

    # зафиксируем, что полное резюме уже отправлено на шаге 7
    update_state(user_id, {"resume_sent": True})

# ---------------------------------------------------------------------------
def _goto(user_id: str, next_stage: str):
    """
    Унифицированный переход.
    """
    update_state(user_id, {"stage": next_stage, "last_message_ts": time.time()})
    from router import route_message
    route_message("", user_id, force_stage=next_stage)

# ---------------------------------------------------------------------------
# ---- напоминание 7.1 -------------------------------------------------------
def _reminder1_if_silent(user_id: str, send_text_func):
    st = get_state(user_id)
    if not st or st.get("stage") != "block7":
        return
    if time.time() - st.get("last_message_ts", 0) < REMINDER_HOURS * 3600:
        return

    prompt = _load(REM1_PROMPT_PATH)
    try:
        txt = ask_openai(_load(GLOBAL_PROMPT_PATH) + "\n\n" + prompt)
    except Exception:
        txt = "Напоминаю, что жду ваш ответ и подтверждение оплаты. Если нужно, я на связи!"

    send_text_func(txt)

    update_state(user_id, {
        "reminder1_sent": True,
        "last_bot_question": txt,
        "last_message_ts": time.time(),
    })

    # ставим таймер на 7.2 через 12 ч
    Timer(
        REMINDER_2_DELAY_HOURS * 3600,
        lambda: _reminder2_if_silent(user_id, send_text_func)
    ).start()

# ---- напоминание 7.2 -------------------------------------------------------
def _reminder2_if_silent(user_id: str, send_text_func):
    st = get_state(user_id)
    if (not st or st.get("stage") != "block7"
        or not st.get("reminder1_sent")
        or st.get("reminder2_sent")):
        return
    if time.time() - st.get("last_message_ts", 0) < REMINDER_2_DELAY_HOURS*3600:
        return

    try:
        txt = ask_openai(_load(GLOBAL_PROMPT_PATH) + "\n\n" + _load(REM2_PROMPT_PATH))
    except Exception:
        txt = ("Напоминаю, что без полной информации и оплаты "
               "мы не сможем удерживать дату. Я на связи, если нужно помочь!")

    send_text_func(txt)

    update_state(user_id, {
        "reminder2_sent": True,
        "last_bot_question": txt,
        "last_message_ts": time.time(),
    })

    # финальный 4‑часовой таймер с проверкой тишины
    Timer(
        FINAL_TIMEOUT_HOURS * 3600,
        lambda: _finalize_if_silent_7(user_id)
    ).start()


def _finalize_if_silent_7(user_id: str):
    """
    Финальная проверка молчания после второго напоминания этапа 7 перед hand‑over.
    """
    st = get_state(user_id)
    if not st:
        return
    if st.get("stage") != "block7":
        return
    # второе напоминание отправлено?
    if not st.get("reminder2_sent"):
        return
    # прошло ли FINАЛЬНОЕ окно тишины?
    if time.time() - st.get("last_message_ts", 0) < FINAL_TIMEOUT_HOURS * 3600:
        return

    # Проставляем причину handover и уходим в block9
    update_state(user_id, {"handover_reason": "no_response_after_7_2", "scenario_stage_at_handover": "block7"})
    _goto(user_id, "block9")
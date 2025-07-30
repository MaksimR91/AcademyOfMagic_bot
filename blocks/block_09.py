import time
from utils.s3_upload import upload_image
import requests, os
from utils.ask_openai import ask_openai
from state.state import get_state, update_state
from utils.wants_handover_ai import wants_handover_ai
from logger import logger

GLOBAL_PROMPT = "prompts/global_prompt.txt"
STAGE_PROMPT  = "prompts/block09_prompt.txt"

# ---------------------------------------------------------------------------
def _load(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------------------------------------
def handle_block9(
    message_text: str,
    user_id: str,
    send_text_func,          # клиенту
    send_owner_text,         # Арсению (текст)
    send_owner_media=None,   # Арсению (медиа), опционально
):
    """
    Универсальный hand-over: формируем расширенное резюме и передаём
    Арсению. Вызывается force_stage='block9' из любого блока.
    """
    if wants_handover_ai(message_text):
        # уже в процессе передачи — игнорируем повторную просьбу
        pass

    st = get_state(user_id) or {}
    # Если не зафиксировали этап для CRM – фиксируем текущий
    if not st.get("scenario_stage_at_handover"):
        update_state(user_id, {"scenario_stage_at_handover": st.get("stage")})
    # --- 1. Отправка резюме Арсению (однократно) ---------------------
    if not st.get("arseniy_notified"):
        reason  = st.get("handover_reason", "")
        comment = _reason_to_comment(reason)
        summary = _build_summary(st, comment)
        # Постоянная подпись для Арсения (всегда одинаковая)
        msg_to_owner = summary + (
            "\n\n—––\n"
            "📌 Пожалуйста, обработай этот заказ и, при необходимости, "
            "свяжись с клиентом."
        )
        try:
            logger.info("[block9] → owner: %s… (%d симв.)",
                        msg_to_owner[:60].replace("\n", " "),
                        len(msg_to_owner))
            send_owner_text(msg_to_owner)
            logger.info(f"[block9] summary sent to owner user={user_id}")
        except Exception as e:
            logger.error(f"[block9] failed to send owner summary: {e}")

        # --- 1a. Фото именинника -------------------------------------
        if st.get("celebrant_photo_id"):
            _forward_and_persist_photo(
                st["celebrant_photo_id"],
                user_id,
                send_owner_media,
            )


        update_state(user_id, {"arseniy_notified": True})

    # --- 2. Сообщение клиенту (если ещё не уведомили) ---------------
    if not st.get("client_notified_about_handover"):
        try:
            prompt = (
                _load(GLOBAL_PROMPT) + "\n\n" + _load(STAGE_PROMPT) +
                "\n\nСИТУАЦИЯ: бот передаёт диалог Арсению. Сформируй короткое дружелюбное сообщение: "
                "поблагодари, скажи что Арсений свяжется при необходимости, заверши позитивно."
            )
            txt = ask_openai(prompt).strip()
        except Exception:
            txt = ("Спасибо! Передал информацию Арсению – он посмотрит детали и свяжется с вами при необходимости. "
                   "Хорошего дня!")
        send_text_func(txt)
        update_state(user_id, {
            "client_notified_about_handover": True,
            "last_message_ts": time.time(),
        })

    # --- 3. Переход к block10 (CRM) ---------------------------------
    _goto(user_id, "block10")

# ---------------------------------------------------------------------------
def _build_summary(st: dict, comment: str) -> str:
    """
    Расширенный шаблон. Пустые значения оставляем пустыми (не выдумываем).
    """
    def _yes_no(val):
        if val is True:
            return "Да"
        if val is False:
            return "Нет"
        return ""

    date_time = ""
    if st.get("event_date"):
        date_time = st["event_date"]
    if st.get("event_time"):
        date_time = (date_time + " " + st["event_time"]).strip()

    payment_status = ""
    if "payment_valid" in st:
        payment_status = _yes_no(st.get("payment_valid"))
    amount = st.get("payment_amount") or ""

    saw_before = ""
    if "saw_show_before" in st:
        saw_before = _yes_no(st.get("saw_show_before"))

    has_photo = "Да" if st.get("celebrant_photo_id") else "Нет"

    children_client = ""
    raw_children = st.get("client_children_attend")
    if isinstance(raw_children, bool):
        children_client = _yes_no(raw_children)
    elif raw_children:
        children_client = str(raw_children)

    lines = [
        "📄 *Резюме для Арсения*",
        f"Этап сценария: {st.get('stage','')}",
        f"Имя клиента: {st.get('client_name','')}",
        f"Тип шоу: {st.get('show_type','')}",
        f"Формат мероприятия: {st.get('event_description','')}",
        f"Выбранный пакет: {st.get('package','')}",
        f"Дата, время: {date_time}",
        f"Адрес: {st.get('address','')}",
        f"Имя виновника торжества: {st.get('celebrant_name','')}",
        f"Возраст виновника: {st.get('celebrant_age','')}",
        f"Количество гостей: {st.get('guests_count','')}",
        f"Пол гостей: {st.get('guests_gender','')}",
        f"Внесена ли предоплата: {payment_status}",
        f"Сумма предоплаты (тенге): {amount}",
        f"Будут ли дети клиента: {children_client}",
        f"Видел(а) шоу раньше?: {saw_before}",
        f"Есть фото именинника: {has_photo}",
    ]

    if st.get("decline_reason"):
        lines.append(f"Причина отказа: {st.get('decline_reason')}")
    if st.get("special_wishes"):
        lines.append(f"Особенности/пожелания: {st.get('special_wishes')}")
    lines.append(f"Комментарий: {comment}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
def _reason_to_comment(reason: str) -> str:
    mapping = {
        "asked_handover": "Клиент попросил живое общение.",
        "early_date_or_busy": "Срочная дата или слот занят – нужна ручная проверка.",
        "non_standard_show": "Нестандартный формат шоу – нужна консультация.",
        "objection_not_resolved": "Не удалось закрыть возражение.",
        "client_declined": "Клиент отказался от заказа.",
        "payment_invalid": "Не удалось подтвердить оплату / сомнительный чек.",
        "missing_required_fields": "Не удалось собрать обязательные данные.",
        "cannot_resolve_resume": "Не удалось согласовать резюме (нет деталей).",
        "unclear_in_block8": "Непонятный ответ при подтверждении резюме.",
        "confirmed_booking": "Все данные получены – заказ зафиксирован.",
        "no_response_after_7_2": "Молчание после двух напоминаний этапа 7.",
        "no_response_after_8_2": "Молчание после двух напоминаний этапа 8.",
        "reserve_failed": "Не удалось подтвердить слот расписания.",
    }
    return mapping.get(reason, reason or "")
# ---------------------------------------------------------------------------
# ⬇︎ помощник: скачиваем из WhatsApp, кладём в S3, шлём Арсению
def _forward_and_persist_photo(media_id: str, user_id: str, send_owner_media):
    """
    • шлём фото Арсению (image/document)
    • перекладываем в S3 и сохраняем постоянную ссылку в state
    Выполняем ОДИН раз — если уже есть celebrant_photo_url, пропускаем.
    """
    from state.state import get_state, update_state
    st = get_state(user_id) or {}

    # --- 0. отправляем Арсению (может упасть, не критично) -------
    if send_owner_media:
        try:
            send_owner_media(media_id)
        except Exception as e:
            logger.warning(f"[block9] send_owner_media fail: {e}")

    # --- 1. если уже сохранена постоянная ссылка — выход ----------
    if st.get("celebrant_photo_url"):
        return

    # --- 2. запрашиваем временный URL у Meta ----------------------
    token = os.getenv("WHATSAPP_TOKEN") or st.get("wa_token")  # fallback
    try:
        meta = requests.get(
            f"https://graph.facebook.com/v17.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        ).json()
        file_url = meta["url"]
        img_resp = requests.get(file_url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        img_resp.raise_for_status()
    except Exception as e:
        logger.error(f"[block9] cannot fetch media {media_id}: {e}")
        return

    # --- 3. кладём в S3 -------------------------------------------
    try:
        perm_url = upload_image(img_resp.content)
        update_state(user_id, {"celebrant_photo_url": perm_url})
        logger.info(f"[block9] photo uploaded → {perm_url} user={user_id}")
    except Exception as e:
        logger.error(f"[block9] S3 upload failed: {e}")

# ---------------------------------------------------------------------------
def _goto(user_id: str, next_stage: str):
    update_state(user_id, {"stage": next_stage, "last_message_ts": time.time()})
    from router import route_message
    route_message("", user_id, force_stage=next_stage)
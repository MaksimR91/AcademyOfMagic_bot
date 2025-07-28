# router.py
import os
from state.state import get_state
from logger import logger
from utils.whatsapp_senders import send_text, send_document, send_video, send_image

# ===== блоки ===============================================================
from blocks import (
    block_01, block_02,
    block_03a, block_03b, block_03c, block_03d,
    block_04, block_05,
    block_06a, block_06b,
    block_07, block_08,
    block_09, block_10,
)

# ── читаем список админ‑номеров один раз при импорте ────────────────
ADMIN_NUMBERS = {
    num.strip() for num in os.getenv("ADMIN_NUMBERS", "").split(",") if num.strip()
}
# --- <stage> → (module, handler_name) --------------------------------------
BLOCK_MAP = {
    "block1":  (block_01,  "handle_block1"),
    "block2":  (block_02,  "handle_block2"),
    "block3a": (block_03a, "handle_block3a"),
    "block3b": (block_03b, "handle_block3b"),
    "block3c": (block_03c, "handle_block3c"),
    "block3d": (block_03d, "handle_block3d"),
    "block4":  (block_04,  "handle_block4"),
    "block5":  (block_05,  "handle_block5"),
    "block6a": (block_06a, "handle_block6a"),
    "block6b": (block_06b, "handle_block6b"),
    "block7":  (block_07,  "handle_block7"),
    "block8":  (block_08,  "handle_block8"),
    "block9":  (block_09,  "handle_block9"),
    "block10": (block_10, "handle_block10"),
}

# ---------------------------------------------------------------------------
def route_message(
    message_text: str,
    user_id: str,
    client_name: str | None = None,
    *,
    force_stage: str | None = None
):
    """
    · Определяем текущий этап пользователя  
    · Готовим callables для WhatsApp  
    · Дергаем нужный handler‑блок
    """
    # -------- подготовка функций отправки (нужны ПЕРЕД #reset) -----------
    wa_to = (get_state(user_id) or {}).get("normalized_number", user_id)
    send_text_func     = lambda body:     send_text(wa_to, body)
    send_document_func = lambda media_id: send_document(wa_to, media_id)
    send_video_func    = lambda media_id: send_video(wa_to, media_id)

    # ---------- техническая команда "#reset" (только для админа) ----------
    if message_text.strip() == "#reset":
        if user_id in ADMIN_NUMBERS:
            from state.state import delete_state
            delete_state(user_id)

            # чистим отложенные джобы
            from utils.reminder_engine import sched
            for job in sched.get_jobs():
                if job.id.startswith(f"{user_id}:"):
                    sched.remove_job(job.id)

            # отвечаем сразу в канал (без лишних лямбд)
            send_text(wa_to, "State cleared.")
        else:
            logger.warning("Ignored #reset from non‑admin %s", user_id)
            send_text(wa_to, "Команда недоступна.")
        return
    elif message_text.strip() == "#jobs" and user_id in ADMIN_NUMBERS:
        from utils.reminder_engine import sched
        jobs = "\n".join(j.id for j in sched.get_jobs())
        send_text(wa_to, jobs or "нет job‑ов")
        return
    state = get_state(user_id) or {}
    stage = force_stage or state.get("stage", "block1")

    logger.info(f"📍 route_message → user={user_id} stage={stage}")


    # канал для сообщений Арсению
    OWNER_WA_ID = "787057065073"                     # Meta‑формат (+7 … → 7)
    send_owner_text  = lambda body: send_text(OWNER_WA_ID, body)
    def send_owner_media(media_id: str):
        # Сначала пробуем как image, при ошибке — document
        try:
            send_image(OWNER_WA_ID, media_id)
        except Exception as e_img:
            logger.warning(f"[router] send_owner_media image failed ({e_img}); retry as document")
            try:
                send_document(OWNER_WA_ID, media_id)
            except Exception as e_doc:
                logger.error(f"[router] send_owner_media document also failed: {e_doc}")

    # -------- выбираем модуль и имя функции --------------------------------
    mod, handler_name = BLOCK_MAP.get(stage, BLOCK_MAP["block1"])
    handler = getattr(mod, handler_name)

    try:
        # Унифицированный вызов: каждая функция сама знает,
        # какие аргументы ей нужны.
        if stage == "block4":
            handler(
                message_text,
                user_id,
                send_text_func,
                send_document_func,
                send_video_func,
            )
        elif stage == "block9":
            handler(
            message_text,
            user_id,
            send_text_func,     # клиент
            send_owner_text,    # текст Арсению
            send_owner_media,   # универсальная пересылка фото
        )
        else:
            handler(message_text, user_id, send_text_func)
    except Exception as e:
        logger.exception(f"💥 Ошибка в блоке {stage} для {user_id}: {e}")
        send_text_func("Произошла техническая ошибка, попробуйте позже.")

    # router ничего не возвращает — вся отправка делается внутри блоков

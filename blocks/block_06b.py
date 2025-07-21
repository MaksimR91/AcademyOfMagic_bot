# blocks/block_06b.py
import time
from utils.ask_openai          import ask_openai
from utils.wants_handover_ai   import wants_handover_ai
from state.state               import update_state
from logger                    import logger

# ── пути к промптам ─────────────────────────────────────────────────────────
GLOBAL_PROMPT_PATH = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH  = "prompts/block06b_prompt.txt"   # «Спасибо + завершение»

# ── вспомогалка для чтения файлов ------------------------------------------
def _load(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

# ────────────────────────────────────────────────────────────────────────────
def handle_block6b(
    message_text:   str,
    user_id:        str,
    send_text_func,                 # λ‑обёртка из router.py
):
    """
    Клиент окончательно отказался.

    ▸ Если вдруг просит прямой контакт — сразу hand‑over → block9.  
    ▸ Иначе: благодарим, завершаем диалог, после чего тоже переходим в block9
      (stage «завершено» / hand‑over c пометкой «refused»).
    """

    # 1) Проверяем явный запрос к Арсению
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block6b"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    # 2) Формируем благодарственное завершающее сообщение
    prompt = (
        _load(GLOBAL_PROMPT_PATH)
        + "\n\n"
        + _load(STAGE_PROMPT_PATH)
    )

    try:
        reply = ask_openai(prompt)
    except Exception as e:
        logger.error(f"[block6b] GPT error: {e}")
        reply = (
            "Спасибо, что уделили время. "
            "Буду рад помочь, если в будущем заинтересует выступление Арсения!"
        )

    send_text_func(reply)

    # 3) Обновляем состояние и передаём управление в block9
    update_state(
        user_id,
        {
            "stage":            "block9",       # помечаем как завершённое
            "last_bot_question": reply,
            "last_message_ts":   time.time(),
            "deal_status":       "refused",     # можно использовать в block9
        },
    )

    from router import route_message
    # Переходим в block9 без лишнего текста: человек уже получил финальное сообщение
    update_state(user_id, {"handover_reason": "client_declined", "scenario_stage_at_handover": "block6b"})
    route_message("", user_id, force_stage="block9")

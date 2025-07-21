# blocks/block_06a.py
import time
import json
from utils.ask_openai import ask_openai
from utils.wants_handover_ai import wants_handover_ai
from state.state import get_state, update_state
from utils.constants import REQUIRED_FIELDS

# ---------- пути к промптам -------------------------------------------------
GLOBAL_PROMPT_PATH = "prompts/global_prompt.txt"
STAGE_PROMPT_PATH  = "prompts/block06a_prompt.txt"      # (описанный выше)

# ---------------------------------------------------------------------------

def _load(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------------------------------------

def handle_block6a(
    message_text: str,
    user_id: str,
    send_text_func,
):
    """
    Получено согласие («да, берём шоу»).

    1. Проверяем явный hand-over.
    2. Составляем список недостающих полей.
    3. Отправляем одно благодарственное / уточняющее сообщение.
    4. Переводим stage → block7 (дальше отвечает клиент).
    """

    # 1) Просьба «передайте Арсению»
    if wants_handover_ai(message_text):
        update_state(user_id, {"handover_reason": "asked_handover", "scenario_stage_at_handover": "block6a"})
        from router import route_message
        return route_message(message_text, user_id, force_stage="block9")

    # ------------------------------------------------------------------    
    state = get_state(user_id) or {}

    # список недостающих полей (можно вставить в промпт, см. ниже)
    missing = [f for f in REQUIRED_FIELDS if not state.get(f)]

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------    
    # ------------------------------------------------------------------
    # JSON-снимок состояния, чтобы LLM видела, какие поля заполнены:
    state_json = json.dumps({k: state.get(k) for k in REQUIRED_FIELDS},
                            ensure_ascii=False, indent=2)

    prompt = (
        _load(GLOBAL_PROMPT_PATH)
        + "\n\n"
        + _load(STAGE_PROMPT_PATH)
        + "\n\nДанные клиента (JSON):\n```json\n"
        + state_json
        + "\n```\n"
        + f"\nНедостающие поля: {', '.join(missing) if missing else '—'}"
    )

    reply = ask_openai(prompt)
    send_text_func(reply)

    # ------------------------------------------------------------------    
    # Сразу переключаем пользователя на блок 7 – там мы будем ждать ответы
    update_state(
        user_id,
        {
            **state,
            "stage": "block7",
            "last_bot_question": reply,
            "last_message_ts": time.time(),
        },
    )

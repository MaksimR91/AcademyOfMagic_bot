# Словарь, где ключ — номер телефона, значение — состояние
user_states = {}

def get_state(user_id):
    return user_states.get(user_id)

def set_state(user_id, state):
    user_states[user_id] = state

def reset_state(user_id):
    user_states.pop(user_id, None)

def update_state(user_id, updates: dict):
    current = get_state(user_id) or {}
    current.update(updates)
    set_state(user_id, current)
    # ---------------------------------------------------------------------------
# Helper: кладём только если ещё пусто
def save_if_absent(user_id, **kwargs):
    """
    Сохраняет пары ключ-значение, но **только** если такого ключа ещё нет
    или он пустой/None/''.
    """
    st = get_state(user_id) or {}
    fresh = {k: v for k, v in kwargs.items() if not st.get(k)}
    if fresh:
        update_state(user_id, fresh)

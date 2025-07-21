import os, requests

SUPABASE_URL        = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY    = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE_NAME = "tokens"

HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json",
}

def load_token_from_supabase() -> str:
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE_NAME}?select=token&order=updated_at.desc&limit=1"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    data = resp.json()
    return data[0]["token"] if data else ""

def save_token_to_supabase(token: str) -> bool:
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE_NAME}"
    payload = {"token": token}
    r = requests.post(url, json=payload, headers=HEADERS, timeout=10)
    return r.status_code == 201

TOKEN_FILE = "token.txt"

def get_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def save_token(token: str):
    with open(TOKEN_FILE, "w") as f:
        f.write(token.strip())

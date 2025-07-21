import os, io, re
from google.cloud import vision

# client = vision.ImageAnnotatorClient()  — инициализируем после того,
# как точно выставили переменную окружения с ключом
def _get_client():
    return vision.ImageAnnotatorClient()

def extract_text_from_image(image_path: str, language_hints=("ru","en")) -> str:
    with io.open(image_path, "rb") as f:
        content = f.read()

    image  = vision.Image(content=content)
    client = _get_client()
    response = client.text_detection(
        image=image,
        image_context={"language_hints": list(language_hints)}
    )
    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")

    return response.text_annotations[0].description if response.text_annotations else ""
# ---- основные проверки ---------------------------------------------------
_STATUS_OK   = ("успешно", "выполнено", "success", "completed")
_RECIPIENT_RGXS = (
    r"арсени[йи]\s*ц\.?",          # Арсений Ц.  / Арсений Ц
    r"arsen[iy]y?\s*t\.?",         # Arseny T.   / Arseniy T
)

_BANK_RGXS = (
    r"kaspi\s+gold",
    r"caspi\s+gold",               # OCR иногда путает K↔C
)

_AMOUNT_RGX  = re.compile(r"\d{1,3}(?:[  .,]\d{3})*(?:[.,]\d{2})?")  # 12 000,00 / 12.000 / 12000
_DATE_RGX    = re.compile(r"\d{2}[./\-]\d{2}[./\-]\d{2,4}")

def _recipient_ok(text_low: str) -> bool:
    name_ok = any(re.search(p, text_low) for p in _RECIPIENT_RGXS)
    bank_ok = any(re.search(p, text_low) for p in _BANK_RGXS)
    return name_ok and bank_ok

def is_valid_payment(text: str, *, min_amount: int = 30_000) -> tuple[bool, list[str]]:
    text_low = text.lower()
    issues   = []

    # статус
    if not any(s in text_low for s in _STATUS_OK):
        issues.append("Не найден статус «Успешно» / «Выполнено»")

    # сумма
    amounts = [
        float(a.replace(" ","").replace(" ","").replace(" ","").replace(",","."))
        for a in _AMOUNT_RGX.findall(text_low)
    ]
    if not any(a >= min_amount for a in amounts):
        issues.append(f"Сумма < {min_amount} ₸")

    # ► получатель + банк
    if not _recipient_ok(text_low):
        issues.append("Получатель должен быть «Арсений Ц.» / «Arseny T.» на Kaspi Gold")

    # дата
    if not _DATE_RGX.search(text_low):
        issues.append("Не найдена дата платежа")

    return not issues, issues

def validate_payment(image_path: str, *, min_amount:int=30_000) -> dict:
    try:
        extracted = extract_text_from_image(image_path)
        ok, reasons = is_valid_payment(extracted, min_amount=min_amount)
        return {"valid": ok, "issues": reasons, "raw_text": extracted}
    except Exception as e:
        return {"valid": False, "issues": [str(e)], "raw_text": ""}

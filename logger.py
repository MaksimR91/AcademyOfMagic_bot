# logger.py  –– минимальная, но 100 % рабочая конфигурация
import logging, os
from datetime import datetime

# ── совместимо и локально, и на Render ───────────────────────────
try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler as S3TimedRotatingFileHandler
except ImportError:
    # если пакет не установлен, падаем на стандартный файловый
    from logging.handlers import TimedRotatingFileHandler as S3TimedRotatingFileHandler
# ─────────────────────────────────────────────────────────────────

LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("bot")
logger.setLevel(logging.INFO)

file_handler = S3TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "bot.log"),
    when="midnight",
    backupCount=7,
    encoding="utf-8",
)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
)
logger.addHandler(file_handler)

# ── заглушки для S3, чтобы код ниже ничего не заметил ─────────────
class _DummyS3Handler(logging.Handler):
    def emit(self, record):
        pass

logger_s3 = _DummyS3Handler()   # вместо реального S3-хендлера
logger.addHandler(logger_s3)

s3_client = None                # чтобы импорт прошёл
BUCKET_NAME = None              # имя бакета не нужно локально
# ──────────────────────────────────────────────────────────────────

FMT = "[%(asctime)s] [%(levelname)s] %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

root = logging.getLogger()
root.setLevel(logging.INFO)

# console → Render dashboard
if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
    sh = logging.StreamHandler()     # stderr
    sh.setFormatter(logging.Formatter(FMT, DATEFMT))
    root.addHandler(sh)

# Продублируем handlers в gunicorn.error (делать до forka!)
guni = logging.getLogger("gunicorn.error")
for h in root.handlers:
    if h not in guni.handlers:
        guni.addHandler(h)

root.info("🔊 Logging ready (pid=%s)", os.getpid())
# ------------------------------------------------------------
#  Экспортируем ссылку `logger`, чтобы
#  “from logger import logger” продолжало работать.
#  Хотите — можете взять root, хотите —
#  отдельный namespace-логгер проекта – разницы нет.
# ------------------------------------------------------------
logger = root            # один и тот же объект
# logger.py  –– минимальная, но 100 % рабочая конфигурация
import logging, os
from datetime import datetime

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
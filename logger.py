import logging
from logging.handlers import TimedRotatingFileHandler
import os

# Создаем папку для логов, если её нет
if not os.path.exists("logs"):
    os.makedirs("logs")

# Формат логов
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

# Хэндлер: лог в файл, ротация по полуночи
file_handler = TimedRotatingFileHandler("logs/log", when="midnight", interval=1, backupCount=14, encoding='utf-8')
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setFormatter(formatter)

# Хэндлер: вывод в консоль
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# Создаем логгер
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # можно заменить на INFO/ERROR
logger.addHandler(file_handler)
logger.addHandler(console_handler)
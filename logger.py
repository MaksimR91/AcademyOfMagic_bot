import logging
# новый хэндлер, умеющий писать в один файл из нескольких процессов
from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
import os
import time
import boto3
from botocore.config import Config
from datetime import datetime, timedelta

# ==== НАСТРОЙКИ S3 ====
AWS_ACCESS_KEY_ID = os.getenv("YANDEX_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("YANDEX_SECRET_ACCESS_KEY")
BUCKET_NAME = "magicacademylogsars"
ENDPOINT_URL = "https://storage.yandexcloud.net"
REGION_NAME = "ru-central1"

# ==== ПАПКА ДЛЯ ЛОГОВ ====
LOG_DIR = "/tmp/logs"
os.makedirs(LOG_DIR, exist_ok=True)

# ==== S3 КЛИЕНТ ====
s3_config = Config(connect_timeout=5, read_timeout=10)
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    endpoint_url=ENDPOINT_URL,
    config=s3_config
)

# ==== ВСПОМОГАТЕЛЬНЫЙ ЛОГГЕР ====
logger_s3 = logging.getLogger("s3_logger")
logger_s3.setLevel(logging.INFO)
s3_console = logging.StreamHandler()
s3_console.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [S3] %(message)s"))
logger_s3.addHandler(s3_console)
logger_s3.propagate = False

# ==== КАСТОМНЫЙ ХЭНДЛЕР (multi‑process) ====
class S3TimedRotatingFileHandler(ConcurrentTimedRotatingFileHandler):
    def doRollover(self):
        logger_s3.info("🔄 Ротация логов (super().doRollover())")
        super().doRollover()
        time.sleep(2)

        from rollover_scheduler import schedule_s3_upload
        schedule_s3_upload()
        logger_s3.info("⏳ Загрузка лога в S3 будет выполнена через 60 секунд")

# ==== ФОРМАТ ЛОГОВ ====
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

# ==== ХЭНДЛЕРЫ (только файл) ====
file_handler = S3TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "log"),
    when="midnight",
    interval=1,
    backupCount=14,
    encoding="utf-8",
    utc=True,   # ротация ровно в 00:00 UTC
    delay=True  # файл откроется при первом emit(), экономит дескрипторы
)
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# ==== ГЛАВНЫЙ ЛОГГЕР ====
logger = logging.getLogger()
logger.setLevel(logging.INFO)
# ---- Console handler (Render dashboard) ----
#  • выводит всё ≥INFO в stderr → сразу видно в логах сервиса
#  • добавляем один раз, чтобы не было дублей при per‑process init
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    console_handler = logging.StreamHandler()          # stderr по умолчанию
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# ─── Важно: то же самое подсовываем gunicorn‑логгеру ───────────────
guni = logging.getLogger("gunicorn.error")
guni.setLevel(logging.INFO)
for h in logger.handlers:            # файл и console
    if h not in guni.handlers:
        guni.addHandler(h)
# Теперь ВСЁ, что делает logger.info(...), одновременно
# попадает и в файлы, и в консоль Render.


# ---- File handler ----
# Добавляем файловый хэндлер, если его ещё нет
if not any(isinstance(h, S3TimedRotatingFileHandler) for h in logger.handlers):
    logger.addHandler(file_handler)

# ==== FALLBACK ====
if not logger.handlers:
    logging.basicConfig(
        filename=f"/tmp/logger_{datetime.now():%Y-%m-%d}.log",
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    logger.debug("logger.py basicConfig fallback activated")

# ==== РУЧНАЯ ЗАГРУЗКА ====
def upload_to_s3_manual():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    local_path = os.path.join(LOG_DIR, f"log.{yesterday}.log")
    s3_key = f"logs/log.{yesterday}.log"

    logger_s3.info("🚀 Ручная загрузка в S3")
    if not os.path.exists(local_path):
        logger_s3.warning("❗ Лог-файл отсутствует, нечего загружать")
        return

    try:
        with open(local_path, 'r', encoding='utf-8') as f:
            content = f.read()
            logger_s3.info(f"📄 Содержимое файла перед загрузкой (ручная):\n{content}")
    except Exception as e:
        logger_s3.warning(f"❌ Не удалось прочитать файл перед ручной загрузкой: {e}")

    try:
        s3_client.upload_file(local_path, BUCKET_NAME, s3_key)
        logger_s3.info(f"✅ Успешно загружено вручную: {s3_key}")

        try:
            s3_client.head_object(Bucket=BUCKET_NAME, Key=s3_key)
            logger_s3.info("🔍 HEAD запрос (ручная): файл действительно появился в бакете")
        except s3_client.exceptions.ClientError as e:
            logger_s3.warning(f"❗ HEAD-запрос (ручная): файл не найден. Ошибка: {e}")

    except Exception as e:
        logger_s3.exception("💥 Ошибка при ручной загрузке в S3")

if __name__ == "__main__":
    logger_s3.info("main() logger.py — тест ручной загрузки")
    upload_to_s3_manual()

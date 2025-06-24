import logging
from logging.handlers import TimedRotatingFileHandler
import os
import time
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from botocore.config import Config
from datetime import datetime, timedelta

# ==== НАСТРОЙКИ S3 ====
AWS_ACCESS_KEY_ID = os.getenv("YANDEX_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("YANDEX_SECRET_ACCESS_KEY")
BUCKET_NAME = "magicacademylogsars"
ENDPOINT_URL = "https://storage.yandexcloud.net"
REGION_NAME = "ru-central1"

# ==== ПАПКА ДЛЯ ЛОГОВ ====
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("tmp", exist_ok=True)

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

# ==== КАСТОМНЫЙ ХЭНДЛЕР ====
class S3TimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self):
        super().doRollover()
        time.sleep(2)  # Подождать, пока система закроет файл

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        filename = os.path.join(LOG_DIR, f"log.{yesterday}.log")
        s3_key = f"logs/log.{yesterday}.log"

        file_exists = os.path.exists(filename)
        file_size = os.path.getsize(filename) if file_exists else 0

        logger_s3.info(f"Проверка файла: существует = {file_exists}, размер = {file_size} байт")

        if not file_exists or file_size == 0:
            logger_s3.warning("Файл не существует или пуст, загрузка в S3 пропущена")
            return

        logger_s3.info(f"Загрузка в S3: {filename} → {s3_key}")
        try:
            s3_client.upload_file(filename, BUCKET_NAME, s3_key)
            print(">>> upload_file вернулся без ошибки")
            logger_s3.info(f"✅ Успешно загружено в S3: {s3_key}")
        except (ClientError, EndpointConnectionError, ReadTimeoutError) as e:
            logger_s3.warning(f"❌ Ошибка сети/таймаут при загрузке: {e}")
        except Exception as e:
            logger_s3.exception("💥 Непредвиденная ошибка при загрузке в S3")

# ==== ФОРМАТ ЛОГОВ ====
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

# ==== ХЭНДЛЕРЫ ====
file_handler = S3TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "log"), when="midnight", interval=1, backupCount=14, encoding='utf-8'
)
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# ==== ГЛАВНЫЙ ЛОГГЕР ====
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ==== FALLBACK ====
if not logger.hasHandlers():
    logging.basicConfig(
        filename=f"tmp/logger_{datetime.now():%Y-%m-%d}.log",
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
        s3_client.upload_file(local_path, BUCKET_NAME, s3_key)
        print(">>> upload_file вернулся без ошибки (ручная загрузка)")
        logger_s3.info(f"✅ Успешно загружено вручную: {s3_key}")
    except Exception as e:
        logger_s3.exception("💥 Ошибка при ручной загрузке в S3")

if __name__ == "__main__":
    logger_s3.info("main() logger.py — тест ручной загрузки")
    upload_to_s3_manual()

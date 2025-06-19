import logging
from logging.handlers import TimedRotatingFileHandler
import os
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from botocore.config import Config
from datetime import datetime

# ==== НАСТРОЙКИ S3 ====
AWS_ACCESS_KEY_ID = os.getenv("YANDEX_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("YANDEX_SECRET_ACCESS_KEY")
BUCKET_NAME = "magicacademylogsars"
ENDPOINT_URL = "https://storage.yandexcloud.net"
REGION_NAME = "ru-central1"

# ==== ПАПКА ДЛЯ ЛОГОВ ====
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs("tmp", exist_ok=True)  # на случай fallback-логгера

# ==== S3 КЛИЕНТ С ТАЙМАУТОМ ====
s3_config = Config(connect_timeout=5, read_timeout=10)
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    endpoint_url=ENDPOINT_URL,
    config=s3_config
)

# ==== КАСТОМНЫЙ ХЭНДЛЕР ====
class S3TimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self):
        super().doRollover()
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = os.path.join(LOG_DIR, f"log.{timestamp}.log")
        s3_key = f"logs/{os.path.basename(filename)}"

        logging.debug(f"[DEBUG] Uploading to S3 → File: {filename} → S3 Key: {s3_key}")
        try:
            s3_client.upload_file(filename, BUCKET_NAME, s3_key)
            logging.debug(f"[S3] Uploaded: {s3_key}")
        except (ClientError, EndpointConnectionError, ReadTimeoutError) as e:
            logging.warning(f"[S3 ERROR] Upload failed due to network/timeout: {e}")
        except Exception as e:
            logging.warning(f"[S3 ERROR] Unexpected error: {e}")

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

# ==== ИНИЦИАЛИЗАЦИЯ ЛОГГЕРА ====
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ==== РЕЗЕРВНЫЙ BASICCONFIG, ЕСЛИ ИМПОРТИРУЕТСЯ ====
if not logger.hasHandlers():
    logging.basicConfig(
        filename=f"tmp/logger_{datetime.now():%Y-%m-%d}.log",
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    logging.debug("📦 logger.py basicConfig fallback activated")

# ==== ПРИНУДИТЕЛЬНАЯ ЗАГРУЗКА ====
def upload_to_s3_manual():
    today = datetime.now().strftime("%Y-%m-%d")
    local_path = os.path.join(LOG_DIR, f"log.{today}.log")
    s3_key = f"logs/log.{today}.log"

    logging.debug("🚀 Начинаем ручную загрузку в S3")
    if not os.path.exists(local_path):
        logging.warning("❗ Лог-файл отсутствует, нечего загружать")
        return

    try:
        s3_client.upload_file(local_path, BUCKET_NAME, s3_key)
        logging.debug(f"✅ Успешно загружено в S3 как {s3_key}")
    except Exception as e:
        logging.exception("💥 Ошибка загрузки в S3")

if __name__ == "__main__":
    logging.debug("🛠 main() в logger.py выполняется")
    upload_to_s3_manual()

import logging
from logging.handlers import TimedRotatingFileHandler
import os
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

# ==== НАСТРОЙКИ S3 ====
AWS_ACCESS_KEY_ID = os.getenv("YANDEX_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("YANDEX_SECRET_ACCESS_KEY")
BUCKET_NAME = "academyofmagicbotlogs"
ENDPOINT_URL = "https://storage.yandexcloud.net"
# REGION_NAME = "kz1"  # Закомментировано, т.к. может ломать подпись

# ==== ОТЛАДОЧНАЯ ИНФОРМАЦИЯ ====
print(f"[DEBUG] AWS_ACCESS_KEY_ID: {AWS_ACCESS_KEY_ID[:4]}...")  # первые символы
print(f"[DEBUG] AWS_SECRET_ACCESS_KEY: {AWS_SECRET_ACCESS_KEY[:4]}...")  # первые символы
print(f"[DEBUG] BUCKET_NAME: {BUCKET_NAME}")
print(f"[DEBUG] ENDPOINT_URL: {ENDPOINT_URL}")
# print(f"[DEBUG] REGION_NAME: {REGION_NAME}")

# ==== ПАПКА ДЛЯ ЛОГОВ ====
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# ==== S3 КЛИЕНТ ====
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    endpoint_url=ENDPOINT_URL,
    # region_name=REGION_NAME  # убрано
)

# ==== КАСТОМНЫЙ ХЭНДЛЕР ====
class S3TimedRotatingFileHandler(TimedRotatingFileHandler):
    def doRollover(self):
        super().doRollover()
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = os.path.join(LOG_DIR, f"log.{timestamp}.log")
        s3_key = f"logs/{os.path.basename(filename)}"

        print(f"[DEBUG] Uploading to S3 → File: {filename} → S3 Key: {s3_key}")
        try:
            # Можно заменить на .put_object() ниже, если будет нужно
            s3_client.upload_file(filename, BUCKET_NAME, s3_key)
            print(f"[S3] Uploaded: {s3_key}")
        except ClientError as e:
            print(f"[S3 ERROR] ClientError: {e}")
        except Exception as e:
            print(f"[S3 ERROR] Unexpected error: {e}")

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

# ==== ЛОГГЕР ====
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
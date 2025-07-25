import os
import json
import boto3
from datetime import datetime, timedelta
from botocore.config import Config
from botocore.exceptions import ClientError

# ==== Настройки доступа к Яндекс Object Storage ====
AWS_ACCESS_KEY_ID = os.getenv("YANDEX_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("YANDEX_SECRET_ACCESS_KEY")
ENDPOINT_URL = "https://storage.yandexcloud.net"
REGION_NAME = "ru-central1"

# ==== Конфигурация клиента ====
s3_config = Config(connect_timeout=5, read_timeout=10)
s3_client = boto3.client(
    "s3",
    region_name=REGION_NAME,
    endpoint_url=ENDPOINT_URL,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    config=s3_config
)

# ==== Настройки расписания ====
BUCKET_NAME = "magicacademylogsars"
SCHEDULE_KEY = "Schedule/arseniy_schedule.json"

# ==== Загрузка расписания из S3 ====
def load_schedule_from_s3():
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=SCHEDULE_KEY)
        content = response['Body'].read().decode('utf-8')
        return json.loads(content)
    except ClientError as e:
        if e.response['Error']['Code'] == "NoSuchKey":
            print("Schedule file not found in S3, initializing empty list.")
            return []
        else:
            raise e

# ==== Проверка доступности времени ====
def check_date_availability(date_str, time_str, schedule_list):
    try:
        request_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "invalid_format"

    now = datetime.now()
    tomorrow = now + timedelta(days=1)

    if request_datetime.date() in (now.date(), tomorrow.date()):
        return "need_handover"

    for entry in schedule_list:
        try:
            entry_datetime = datetime.strptime(f"{entry['date']} {entry['time']}", "%Y-%m-%d %H:%M")
        except Exception:
            continue

        if entry_datetime.date() == request_datetime.date():
            diff_hours = abs((entry_datetime - request_datetime).total_seconds()) / 3600
            if diff_hours <= 3:
                return "occupied"

    return "available"

# ==== Сохранение расписания обратно в S3 ====
def save_schedule_to_s3(schedule_list: list[dict]):
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=SCHEDULE_KEY,
        Body=json.dumps(schedule_list, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

# ==== Резервирование слота (добавляет, если свободно) ====
def reserve_slot(date_str: str, time_str: str) -> bool:
    """
    Возвращает True, если слот успешно добавлен,
    False – если такой слот уже есть (или ошибка S3).
    """
    sched = load_schedule_from_s3()
    for e in sched:
        if e["date"] == date_str and e["time"] == time_str:
            return False          # уже забронировано

    sched.append({"date": date_str, "time": time_str})
    try:
        save_schedule_to_s3(sched)
        return True
    except Exception as e:
        print(f"[schedule] reserve_slot S3 error: {e}")
        return False


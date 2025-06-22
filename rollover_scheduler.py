from apscheduler.schedulers.background import BackgroundScheduler
from logger import logger, S3TimedRotatingFileHandler

def manual_rollover():
    for handler in logger.handlers:
        if isinstance(handler, S3TimedRotatingFileHandler):
            logger.info("🌀 Ручной вызов doRollover()")
            handler.doRollover()
            break
    else:
        logger.warning("❗ Хендлер S3TimedRotatingFileHandler не найден")

def start_rollover_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(manual_rollover, "cron", hour=0, minute=5)
    scheduler.start()
    logger.info("🕒 Планировщик выгрузки логов в S3 запущен")

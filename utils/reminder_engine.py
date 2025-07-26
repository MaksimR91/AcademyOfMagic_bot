import os, time, logging, uuid
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from state.state import get_state          # тот же dict-API
log = logging.getLogger(__name__)

# ---------- APScheduler с jobstore в Supabase -------------------
pg_url = os.getenv("SUPABASE_URL").replace("https://", "postgresql+psycopg2://")
pg_url = pg_url.replace(".supabase.co", ".supabase.co/postgres")          # URI вида postgresql://user:pass@host:5432/postgres
jobstores = {"default": SQLAlchemyJobStore(url=pg_url)}
sched = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
sched.start()
log.info("⏰ reminder_engine started")

# ---------- универсальный планировщик ---------------------------
def plan(user_id: str, func_path: str, delay_sec: int) -> None:
    """
    Зарегистрировать одноразовую задачу.
    • func_path  – строкой "blocks.block02.send_first_reminder_if_silent"
    • delay_sec  – через сколько секунд вызвать
    При повторном вызове с тем же ключом старая задача перезаписывается.
    """
    job_id = f"{user_id}:{func_path}"
    run_at = time.time() + delay_sec

    # при рестарте, если задача уже прошла – не ставим снова
    if run_at <= time.time():
        return

    def _runner():
        # Если пользователя уже нет в нужном стадии – тихо выходим
        mod_name, func_name = func_path.rsplit(".", 1)
        mod = __import__(mod_name, fromlist=[func_name])
        func = getattr(mod, func_name)
        try:
            func(user_id, _send_func_factory(user_id))
        except TypeError:
            # блоки, где сигнатура (user_id) без send_func
            func(user_id)
        except Exception as e:
            log.error(f"[reminder_engine] job {job_id} error: {e}")

    # remove & add (idempotent)
    try:
        sched.remove_job(job_id)
    except Exception:
        pass
    sched.add_job(
        _runner,
        "date",
        id=job_id,
        run_date=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(run_at)),
        misfire_grace_time=300,
    )
    log.info(f"[reminder_engine] scheduled {job_id} in {delay_sec//60} min")

# ---------- лёгкая обёртка для send_text ------------------------
from utils.whatsapp_senders import send_text
def _send_func_factory(user_id):
    def _send(body):
        st = get_state(user_id) or {}
        to = st.get("normalized_number", user_id)
        send_text(to, body)
    return _send
"""Celery 实例 + beat_schedule（蓝图 00 落位：08/10/12）。

worker/beat 部署归 12；本文件定义任务与调度，测试直接调 async 核心函数。
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "assistant",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.timezone = settings.timezone

celery_app.conf.beat_schedule = {
    "scan-reminders-every-30s": {
        "task": "app.tasks.notification_tasks.scan_due_reminders",
        "schedule": 30.0,
    },
    "scan-overdue-todos-daily": {
        "task": "app.tasks.notification_tasks.scan_overdue_todos",
        "schedule": crontab(hour=9, minute=0),
    },
    "scan-automation-rules-every-minute": {
        "task": "app.tasks.automation_tasks.scan_automation_rules",
        "schedule": 60.0,
    },
    # 12：软删物理清除 / 审计保留 / 画像重构（每日）
    "purge-soft-deleted-daily": {
        "task": "app.tasks.cleanup.purge_soft_deleted",
        "schedule": crontab(hour=3, minute=17),
    },
    "purge-audit-logs-daily": {
        "task": "app.tasks.cleanup.purge_audit_logs",
        "schedule": crontab(hour=3, minute=43),
    },
    "refresh-profiles-daily": {
        "task": "app.tasks.memory_tasks.refresh_profiles",
        "schedule": crontab(hour=4, minute=23),
        "kwargs": {"force": True},
    },
}

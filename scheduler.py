"""
Scheduler de Nexus — gère les tâches planifiées et les rapports automatiques.
Basé sur APScheduler.
"""
import logging
import uuid
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class NexusScheduler:
    def __init__(
        self,
        send_task_callback: Callable[[str, str], None],
        request_report_callback: Callable[[str], None],
    ):
        self._scheduler = BackgroundScheduler(timezone="Europe/Paris")
        self._send_task = send_task_callback
        self._request_report = request_report_callback
        self._jobs: dict[str, dict] = {}  # job_id → metadata

    def start(self, config: dict):
        """Démarre le scheduler avec la config initiale."""
        self._scheduler.start()

        # Tâches planifiées initiales depuis config
        for job in config.get("scheduled_tasks", []):
            try:
                self.add_job(
                    frequency=job["frequency"],
                    agent_id=job["agent"],
                    task=job["task"],
                    job_id=job.get("id"),
                )
            except Exception as e:
                logger.error(f"[Scheduler] Erreur chargement tâche {job}: {e}")

        # Rapports automatiques
        for report in config.get("daily_reports", []):
            try:
                self._add_report_job(
                    agent_id=report["agent"],
                    time_str=report["time"],  # "08:00"
                )
            except Exception as e:
                logger.error(f"[Scheduler] Erreur rapport {report}: {e}")

        logger.info(f"[Scheduler] {len(self._jobs)} job(s) chargé(s)")

    def add_job(self, frequency: str, agent_id: str, task: str,
                job_id: Optional[str] = None) -> str:
        """
        Ajoute une tâche planifiée.

        Formats de fréquence supportés :
          daily HH:MM         → tous les jours à HH:MM
          every Xh            → toutes les X heures
          every Xmin          → toutes les X minutes
          weekly <day> HH:MM  → une fois par semaine (lun/mar/...)
        """
        job_id = job_id or str(uuid.uuid4())[:8]
        trigger = self._parse_frequency(frequency)

        self._scheduler.add_job(
            func=self._send_task,
            trigger=trigger,
            args=[agent_id, task],
            id=job_id,
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "id": job_id,
            "frequency": frequency,
            "agent": agent_id,
            "task": task,
        }
        logger.info(f"[Scheduler] Job {job_id} : [{frequency}] @{agent_id} → {task}")
        return job_id

    def _add_report_job(self, agent_id: str, time_str: str) -> str:
        """Planifie une demande de rapport quotidien."""
        job_id = f"report_{agent_id}"
        hour, minute = map(int, time_str.split(":"))
        self._scheduler.add_job(
            func=self._request_report,
            trigger=CronTrigger(hour=hour, minute=minute),
            args=[agent_id],
            id=job_id,
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "id": job_id,
            "frequency": f"daily {time_str}",
            "agent": agent_id,
            "task": "[rapport quotidien]",
        }
        return job_id

    def cancel_job(self, job_id: str) -> bool:
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            return True
        except Exception:
            return False

    def list_jobs(self) -> str:
        if not self._jobs:
            return "Aucune tâche planifiée."
        lines = ["── Tâches planifiées ────────────────"]
        for j in self._jobs.values():
            lines.append(f"  [{j['id']}] {j['frequency']} → @{j['agent']} : {j['task']}")
        return "\n".join(lines)

    def _parse_frequency(self, frequency: str):
        """Parse une fréquence en trigger APScheduler."""
        parts = frequency.strip().split()

        # daily HH:MM
        if parts[0] == "daily" and len(parts) >= 2:
            hour, minute = map(int, parts[1].split(":"))
            return CronTrigger(hour=hour, minute=minute)

        # weekly lun HH:MM
        if parts[0] == "weekly" and len(parts) >= 3:
            day_map = {
                "lun": "mon", "mar": "tue", "mer": "wed",
                "jeu": "thu", "ven": "fri", "sam": "sat", "dim": "sun",
            }
            day = day_map.get(parts[1].lower(), parts[1])
            hour, minute = map(int, parts[2].split(":"))
            return CronTrigger(day_of_week=day, hour=hour, minute=minute)

        # every Xh
        if parts[0] == "every" and len(parts) >= 2:
            val = parts[1]
            if val.endswith("h"):
                return IntervalTrigger(hours=int(val[:-1]))
            if val.endswith("min"):
                return IntervalTrigger(minutes=int(val[:-3]))
            if val.endswith("m"):
                return IntervalTrigger(minutes=int(val[:-1]))

        raise ValueError(f"Format de fréquence non reconnu : '{frequency}'")

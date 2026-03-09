"""
Gestion des rapports quotidiens agrégés de tous les agents.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class DailyReportManager:
    def __init__(self):
        # {agent_id: {"received_at": ..., "content": ...}}
        self._reports: dict[str, dict] = {}

    def add_report(self, agent_id: str, content: str):
        self._reports[agent_id] = {
            "received_at": datetime.now(timezone.utc).isoformat(),
            "content": content,
        }
        logger.info(f"[DailyReport] Rapport reçu de {agent_id}")

    def get_report(self, agent_id: Optional[str] = None) -> str:
        if agent_id:
            r = self._reports.get(agent_id)
            if not r:
                return f"Aucun rapport reçu de {agent_id} aujourd'hui."
            return f"── Rapport {agent_id} ({r['received_at'][:16]}) ──\n{r['content']}"

        if not self._reports:
            return "Aucun rapport reçu aujourd'hui."

        lines = [f"── Rapport quotidien ({datetime.now().strftime('%d/%m/%Y')}) ──"]
        for aid, r in self._reports.items():
            lines.append(f"\n[{aid}] reçu à {r['received_at'][11:16]}")
            lines.append(r["content"])
        return "\n".join(lines)

    def clear(self):
        self._reports.clear()

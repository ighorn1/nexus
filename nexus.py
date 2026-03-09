#!/usr/bin/env python3
"""
Nexus — Orchestrateur principal du système multi-agents.

Reçoit les instructions via XMPP (ou CLI), les traite via LLM,
délègue aux agents spécialisés via MQTT, et renvoie les résultats.
"""
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


from agents_core import BaseAgent, AgentContext, Message, MessageType
from agents_core.command_parser import ParsedCommand, CommandType, help_text

from scheduler import NexusScheduler
from daily_report import DailyReportManager

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent / "config"


class Nexus(BaseAgent):
    AGENT_TYPE = "nexus"
    DESCRIPTION = "Orchestrateur principal — reçoit les instructions et coordonne les agents spécialisés"
    DEFAULT_CONFIG_PATH = str(CONFIG_DIR / "config.json")

    def __init__(self):
        super().__init__()

        # Rapport quotidien agrégé
        self.report_manager = DailyReportManager()

        # Scheduler (tâches planifiées, rapports automatiques)
        self.scheduler = NexusScheduler(
            send_task_callback=self._schedule_send_task,
            request_report_callback=self._request_daily_report,
        )

        # Résultats en attente de réponse XMPP
        # {correlation_id: sender_jid}
        self._pending_replies: dict[str, str] = {}
        self._pending_lock = threading.Lock()

        # Mode veille global
        self._sleep_mode = False

    # ──────────────────────────────────────────────
    # Démarrage
    # ──────────────────────────────────────────────

    def get_skills_dir(self) -> str:
        return str(Path(__file__).parent / "skills")

    def on_start(self):
        self.scheduler.start(self.config.get("schedules", {}))
        logger.info("Nexus prêt — scheduler démarré")

    def setup_extra_subscriptions(self):
        """Souscriptions MQTT supplémentaires de Nexus."""
        # Résultats des agents (réponses à nos délégations)
        self.mqtt.subscribe("agents/nexus/inbox", self._on_agent_result)
        # Rapports quotidiens des agents
        self.mqtt.subscribe("agents/daily_report", self._on_daily_report)

    # ──────────────────────────────────────────────
    # Réception des résultats agents (MQTT)
    # ──────────────────────────────────────────────

    def _on_agent_result(self, msg: Message | str, topic: str):
        """Un agent a renvoyé un résultat → transmettre à l'utilisateur via XMPP."""
        if isinstance(msg, str):
            self._forward_to_user(msg, sender="unknown")
            return

        if msg.type == MessageType.ALERT:
            severity = msg.metadata.get("severity", "warning")
            text = f"⚠ Alerte [{severity}] de {msg.sender} :\n{msg.payload}"
            self._forward_to_user(text, sender=msg.sender)
            return

        if msg.type == MessageType.RESULT:
            result_text = (
                f"Résultat de {msg.sender} :\n{msg.payload}"
            )
            # Retrouver le JID de l'utilisateur qui a initié la demande
            with self._pending_lock:
                reply_jid = self._pending_replies.pop(msg.correlation_id, None)
            self._forward_to_user(result_text, sender=msg.sender, reply_jid=reply_jid)
            return

        # Message direct d'un agent
        if msg.type == MessageType.DIRECT:
            self._forward_to_user(
                f"Message de {msg.sender} :\n{msg.payload}",
                sender=msg.sender,
            )

    def _on_daily_report(self, msg: Message | str, topic: str):
        """Réception d'un rapport quotidien d'un agent."""
        if isinstance(msg, Message):
            self.report_manager.add_report(msg.sender, msg.payload)
            logger.info(f"Rapport reçu de {msg.sender}")

    def _forward_to_user(self, text: str, sender: str = "", reply_jid: Optional[str] = None):
        """
        Envoie un message à l'utilisateur XMPP.
        - Si reply_jid : répond à l'expéditeur spécifique (réponse async)
        - Sinon : envoie à tous les admins configurés
        - Toujours dans le groupe MUC si configuré
        """
        if self.xmpp:
            if reply_jid:
                self.xmpp.send_message(reply_jid, text)
            else:
                self.xmpp.send_to_all_admins(text)
            if self.xmpp.muc_room:
                self.xmpp.send_to_group(text)

    # ──────────────────────────────────────────────
    # Traitement des messages XMPP
    # ──────────────────────────────────────────────

    def _on_xmpp_message(self, sender: str, body: str, is_muc: bool = False):
        """Override — Nexus gère les commandes et délègue au LLM."""
        from agents_core.command_parser import parse as parse_command

        logger.info(f"[XMPP] Message de {sender}: {body[:80]!r}")

        if self._sleep_mode and not body.strip().startswith("/"):
            return  # En veille, ignore les messages sauf commandes système

        cmd = parse_command(body)
        context = AgentContext(self)

        # ── Commandes système /xxx
        if cmd.type == CommandType.SYSTEM:
            reply = self._handle_system_command(f"/{cmd.command} {cmd.args}", raw_cmd=cmd)
            if reply and self.xmpp:
                self.xmpp.send_message(sender, reply)
            return

        # ── Message direct @agent
        if cmd.type == CommandType.DIRECT:
            reply = self._delegate_direct(cmd, sender)
            if self.xmpp:
                self.xmpp.send_message(sender, reply)
            return

        # ── Broadcast @all
        if cmd.type == CommandType.BROADCAST:
            self.mqtt.broadcast(cmd.args or "")
            if self.xmpp:
                self.xmpp.send_message(sender, "Broadcast envoyé à tous les agents.")
            return

        # ── Mode naturel → LLM → skills
        extra_ctx = self.registry.summary_for_llm(self._online_agents)
        response = self._llm_loop(body, context, extra_ctx)

        # Enregistre le JID pour le retour asynchrone éventuel
        # (si le LLM a délégué à un agent via DELEGATE skill)
        if self.xmpp:
            self.xmpp.send_message(sender, response)

    def _delegate_direct(self, cmd: ParsedCommand, sender_jid: str) -> str:
        """Route @agent message directement via MQTT."""
        target = cmd.target
        message = cmd.args or ""

        caps = self.registry.get(target)
        if caps is None:
            known = [a.agent_id for a in self.registry.all_agents()]
            return f"Agent '{target}' inconnu.\nAgents connus : {', '.join(known) or 'aucun'}"

        with self._online_lock:
            online = target in self._online_agents

        if not online:
            return f"Agent '{target}' est hors ligne."

        sent = self.mqtt.send_to(
            recipient_id=target,
            payload=message,
            reply_to=self.mqtt.topic_inbox(),
        )

        # Mémoriser le JID pour renvoyer la réponse
        with self._pending_lock:
            self._pending_replies[sent.correlation_id] = sender_jid

        return f"Message envoyé à {target}. Attente de la réponse..."

    # ──────────────────────────────────────────────
    # Commandes système étendues
    # ──────────────────────────────────────────────

    def handle_custom_command(self, cmd: str, args: str,
                               source_msg: Optional[Message] = None) -> Optional[str]:
        """Commandes spécifiques à Nexus."""

        if cmd == "sleep":
            self._sleep_mode = True
            return "Nexus en veille. Tape /wake pour reprendre."

        if cmd == "wake":
            self._sleep_mode = False
            return "Nexus actif."

        if cmd == "agents":
            with self._online_lock:
                online = list(self._online_agents)
            all_caps = self.registry.all_agents()
            lines = ["── Agents ──────────────────"]
            for a in all_caps:
                status = "🟢 EN LIGNE" if a.agent_id in online else "🔴 hors ligne"
                skills = ", ".join(s["name"] for s in a.skills[:5])
                lines.append(f"  {a.agent_id} [{a.agent_type}] {status}")
                lines.append(f"    {a.description}")
                lines.append(f"    Skills: {skills or 'aucun'}")
            return "\n".join(lines) if len(lines) > 1 else "Aucun agent connu."

        if cmd == "report":
            target = args.strip() or None
            return self.report_manager.get_report(target)

        if cmd == "schedule":
            return self._handle_schedule_command(args)

        if cmd == "schedules":
            return self.scheduler.list_jobs()

        if cmd == "update":
            # @agent update → git pull + restart
            target = args.strip()
            if not target:
                return "Usage : /update <agent_id>"
            self.mqtt.send_to(target, "/update", msg_type=MessageType.COMMAND)
            return f"Mise à jour demandée à {target}."

        if cmd == "admins":
            return self._handle_admins_command(args)

        if cmd == "help":
            return self._nexus_help()

        return f"Commande inconnue : /{cmd}. Tape /help."

    def _handle_admins_command(self, args: str) -> str:
        """
        /admins          → liste les admins autorisés
        /admins add <jid>    → ajoute un admin
        /admins remove <jid> → retire un admin
        """
        if not self.xmpp:
            return "XMPP non configuré."

        parts = args.strip().split(None, 1)
        sub   = parts[0].lower() if parts else "list"
        jid   = parts[1].strip() if len(parts) > 1 else ""

        # Auto-complète le domaine si pas de @
        xmpp_domain = self.config.get("xmpp", {}).get("jid", "@").split("@")[1]
        if jid and "@" not in jid:
            jid = f"{jid}@{xmpp_domain}"

        if sub in ("list", ""):
            admins = sorted(self.xmpp.admin_jids)
            return "Admins autorisés :\n" + "\n".join(f"  • {j}" for j in admins) \
                if admins else "Aucun admin configuré (accès ouvert)."

        if sub == "add":
            if not jid:
                return "Usage : /admins add <jid>"
            self.xmpp.add_admin(jid)
            return f"Admin ajouté : {jid}"

        if sub == "remove":
            if not jid:
                return "Usage : /admins remove <jid>"
            self.xmpp.remove_admin(jid)
            return f"Admin retiré : {jid}"

        return "Usage : /admins | /admins add <jid> | /admins remove <jid>"

    def _handle_schedule_command(self, args: str) -> str:
        """
        /schedule <fréquence> @<agent> <tâche>
        Exemples :
          /schedule daily 03:00 @debian apt upgrade -y
          /schedule every 6h @ansible playbook site.yml
          /schedule cancel <job_id>
        """
        args = args.strip()
        if not args:
            return "Usage : /schedule <fréquence> @<agent> <tâche>\nOu : /schedule cancel <job_id>"

        if args.startswith("cancel "):
            job_id = args.split(" ", 1)[1].strip()
            ok = self.scheduler.cancel_job(job_id)
            return f"Tâche {job_id} annulée." if ok else f"Tâche {job_id} introuvable."

        # Parse : "daily 03:00 @debian apt upgrade"
        # ou     : "every 6h @ansible playbook site.yml"
        try:
            parts = args.split()
            # Trouver @agent
            agent_idx = next(i for i, p in enumerate(parts) if p.startswith("@"))
            freq_parts = parts[:agent_idx]
            agent_id = parts[agent_idx][1:]  # Enlève le @
            task = " ".join(parts[agent_idx + 1:])

            job_id = self.scheduler.add_job(
                frequency=" ".join(freq_parts),
                agent_id=agent_id,
                task=task,
            )
            return f"Tâche planifiée (id={job_id}) : [{' '.join(freq_parts)}] @{agent_id} → {task}"
        except (StopIteration, IndexError, ValueError) as e:
            return f"Format invalide : {e}\nUsage : /schedule daily 03:00 @agent tâche"

    def _nexus_help(self) -> str:
        base = help_text()
        nexus_extra = """
── Commandes Nexus ─────────────────
  /agents                   — Liste et statut des agents
  /sleep                    — Mettre Nexus en veille
  /wake                     — Réveiller Nexus
  /report [agent]           — Rapport quotidien
  /schedule <freq> @a tâche — Planifier une tâche
  /schedules                — Voir les tâches planifiées
  /update <agent>           — Mettre à jour un agent (git pull)
  /admins                   — Lister les utilisateurs autorisés
  /admins add <jid>         — Autoriser un nouvel utilisateur
  /admins remove <jid>      — Retirer un utilisateur
  /pause [agent]            — Mettre en pause
  /resume [agent]           — Reprendre
  /reset                    — Effacer l'historique LLM
  /status                   — Statut de Nexus

Mode @agent :
  @debian-prod apt update   — Commande directe
  @all status               — Broadcast à tous
"""
        return base + nexus_extra

    # ──────────────────────────────────────────────
    # Scheduler callbacks
    # ──────────────────────────────────────────────

    def _schedule_send_task(self, agent_id: str, task: str):
        """Callback du scheduler pour envoyer une tâche planifiée."""
        with self._online_lock:
            online = agent_id in self._online_agents
        if not online:
            logger.warning(f"[Scheduler] Agent {agent_id} hors ligne, tâche ignorée : {task}")
            return
        self.mqtt.send_to(agent_id, task)
        logger.info(f"[Scheduler] Tâche envoyée à {agent_id} : {task}")

    def _request_daily_report(self, agent_id: str):
        """Demande un rapport quotidien à un agent."""
        self.mqtt.send_to(agent_id, "/report", msg_type=MessageType.COMMAND)

    # ──────────────────────────────────────────────
    # Broadcast handler
    # ──────────────────────────────────────────────

    def on_xmpp_connected(self):
        """Au démarrage XMPP : envoie le récap des agents connus dans le MUC."""
        import time as _time
        _time.sleep(2)  # Laisser le MUC join et les agents publier
        with self._online_lock:
            online = set(self._online_agents)
        all_caps = self.registry.all_agents()
        lines = ["── Agents au démarrage ──"]
        for caps in sorted(all_caps, key=lambda c: c.agent_id):
            if caps.agent_id == self.agent_id:
                continue
            icon = "🟢" if caps.agent_id in online else "🔴"
            label = "en ligne" if caps.agent_id in online else "hors ligne"
            lines.append(f"  {icon} {caps.agent_id} — {label}")
        if len(lines) > 1 and self.xmpp:
            self.xmpp.send_to_group("\n".join(lines))

    def on_agent_status_change(self, agent_id: str, status: str):
        """Notifie le MUC et les admins quand un agent change de statut."""
        icon = "🟢" if status == "online" else "🔴"
        label = "en ligne" if status == "online" else "hors ligne"
        text = f"{icon} {agent_id} est {label}."
        logger.info(f"[Nexus] Statut agent : {text}")
        if self.xmpp:
            if self.xmpp.muc_room:
                self.xmpp.send_to_group(text)
            self.xmpp.send_to_all_admins(text)

    def on_broadcast(self, msg: Message):
        """Nexus reçoit les broadcasts — les transmet à l'admin si pertinent."""
        if msg.type == MessageType.ALERT:
            self._forward_to_user(
                f"⚠ Alerte broadcast de {msg.sender} :\n{msg.payload}"
            )


if __name__ == "__main__":
    Nexus().run()

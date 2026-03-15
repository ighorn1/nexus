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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


from agents_core import BaseAgent, AgentContext, Message, MessageType
from agents_core.command_parser import ParsedCommand, CommandType, help_text
from agents_core.llm_coordinator import LLMCoordinator

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
            send_script_callback=self._schedule_send_script,
        )

        # Résultats en attente de réponse XMPP
        # {correlation_id: sender_jid}
        self._pending_replies: dict[str, str] = {}
        self._pending_lock = threading.Lock()

        # Mode veille global
        self._sleep_mode = False

        # Coordinateur LLM — initialisé dans on_start() après connexion MQTT
        self._llm_coordinator: Optional[LLMCoordinator] = None

    # ──────────────────────────────────────────────
    # Démarrage
    # ──────────────────────────────────────────────

    def get_skills_dir(self) -> str:
        return str(Path(__file__).parent / "skills")

    def on_start(self):
        self.scheduler.start(self.config.get("schedules", {}))

        # Démarrage du coordinateur LLM
        coord_cfg = self.config.get("llm_coordinator", {})
        max_concurrent = coord_cfg.get("max_concurrent", 1)
        self._llm_coordinator = LLMCoordinator(self.mqtt, max_concurrent=max_concurrent)
        self._llm_coordinator.setup()

        logger.info("Nexus prêt — scheduler + coordinateur LLM démarrés")

    # ──────────────────────────────────────────────
    # Override slots LLM (Nexus passe par le coordinateur local, pas MQTT)
    # ──────────────────────────────────────────────

    def _llm_slot_acquire(self) -> Optional[str]:
        """Nexus acquiert un slot via le coordinateur local (sans MQTT)."""
        if self._llm_coordinator:
            granted = self._llm_coordinator.local_acquire(timeout=120)
            if not granted:
                logger.warning("[Nexus] Timeout slot LLM — appel direct")
            return "__local__" if granted else None
        return None

    def _llm_slot_release(self, slot_id: Optional[str]):
        """Nexus libère son slot."""
        if slot_id == "__local__" and self._llm_coordinator:
            self._llm_coordinator.local_release()

    def setup_extra_subscriptions(self):
        """Souscriptions MQTT supplémentaires de Nexus."""
        # Résultats des agents (réponses à nos délégations)
        self.mqtt.subscribe("agents/nexus/inbox", self._on_agent_result)
        # Rapports quotidiens des agents
        self.mqtt.subscribe("agents/daily_report", self._on_daily_report)
        # Notifications d'exécution de scripts
        self.mqtt.subscribe("agents/scripts/execution", self._on_script_execution)

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
                self._xmpp_reply(sender, reply, is_muc)
            return

        # ── Message direct @agent
        if cmd.type == CommandType.DIRECT:
            reply = self._delegate_direct(cmd, sender)
            if self.xmpp:
                self._xmpp_reply(sender, reply, is_muc)
            return

        # ── Broadcast @all
        if cmd.type == CommandType.BROADCAST:
            self.mqtt.broadcast(cmd.args or "")
            if self.xmpp:
                self._xmpp_reply(sender, "Broadcast envoyé à tous les agents.", is_muc)
            return

        # ── Mode naturel → LLM → skills (un seul appel à la fois)
        if not self._llm_lock.acquire(blocking=False):
            self._xmpp_reply(sender, "⏳ Je traite déjà une demande, attends un instant.", is_muc)
            return
        try:
            extra_ctx = self.registry.summary_for_llm(self._online_agents)
            response = self._llm_loop(body, context, extra_ctx)
            if self.xmpp:
                self._xmpp_reply(sender, response, is_muc)
        finally:
            self._llm_lock.release()

    def _xmpp_reply(self, sender: str, body: str, is_muc: bool):
        """Répond dans le bon canal : MUC si message vient du MUC, direct sinon."""
        if is_muc:
            self.xmpp.send_to_group(body)
        else:
            self.xmpp.send_message(sender, body)

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

        if cmd == "script":
            return self._handle_script_nexus_command(args)

        if cmd == "queue":
            return self._handle_queue_command(args)

        if cmd == "update":
            target = args.strip()
            if not target:
                return "Usage : /update <agent_id>  (ou /update all)"

            # Mise à jour de tous les agents connus
            if target == "all":
                targets = [a.agent_id for a in self.registry.all_agents()
                           if a.agent_id != self.agent_id]
                for t in targets:
                    self.mqtt.send_to(t, "/update", msg_type=MessageType.COMMAND)
                # Se met à jour lui-même en dernier
                threading.Thread(
                    target=lambda: (time.sleep(1), self._do_self_update()),
                    daemon=True,
                ).start()
                return f"Mise à jour demandée à : {', '.join(targets)} + nexus."

            # Mise à jour de nexus lui-même
            if target == self.agent_id or target == "nexus":
                return self._do_self_update()

            # Mise à jour d'un agent distant : envoie la commande et attend la réponse
            import uuid
            corr_id   = str(uuid.uuid4())[:8]
            result_topic = f"agents/results/{corr_id}"
            reply_box = []
            reply_evt = threading.Event()

            def _on_result(msg, topic):
                body = msg.payload if isinstance(msg, Message) else str(msg)
                reply_box.append(body)
                reply_evt.set()

            self.mqtt.subscribe(result_topic, _on_result)
            try:
                self.mqtt.send_to(
                    target, "/update",
                    msg_type=MessageType.COMMAND,
                    correlation_id=corr_id,
                    reply_to=result_topic,
                )
                # Attend la réponse 30s (l'agent peut être lent à puller)
                got = reply_evt.wait(timeout=30)
            finally:
                self.mqtt.unsubscribe(result_topic)

            if got:
                return reply_box[0]
            return f"Mise à jour demandée à {target} (pas de réponse dans 30s)."

        if cmd == "llm":
            return self._handle_llm_command(args)

        if cmd == "admins":
            return self._handle_admins_command(args)

        if cmd == "help":
            return self._nexus_help()

        return f"Commande inconnue : /{cmd}. Tape /help."

    def _handle_script_nexus_command(self, args: str) -> str:
        """
        /script run <agent> <nom> [args]          — exécuter maintenant
        /script schedule <freq> <agent> <nom> [args] — planifier
        /script unschedule <job_id>               — annuler une planification
        /script list [agent]                      — scripts dispo ou planifications
        /script schedules                         — voir les scripts planifiés

        Fréquences : daily HH:MM | once HH:MM | every Xh | every Xmin | weekly <jour> HH:MM
        """
        parts  = args.strip().split(None, 1)
        action = parts[0].lower() if parts else ""
        rest   = parts[1] if len(parts) > 1 else ""

        # ── run ──────────────────────────────────────────────────────────
        if action == "run":
            p = rest.split(None, 1)
            if len(p) < 2:
                return "Usage : /script run <agent> <nom> [args]"
            agent_id, script_rest = p[0], p[1]
            # Envoi direct COMMAND + attente réponse 30s
            import uuid as _uuid
            corr_id     = _uuid.uuid4().hex[:8]
            reply_topic = f"agents/results/{corr_id}"
            reply_box   = []
            reply_evt   = threading.Event()

            def _on_result(msg, topic):
                body = msg.payload if hasattr(msg, 'payload') else str(msg)
                reply_box.append(body)
                reply_evt.set()

            self.mqtt.subscribe(reply_topic, _on_result)
            try:
                self.mqtt.send_to(
                    agent_id,
                    f"/script exec {script_rest}",
                    msg_type=MessageType.COMMAND,
                    correlation_id=corr_id,
                    reply_to=reply_topic,
                )
                got = reply_evt.wait(timeout=30)
            finally:
                self.mqtt.unsubscribe(reply_topic)

            if got:
                return reply_box[0]
            return f"Pas de réponse de {agent_id} dans 30s."

        # ── schedule ─────────────────────────────────────────────────────
        if action == "schedule":
            # format : <fréquence> <agent> <nom> [args]
            # la fréquence peut être "daily HH:MM", "once HH:MM", "every Xh", "weekly lun HH:MM"
            # on détecte le début de l'agent_id (premier token qui n'appartient pas à la freq)
            p = rest.split()
            if len(p) < 3:
                return "Usage : /script schedule <fréquence> <agent> <nom> [args]"

            # Reconstruit fréquence selon le type
            if p[0] in ("daily", "once") and len(p) >= 3:
                freq, agent_id, script_name = p[0] + " " + p[1], p[2], p[3] if len(p) > 3 else ""
                script_args = " ".join(p[4:]) if len(p) > 4 else ""
            elif p[0] == "every" and len(p) >= 4:
                freq, agent_id, script_name = p[0] + " " + p[1], p[2], p[3]
                script_args = " ".join(p[4:]) if len(p) > 4 else ""
            elif p[0] == "weekly" and len(p) >= 5:
                freq, agent_id, script_name = p[0] + " " + p[1] + " " + p[2], p[3], p[4]
                script_args = " ".join(p[5:]) if len(p) > 5 else ""
            else:
                return "Format de fréquence non reconnu. Ex: daily 03:00 | once 14:30 | every 6h | weekly lun 08:00"

            if not script_name:
                return "Précise le nom du script."
            try:
                job_id = self.scheduler.add_script_job(
                    frequency=freq,
                    agent_id=agent_id,
                    script_name=script_name,
                    script_args=script_args,
                )
                return f"✓ Script '{script_name}' planifié sur @{agent_id} [{freq}] — id: {job_id}"
            except Exception as e:
                return f"Erreur : {e}"

        # ── unschedule ────────────────────────────────────────────────────
        if action == "unschedule":
            job_id = rest.strip()
            if not job_id:
                return "Usage : /script unschedule <job_id>"
            ok = self.scheduler.cancel_job(job_id)
            return f"Job '{job_id}' annulé." if ok else f"Job '{job_id}' introuvable."

        # ── schedules ─────────────────────────────────────────────────────
        if action == "schedules":
            jobs = {jid: j for jid, j in self.scheduler._jobs.items()
                    if j.get("type") == "script"}
            if not jobs:
                return "Aucun script planifié."
            lines = ["── Scripts planifiés ────────────────"]
            for j in jobs.values():
                lines.append(f"  [{j['id']}] {j['frequency']} → @{j['agent']} : {j['task']}")
            return "\n".join(lines)

        # ── list ──────────────────────────────────────────────────────────
        if action == "list":
            agent_id = rest.strip()
            if not agent_id:
                return "Usage : /script list <agent>"
            # Demande la liste directement via COMMAND
            import uuid as _uuid
            corr_id     = _uuid.uuid4().hex[:8]
            reply_topic = f"agents/results/{corr_id}"
            reply_box   = []
            reply_evt   = threading.Event()

            def _on_list(msg, topic):
                body = msg.payload if hasattr(msg, 'payload') else str(msg)
                reply_box.append(body)
                reply_evt.set()

            self.mqtt.subscribe(reply_topic, _on_list)
            try:
                self.mqtt.send_to(
                    agent_id, "/script list",
                    msg_type=MessageType.COMMAND,
                    correlation_id=corr_id,
                    reply_to=reply_topic,
                )
                got = reply_evt.wait(timeout=15)
            finally:
                self.mqtt.unsubscribe(reply_topic)

            return reply_box[0] if got else f"Pas de réponse de {agent_id}."

        return (
            "Usage :\n"
            "  /script run <agent> <nom> [args]\n"
            "  /script schedule <fréquence> <agent> <nom> [args]\n"
            "  /script unschedule <job_id>\n"
            "  /script schedules\n"
            "  /script list <agent>"
        )

    def _handle_queue_command(self, args: str) -> str:
        """
        /queue          — état du coordinateur LLM + files d'attente de chaque agent
        /queue <agent>  — file d'attente d'un agent spécifique
        """
        lines = []

        # État du coordinateur LLM
        if self._llm_coordinator:
            lines.append(f"── {self._llm_coordinator.status()}")
        else:
            lines.append("── Coordinateur LLM : inactif")

        target = args.strip()
        agents_to_show = []
        if target:
            caps = self.registry.get(target)
            if caps:
                agents_to_show = [caps]
            else:
                return f"Agent '{target}' inconnu."
        else:
            agents_to_show = self.registry.all_agents()

        lines.append("")
        with self._online_lock:
            online = set(self._online_agents)

        for caps in agents_to_show:
            aid     = caps.agent_id
            status  = "🟢" if aid in online else "🔴"
            # Demande les stats de la file via MQTT (non bloquant — on affiche ce qu'on sait)
            lines.append(f"{status} {aid} [{caps.agent_type}]")

        # Propre file nexus
        nexus_stats = self.queue.daily_stats()
        lines.append("")
        lines.append(
            f"Nexus today : {nexus_stats['total']} tâches "
            f"(✓{nexus_stats['completed']} ✗{nexus_stats['failed']} ⏳{nexus_stats['pending']})"
        )

        return "\n".join(lines)

    def _handle_llm_command(self, args: str) -> str:
        """
        /llm                          → statut actuel
        /llm local                    → switch tous les agents vers le profil local
        /llm cloud                    → switch tous les agents vers le profil cloud
        /llm list                     → liste les modèles Ollama disponibles
        /llm set local <model>        → définit + active le profil local
        /llm set cloud <model>        → définit + active le profil cloud
        """
        args = args.strip()

        if not args:
            current = self.config["llm"]["model"]
            profiles = self.config.get("llm_profiles", {})
            local = profiles.get("local", "non configuré")
            cloud = profiles.get("cloud", "non configuré")
            tag = "cloud" if ":cloud" in current else "local"
            return (
                f"── LLM actif : {current} ({tag}) ──\n"
                f"  local : {local}\n"
                f"  cloud : {cloud}\n"
                f"Commandes : /llm local | /llm cloud | /llm list\n"
                f"            /llm set local <model> | /llm set cloud <model>"
            )

        if args in ("local", "cloud"):
            profiles = self.config.get("llm_profiles", {})
            model = profiles.get(args)
            if not model:
                return f"Profil '{args}' non configuré. Utilise : /llm set {args} <model>"
            return self._switch_all_llm(args, model)

        if args == "list":
            return self._list_ollama_models()

        if args.startswith("set "):
            rest = args[4:].strip().split(None, 1)
            if len(rest) < 2:
                return "Usage : /llm set local <model> | /llm set cloud <model>"
            profile, model = rest[0].lower(), rest[1].strip()
            if profile not in ("local", "cloud"):
                return "Profil invalide : utilise 'local' ou 'cloud'."
            return self._switch_all_llm(profile, model)

        return "Usage : /llm | /llm local | /llm cloud | /llm list | /llm set local|cloud <model>"

    def _switch_all_llm(self, profile: str, model: str) -> str:
        """Broadcast le switch LLM à tous les agents + applique localement."""
        import json as _json
        payload = _json.dumps({"profile": profile, "model": model})
        self.mqtt.publish_raw("agents/llm/switch", payload, retain=True)
        # Application locale immédiate
        self.llm.model = model
        self.config["llm"]["model"] = model
        self.config.setdefault("llm_profiles", {})[profile] = model
        self._save_config()
        return f"✅ Switch LLM → {model} (profil {profile}) appliqué à tous les agents."

    def _list_ollama_models(self) -> str:
        """Liste les modèles disponibles sur Ollama, séparés local/cloud."""
        import requests as _req
        base_url = self.config["llm"]["base_url"]
        try:
            resp = _req.get(f"{base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            local = sorted(m["name"] for m in models if ":cloud" not in m["name"])
            cloud = sorted(m["name"] for m in models if ":cloud" in m["name"])
            lines = [f"── Modèles Ollama ({base_url}) ──"]
            lines.append("Local :")
            lines.extend(f"  {m}" for m in local)
            lines.append("Cloud :")
            lines.extend(f"  {m}" for m in cloud)
            return "\n".join(lines)
        except Exception as e:
            return f"Erreur Ollama : {e}"

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
  /queue                    — État du coordinateur LLM + files d'attente
  /queue <agent>            — File d'un agent spécifique
  /script run <a> <nom>     — Exécuter un script sur un agent
  /script schedule <f> <a> <nom> — Planifier un script (daily/once/every/weekly)
  /script unschedule <id>   — Annuler une planification de script
  /script schedules         — Voir les scripts planifiés
  /script list <agent>      — Lister les scripts d'un agent
  /update <agent>           — Mettre à jour un agent (git pull)
  /llm                      — Statut et gestion du LLM
  /llm local|cloud          — Switch le modèle pour tous les agents
  /llm list                 — Lister les modèles Ollama disponibles
  /llm set local|cloud <m>  — Définir un profil et l'activer
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

    def _schedule_send_script(self, agent_id: str, script_args: str):
        """Callback du scheduler pour exécuter un script planifié sur un agent."""
        with self._online_lock:
            online = agent_id in self._online_agents
        if not online:
            logger.warning(f"[Scheduler] Agent {agent_id} hors ligne, script ignoré : {script_args}")
            return
        self.mqtt.send_to(
            agent_id,
            f"/script exec {script_args}",
            msg_type=MessageType.COMMAND,
            reply_to=self.mqtt.topic_inbox(),
        )
        logger.info(f"[Scheduler] Script envoyé à {agent_id} : {script_args}")

    def _on_script_execution(self, msg, topic: str):
        """
        Un agent vient d'exécuter un script — notifie l'utilisateur via XMPP.
        Payload JSON : {agent_id, script, timestamp, result}
        """
        try:
            raw = msg if isinstance(msg, str) else (msg.payload if hasattr(msg, 'payload') else str(msg))
            if isinstance(raw, dict):
                data = raw
            else:
                data = json.loads(raw)
            agent_id  = data.get("agent_id", "?")
            script    = data.get("script", "?")
            timestamp = data.get("timestamp", "")
            result    = data.get("result", "")
            notif = (
                f"📋 Script exécuté\n"
                f"  Agent   : {agent_id}\n"
                f"  Script  : {script}\n"
                f"  Heure   : {timestamp}\n"
                f"  Résultat:\n{result}"
            )
            self.xmpp.send_to_all_admins(notif)
        except Exception as e:
            logger.debug(f"[Script] Erreur notification : {e}")

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

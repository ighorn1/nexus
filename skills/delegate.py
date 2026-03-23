"""
Skill DELEGATE — déléguer une tâche à un agent spécialisé via MQTT.
Attend la réponse de l'agent (synchrone) avant de retourner.

Usage LLM : SKILL:delegate ARGS:<agent_id> | <tâche>
"""
import threading
import uuid
from datetime import datetime

DESCRIPTION = "Déléguer une tâche à un agent spécialisé et retourner son résultat"
USAGE = "SKILL:delegate ARGS:<agent_id> | <tâche>"

TIMEOUT = 120  # secondes max d'attente de la réponse


def _is_within_work_hours(work_hours: str) -> bool:
    """Vérifie si l'heure actuelle est dans la plage HH:MM-HH:MM."""
    try:
        start_str, end_str = work_hours.strip().split("-")
        now = datetime.now().time()
        start = datetime.strptime(start_str.strip(), "%H:%M").time()
        end   = datetime.strptime(end_str.strip(),   "%H:%M").time()
        if start <= end:
            return start <= now <= end
        # Plage qui chevauche minuit (ex: 22:00-06:00)
        return now >= start or now <= end
    except Exception:
        return True  # En cas de format invalide, on laisse passer


def run(args: str, context) -> str:
    if "|" not in args:
        return "Format invalide. Usage : SKILL:delegate ARGS:<agent_id> | <tâche>"

    agent_id, task = args.split("|", 1)
    agent_id = agent_id.strip()
    task = task.strip()

    # Vérifier que l'agent est connu
    caps = context.registry.get(agent_id)
    if caps is None:
        known = [a.agent_id for a in context.registry.all_agents()]
        return f"Agent '{agent_id}' inconnu. Agents connus : {', '.join(known)}"

    # Vérifier les horaires de travail
    work_hours = getattr(caps, "work_hours", "00:00-23:59")
    if not _is_within_work_hours(work_hours):
        now_str = datetime.now().strftime("%H:%M")
        return f"⏰ Agent '{agent_id}' hors horaires ({work_hours}). Heure actuelle : {now_str}."

    # Préparer la réception de la réponse
    corr_id = str(uuid.uuid4())
    reply_topic = context.mqtt.topic_results(corr_id)

    result_event = threading.Event()
    result_holder = []

    def on_result(msg, topic):
        payload = msg.payload if hasattr(msg, "payload") else str(msg)
        result_holder.append(payload)
        result_event.set()

    # S'abonner avant d'envoyer pour ne pas manquer la réponse
    context.mqtt.subscribe(reply_topic, on_result)

    # Envoyer la tâche
    context.mqtt.send_to(
        recipient_id=agent_id,
        payload=task,
        correlation_id=corr_id,
        reply_to=reply_topic,
    )

    # Attendre la réponse
    got_reply = result_event.wait(timeout=TIMEOUT)
    context.mqtt.unsubscribe(reply_topic)

    if not got_reply:
        return f"⏱ Timeout : {agent_id} n'a pas répondu en {TIMEOUT}s."

    return result_holder[0] if result_holder else "Réponse vide de l'agent."

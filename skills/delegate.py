"""
Skill DELEGATE — déléguer une tâche à un agent spécialisé via MQTT.
Attend la réponse de l'agent (synchrone) avant de retourner.

Usage LLM : SKILL:delegate ARGS:<agent_id> | <tâche>
"""
import threading
import uuid

DESCRIPTION = "Déléguer une tâche à un agent spécialisé et retourner son résultat"
USAGE = "SKILL:delegate ARGS:<agent_id> | <tâche>"

TIMEOUT = 120  # secondes max d'attente de la réponse


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

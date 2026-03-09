"""
Skill DELEGATE — déléguer une tâche à un agent spécialisé via MQTT.

Usage LLM : SKILL:delegate ARGS:<agent_id> | <tâche>
"""
DESCRIPTION = "Déléguer une tâche à un agent spécialisé"
USAGE = "SKILL:delegate ARGS:<agent_id> | <tâche>"


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

    # Envoyer la tâche via MQTT
    sent = context.mqtt.send_to(
        recipient_id=agent_id,
        payload=task,
        reply_to=context.mqtt.topic_inbox(),
    )

    return f"Tâche déléguée à {agent_id} (id={sent.correlation_id[:8]}). Attente de la réponse..."

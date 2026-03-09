"""
Skill MQTT_SEND — publier un message sur n'importe quel topic MQTT.

Permet au LLM (et à l'utilisateur) de publier librement sur le bus.

Usage LLM : SKILL:mqtt_send ARGS:<topic> | <message>
"""
DESCRIPTION = "Publier un message sur un topic MQTT arbitraire"
USAGE = "SKILL:mqtt_send ARGS:<topic> | <message>"


def run(args: str, context) -> str:
    if "|" not in args:
        return "Format invalide. Usage : SKILL:mqtt_send ARGS:<topic> | <message>"

    topic, message = args.split("|", 1)
    topic = topic.strip()
    message = message.strip()

    if not topic:
        return "Topic vide."

    context.mqtt.publish_raw(topic, message)
    return f"Message publié sur '{topic}'."

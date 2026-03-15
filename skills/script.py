"""
Skill SCRIPT — bibliothèque de scripts bash par agent.

Chaque agent dispose de son propre dossier scripts/ (configurable via
"scripts_dir" dans config.json, sinon /opt/<install_dir>/scripts).

L'environnement du script expose automatiquement :
  MQTT_BROKER, MQTT_PORT, MQTT_REPLY_TOPIC, AGENT_ID, SCRIPTS_DIR

Ainsi un script peut publier son résultat directement :
  mosquitto_pub -h $MQTT_BROKER -t $MQTT_REPLY_TOPIC -m "mon résultat"

Usage LLM :
  SKILL:script ARGS:list
  SKILL:script ARGS:show <nom>
  SKILL:script ARGS:save <nom> | <contenu>
  SKILL:script ARGS:exec <nom> [args...]
  SKILL:script ARGS:run | <contenu inline>
  SKILL:script ARGS:delete <nom>
"""
import json
import os
import stat
import subprocess
import tempfile
from datetime import datetime

DESCRIPTION = "Bibliothèque de scripts bash : sauvegarder, lister, afficher, exécuter"
USAGE = (
    "SKILL:script ARGS:list\n"
    "SKILL:script ARGS:show <nom>\n"
    "SKILL:script ARGS:save <nom> | <contenu>\n"
    "SKILL:script ARGS:exec <nom> [args]\n"
    "SKILL:script ARGS:run | <contenu inline>\n"
    "SKILL:script ARGS:delete <nom>"
)


def _scripts_dir(context) -> str:
    """Détermine le répertoire scripts de cet agent."""
    if context.config.get("scripts_dir"):
        return context.config["scripts_dir"]
    queue_db = context.config.get("queue_db", "")
    if queue_db:
        install = os.path.dirname(os.path.dirname(queue_db))
        return os.path.join(install, "scripts")
    return f"/opt/{context.agent_id}/scripts"


def _ensure_dir(context) -> str:
    d = _scripts_dir(context)
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    """Empêche les traversées de répertoire."""
    return os.path.basename(name.strip().replace("/", "_"))


def _build_env(context, scripts_dir: str) -> dict:
    env = os.environ.copy()
    mc = context.config.get("mqtt", {})
    env["MQTT_BROKER"]      = mc.get("host", "localhost")
    env["MQTT_PORT"]        = str(mc.get("port", 1883))
    env["MQTT_REPLY_TOPIC"] = "agents/nexus/inbox"
    env["AGENT_ID"]         = context.agent_id
    env["SCRIPTS_DIR"]      = scripts_dir
    return env


def _notify(context, script_name: str, result: str):
    """Publie un événement d'exécution sur MQTT pour que Nexus notifie l'utilisateur."""
    try:
        context.mqtt.publish_raw("agents/scripts/execution", json.dumps({
            "agent_id":  context.agent_id,
            "script":    script_name,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "result":    result[:1000],
        }))
    except Exception:
        pass


def _run_script(cmd: str, env: dict, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, text=True,
            capture_output=True, timeout=timeout,
            env=env, executable="/bin/bash",
        )
        out = (result.stdout + result.stderr).strip()
        if len(out) > 4000:
            out = out[:4000] + "\n... [tronqué]"
        return out or f"(code retour : {result.returncode})"
    except subprocess.TimeoutExpired:
        return f"Timeout ({timeout}s dépassé)"
    except Exception as e:
        return str(e)


def run(args: str, context) -> str:
    parts  = args.strip().split(None, 1)
    action = parts[0].lower() if parts else "list"
    rest   = parts[1] if len(parts) > 1 else ""

    # ── list ──────────────────────────────────────────────────────────────
    if action == "list":
        d = _ensure_dir(context)
        files = sorted(f for f in os.listdir(d) if f.endswith(".sh"))
        if not files:
            return f"Aucun script dans {d}"
        lines = [f"Scripts disponibles ({d}) :"]
        for f in files:
            path = os.path.join(d, f)
            size = os.path.getsize(path)
            lines.append(f"  {f[:-3]:30s}  ({size} octets)")
        return "\n".join(lines)

    # ── show ──────────────────────────────────────────────────────────────
    if action == "show":
        name = _safe_name(rest)
        if not name:
            return "Précise le nom du script."
        d    = _ensure_dir(context)
        path = os.path.join(d, name + ".sh")
        if not os.path.exists(path):
            return f"Script '{name}' introuvable dans {d}"
        with open(path) as f:
            content = f.read()
        return f"── {name}.sh ──\n{content}"

    # ── save ──────────────────────────────────────────────────────────────
    if action == "save":
        if "|" not in rest:
            return "Format : save <nom> | <contenu du script>"
        name_raw, content = rest.split("|", 1)
        name    = _safe_name(name_raw)
        content = content.strip().replace("\\n", "\n")
        d       = _ensure_dir(context)
        path    = os.path.join(d, name + ".sh")
        existed = os.path.exists(path)
        with open(path, "w") as f:
            if not content.startswith("#!"):
                f.write("#!/bin/bash\n")
            f.write(content + "\n")
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
        verb = "mis à jour" if existed else "créé"
        return f"Script '{name}' {verb} : {path}"

    # ── exec ──────────────────────────────────────────────────────────────
    if action == "exec":
        parts2 = rest.split(None, 1)
        name   = _safe_name(parts2[0]) if parts2 else ""
        sargs  = parts2[1] if len(parts2) > 1 else ""
        if not name:
            return "Précise le nom du script."
        d    = _ensure_dir(context)
        path = os.path.join(d, name + ".sh")
        if not os.path.exists(path):
            return f"Script '{name}' introuvable. Utilise 'list' pour voir les scripts disponibles."
        env = _build_env(context, d)
        out = _run_script(f'"{path}" {sargs}', env=env, timeout=120)
        _notify(context, name, out)
        return out

    # ── run (inline) ──────────────────────────────────────────────────────
    if action == "run":
        if not rest:
            return "Précise le contenu du script."
        d       = _ensure_dir(context)
        content = rest.replace("\\n", "\n")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir="/tmp"
        ) as f:
            f.write("#!/bin/bash\nset -e\n" + content)
            tmpfile = f.name
        os.chmod(tmpfile, stat.S_IRWXU)
        env = _build_env(context, d)
        out = _run_script(tmpfile, env=env, timeout=60)
        os.unlink(tmpfile)
        _notify(context, "<inline>", out)
        return out

    # ── delete ────────────────────────────────────────────────────────────
    if action == "delete":
        name = _safe_name(rest)
        if not name:
            return "Précise le nom du script."
        d    = _ensure_dir(context)
        path = os.path.join(d, name + ".sh")
        if not os.path.exists(path):
            return f"Script '{name}' introuvable dans {d}"
        os.unlink(path)
        return f"Script '{name}' supprimé."

    return "Action inconnue. Disponible : list, show, save, exec, run, delete"

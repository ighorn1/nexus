# nexus

Orchestrateur principal du système multi-agents. Reçoit les instructions via XMPP, les traite avec un LLM (Ollama), délègue aux agents spécialisés via MQTT, et renvoie les résultats à l'utilisateur.

## Rôle

Nexus est le point d'entrée unique pour l'utilisateur. Il ne fait pas de travail technique lui-même — il comprend l'intention, choisit le bon agent, délègue la tâche, et agrège les résultats.

```
sylvain@xmpp.ovh
       ↕ XMPP
  nexus@xmpp.ovh
       ↕ MQTT
  debian.local  /  ansible.main  /  deploy  /  ...
```

## Installation

```bash
cd /opt/nexus
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
systemctl enable --now nexus
```

## Skills disponibles

| Skill | Description |
|-------|-------------|
| `delegate` | Délègue une tâche à un agent via MQTT |
| `agents_status` | Liste les agents en ligne/hors ligne |
| `memory` | Mémoire clé/valeur SQLite persistante |
| `web_search` | Recherche DuckDuckGo |
| `web_read` | Lecture de page web (BeautifulSoup) |
| `mqtt_send` | Publie sur un topic MQTT arbitraire |
| `mqtt_subscribe` | S'abonne dynamiquement à un topic MQTT |
| `muc_send` | Poste dans le groupe XMPP agents@muc.xmpp.ovh |

## Commandes XMPP

### Navigation
```
/help                     — Liste toutes les commandes
/status                   — Statut de Nexus (queue, pause...)
/agents                   — Liste et statut des agents connus
```

### Gestion du LLM
```
/llm                      — Modèle actif + profils configurés
/llm local                — Switch tous les agents vers le profil local
/llm cloud                — Switch tous les agents vers le profil cloud
/llm list                 — Liste les modèles Ollama disponibles
/llm set local <model>    — Définir le profil local et l'activer
/llm set cloud <model>    — Définir le profil cloud et l'activer
```

### Planification
```
/schedule daily 03:00 @debian apt upgrade -y
/schedule every 6h @ansible playbook site.yml
/schedules                — Voir les tâches planifiées
/schedule cancel <id>     — Annuler une tâche planifiée
```

### Administration
```
/admins                   — Lister les JIDs autorisés
/admins add <jid>         — Autoriser un utilisateur
/admins remove <jid>      — Retirer un utilisateur
/update <agent>           — Demande git pull + restart à un agent
/report [agent]           — Rapport quotidien
/reset                    — Effacer l'historique LLM
/sleep / /wake            — Mettre Nexus en veille / réveiller
```

### Routing direct
```
@debian.local apt update  — Commande directe sans passer par le LLM
@all status               — Broadcast à tous les agents
```

## Configuration

`config/config.json` :
```json
{
  "agent_id": "nexus",
  "xmpp": {
    "jid": "nexus@xmpp.ovh",
    "password": "...",
    "admin_jid": "sylvain@xmpp.ovh",
    "muc_room": "agents@muc.xmpp.ovh"
  },
  "mqtt": { "host": "localhost", "port": 1883 },
  "llm": {
    "base_url": "http://192.168.7.119:11434",
    "model": "ministral-3:latest",
    "temperature": 0.3
  },
  "llm_profiles": {
    "local": "ministral-3:latest",
    "cloud": "gpt-oss:120b-cloud"
  },
  "system_prompt": "/opt/nexus/config/system_prompt.txt"
}
```

`config/system_prompt.txt` : prompt système dynamique — la liste des agents disponibles est injectée automatiquement au moment de chaque appel LLM via les capacités publiées sur MQTT.

## Fichiers

```
nexus.py              — Point d'entrée principal
scheduler.py          — Gestion des tâches planifiées (APScheduler)
daily_report.py       — Agrégation des rapports quotidiens
skills/               — Skills de Nexus
config/               — Configuration et system prompt
nexus.service         — Unit systemd
```

## Dépendances

- agents_core (partagé)
- apscheduler ≥ 3.10
- duckduckgo-search ≥ 6.0
- beautifulsoup4 ≥ 4.12
- requests ≥ 2.28

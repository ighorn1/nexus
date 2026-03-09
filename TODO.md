# TODO — Système multi-agents (Nexus + agents spécialisés)

## Légende
- [x] Implémenté
- [ ] À faire
- [~] Partiel / à améliorer

---

## 1. Infrastructure de base

| Item | État |
|------|------|
| `agents_core` — librairie partagée (pip install -e) | [x] |
| `BaseAgent` — classe abstraite commune à tous les agents | [x] |
| Système de skills (plugins `.py` auto-découverts) | [x] |
| File d'attente SQLite FIFO par agent (`task_queue.py`) | [x] |
| Mode pause / resume par agent (`/pause`, `/resume`) | [x] |
| Plages horaires par agent (`work_hours` dans config.json) | [x] |
| Broker MQTT local (Mosquitto) | [x] |
| Topics MQTT structurés : inbox, status, capabilities, broadcast | [x] |
| LWT (Last Will Testament) MQTT → statut offline automatique | [x] |
| Reconnexion automatique MQTT | [x] |
| Reconnexion automatique XMPP (backoff exponentiel) | [x] |
| Dispatch XMPP handler en thread (évite blocage asyncio) | [x] |
| Protection contre appels LLM concurrents (`_llm_lock`) | [x] |
| Switch LLM global via MQTT retained (`/llm local/cloud`) | [x] |
| Reset historique LLM automatique lors d'un switch | [x] |

---

## 2. Nexus — orchestrateur

| Item | État |
|------|------|
| Connexion XMPP + MUC | [x] |
| Multi-utilisateurs XMPP (`admin_jids`) | [x] |
| Commandes `/admins add/remove/list` | [x] |
| **Persistance des admins ajoutés à chaud** (réécriture config.json) | [ ] |
| Mode veille `/sleep` / `/wake` | [x] |
| Scheduler APScheduler (`/schedule`, `/schedules`, `/schedule cancel`) | [x] |
| Rapports quotidiens agrégés (`/report`) | [x] |
| Délégation directe `@agent message` | [x] |
| Broadcast `@all message` | [x] |
| Mise à jour agent `/update <agent>` (envoi MQTT) | [x] |
| Commandes `/llm`, `/llm local/cloud`, `/llm list`, `/llm set` | [x] |
| Réponses nexus dans le MUC quand commande vient du MUC | [x] |
| Routage LLM dynamique (capacités agents injectées automatiquement) | [x] |
| **Vérification `work_hours` avant délégation** (delegate skill) | [ ] |
| **Blackout global** (plage horaire où aucune tâche n'est envoyée) | [ ] |
| **Commandes `/claude` et `/mammouth`** (appels one-shot API externes) | [ ] |
| **Skill `notify`** — envoyer une notification proactive à l'utilisateur | [ ] |
| **Historique des conversations** (persistance SQLite, `/history`) | [ ] |
| **Confirmation avant exécution** pour les actions destructives | [ ] |
| Commande `/status` détaillée (uptime, nb tâches, LLM actif…) | [~] |
| Skill `web_search` (DuckDuckGo) | [x] |
| Skill `web_read` (BeautifulSoup) | [x] |
| Skill `memory` (clé/valeur SQLite) | [x] |
| Skill `delegate` | [x] |
| Skill `mqtt_send` | [x] |

---

## 3. agent_debian — administration système

| Item | État |
|------|------|
| Skills : `sysinfo`, `apt`, `systemd`, `filesystem`, `network` | [x] |
| Skills : `process`, `journal`, `user`, `container`, `cron` | [x] |
| Skill `script` avec `$MQTT_REPLY_TOPIC` pour retour résultat | [x] |
| Skill `shell` (commandes arbitraires) | [x] |
| Monitoring proactif disque (>85%) → alerte MQTT | [x] |
| Monitoring proactif RAM (>90%) → alerte MQTT | [x] |
| **Seuils de monitoring configurables** dans config.json | [ ] |
| **Skill `backup`** — sauvegarde fichiers/bases vers destination | [ ] |
| **Skill `firewall`** — gestion ufw/iptables | [ ] |
| **Skill `logwatch`** — analyse automatique des logs suspects | [ ] |
| **Tests end-to-end des skills depuis Nexus** | [ ] |

---

## 4. agent_ansible — automatisation

| Item | État |
|------|------|
| Skill `playbook` | [x] |
| Skill `adhoc` (avec aliases : ping, facts, uptime…) | [x] |
| Skill `inventory` | [x] |
| Skill `galaxy` | [x] |
| Skill `vault` | [x] |
| `ansible.cfg` optimisé (pipelining, fact cache, 10 forks) | [x] |
| **Résultats long playbook** envoyés en streaming MQTT | [ ] |
| **Skill `template`** — générer des fichiers de config depuis Jinja2 | [ ] |
| **Venv + service systemd installés et testés** | [ ] |

---

## 5. agent_deploy — déploiement d'agents

| Item | État |
|------|------|
| Déploiement SSH (Paramiko) + local | [x] |
| Catalogue d'agents (nexus, debian, ansible, deploy) | [x] |
| Skill `deploy` avec progress MQTT temps réel | [x] |
| Skill `ssh` (commande distante + SCP) | [x] |
| Skill `catalog` (list/show/add/remove) | [x] |
| **Déployer agent_debian sur machine distante (test réel)** | [ ] |
| **Vérification post-déploiement** (agent en ligne sur MQTT ?) | [ ] |
| **Rollback automatique** si déploiement échoue | [ ] |

---

## 6. Mise à jour des agents (`/update`)

| Item | État |
|------|------|
| Nexus envoie `/update` via MQTT à l'agent cible | [x] |
| **BaseAgent gère `/update` : `git pull` + `systemctl restart`** | [ ] |
| Vérification si mise à jour disponible (`git fetch` + diff) | [ ] |
| Confirmation XMPP après redémarrage réussi | [ ] |
| `/update` sur Nexus lui-même (git pull + restart) | [ ] |

---

## 7. LLM — améliorations

| Item | État |
|------|------|
| Timeout LLM configurable (300s par défaut) | [x] |
| Switch global local/cloud via `/llm` | [x] |
| Profils `llm_profiles` par agent | [x] |
| **Commandes `/claude` et `/mammouth`** (one-shot API externes) | [ ] |
| **Support multi-backends** dans `llm_client.py` (Anthropic, OpenAI) | [ ] |
| **Désactiver le thinking mode** de qwen3 (`/no_think`) | [ ] |
| **Timeout par étape** dans `_llm_loop` (pas seulement global) | [ ] |
| **Limiter `max_steps`** configurable selon l'agent | [ ] |
| **Streaming des réponses LLM** vers XMPP (réponse progressive) | [ ] |

---

## 8. Sécurité / chiffrement

| Item | État |
|------|------|
| Filtrage XMPP par `admin_jids` | [x] |
| OMEMO (stub présent, non fonctionnel) | [~] |
| **OMEMO réel** (slixmpp-omemo) | [ ] |
| **OpenPGP alternative** (si OMEMO trop complexe) | [ ] |
| Authentification MQTT (username/password) | [~] |
| TLS MQTT | [~] |
| **Rotation des mots de passe** XMPP via commande | [ ] |
| **Rate limiting** — limiter le nombre de requêtes par minute | [ ] |

---

## 9. Observabilité / monitoring

| Item | État |
|------|------|
| Logs systemd par agent | [x] |
| Statut online/offline temps réel (MQTT retained) | [x] |
| **Dashboard web simple** — statut de tous les agents en temps réel | [ ] |
| **Métriques** — nb tâches/jour, temps moyen, taux d'erreur | [ ] |
| **Alertes** — notifier si un agent est offline depuis X minutes | [ ] |
| **Agrégation des logs** vers un topic MQTT centralisé | [ ] |

---

## 10. Nouveaux agents (idées)

| Agent | Rôle | État |
|-------|------|------|
| `agent_claude` | LLM Anthropic — tâches complexes, raisonnement | [ ] |
| `agent_mammouth` | LLM Mammouth AI — alternative FR | [ ] |
| `agent_docker` | Gestion Docker avancée (compose, registry, build) | [ ] |
| `agent_git` | Gestion dépôts Git, PR, issues Gitea/GitHub | [ ] |
| `agent_monitor` | Supervision réseau (ping, ports, services) | [ ] |
| `agent_mail` | Envoi/lecture emails, notifications | [ ] |
| `agent_homeassistant` | Domotique via HA API | [ ] |

---

## 11. Script d'installation (`install.sh`)

| Item | État |
|------|------|
| Scan modèles Ollama disponibles + choix interactif | [x] |
| Multi-utilisateurs XMPP (collection `admin_jids`) | [x] |
| Choix domaine XMPP | [x] |
| Sélection des agents à installer | [x] |
| Génération `config.json` + service systemd | [x] |
| Mode `--update` et `--uninstall` | [x] |
| **Test complet end-to-end de install.sh** | [ ] |
| **Documenter les prérequis (compte XMPP, Ollama…)** | [ ] |
| **Ajout `llm_profiles` automatique dans install.sh** | [ ] |

---

## 12. Ordre de priorité suggéré

1. **Implémenter `/update` dans BaseAgent** — git pull + restart (fonctionnalité clé)
2. **Persistance `/admins add`** — réécriture config.json
3. **Vérification `work_hours` dans delegate.py**
4. **Seuils monitoring configurables** dans agent_debian
5. **Test install.sh complet** sur machine vierge
6. **Commandes `/claude` et `/mammouth`** (quand clés API dispo)
7. **Support multi-backends LLM** dans llm_client.py
8. **Dashboard web** statut agents
9. **OMEMO** chiffrement XMPP

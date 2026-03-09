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
| **Vérification `work_hours` avant délégation** (delegate skill) | [ ] |
| **Blackout global** (plage horaire où aucune tâche n'est envoyée) | [ ] |
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
| **Venv + service systemd installés et testés** | [ ] |
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
| **Venv + service systemd installés et testés** | [ ] |
| **Déployer agent_debian sur machine distante (test réel)** | [ ] |

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

## 7. Sécurité / chiffrement

| Item | État |
|------|------|
| Filtrage XMPP par `admin_jids` | [x] |
| OMEMO (stub présent, non fonctionnel) | [~] |
| **OMEMO réel** (slixmpp-omemo) | [ ] |
| **OpenPGP alternative** (si OMEMO trop complexe) | [ ] |
| Authentification MQTT (username/password) | [~] |
| TLS MQTT | [~] |

---

## 8. Script d'installation (`install.sh`)

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

---

## 9. Ordre de priorité suggéré

1. **Implémenter `/update` dans BaseAgent** (git pull + restart) — fonctionnalité clé
2. **Installer et tester agent_debian** sur cette machine
3. **Persistance des admins** (réécriture config.json à chaud)
4. **Vérification `work_hours` dans delegate.py**
5. **Test install.sh complet** sur machine vierge
6. **OMEMO** (si slixmpp-omemo disponible)
7. **Blackout global** dans Nexus

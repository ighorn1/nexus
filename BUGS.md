# BUGS & PROBLÈMES CONNUS

## Bugs résolus ✓

| # | Description | Résolution |
|---|-------------|------------|
| B01 | `ImportError: cannot import name 'BaseAgent' from 'agents_core'` — `sys.path.insert(0, "/opt")` faisait trouver `/opt/agents_core` comme namespace package avant l'install éditable | Supprimé dans tous les agents |
| B02 | `AttributeError: '_SlixClient' object has no attribute 'process'` — slixmpp 1.13 est full asyncio, `process()` supprimé | Remplacé par `asyncio.new_event_loop()` + `loop.run_forever()` |
| B03 | `TypeError: XEP_0045.join_muc() got an unexpected keyword argument 'wait'` | Supprimé `wait=True` |
| B04 | `[Registry] Erreur parsing capacités` au démarrage — messages MQTT retained vides mal gérés | `update_from_json()` ignore silencieusement les payloads vides |
| B05 | Mosquitto refusait de démarrer — `Duplicate persistence_location` entre `/etc/mosquitto/mosquitto.conf` et notre `agents.conf` | Supprimé `persistence` et `persistence_location` de `agents.conf` |
| B06 | `send_xmpp_message()` appelé depuis un thread non-asyncio → comportement indéfini | Utilisation de `loop.call_soon_threadsafe()` |
| B07 | MUC room incorrecte (`agents@conference.xmpp.ovh` au lieu de `agents@muc.xmpp.ovh`) | Corrigé dans config.json et deployer.py |

---

## Bugs actifs

| # | Sévérité | Description | Piste |
|---|----------|-------------|-------|
| B08 | Haute | **Nexus ne voit pas les autres agents comme connectés** — `/agents` ne liste aucun agent en ligne même si les agents tournent. Nexus surveille les topics `agents/+/status` pour les mises à jour de présence, mais les agents n'ont peut-être pas encore publié leur statut retained, ou le topic pattern ne correspond pas. | Vérifier que les agents publient bien sur `agents/<id>/status` (retained) au démarrage, et que Nexus souscrit à ce topic au bon moment |
| B09 | Moyenne | **`Task exception was never retrieved`** dans les logs asyncio — une coroutine slixmpp lève une exception non capturée | Identifier la coroutine concernée, ajouter un handler `loop.set_exception_handler()` |
| B10 | Moyenne | **`/update <agent>` ne fait rien** — Nexus envoie la commande MQTT mais `BaseAgent` n'a pas de handler pour `/update` (git pull + restart) | Implémenter dans `base_agent.py` : handler `/update` → subprocess git pull → systemctl restart |
| B11 | Faible | **`/admins add <jid>` non persistant** — l'ajout à chaud d'un admin fonctionne en mémoire mais est perdu au redémarrage de Nexus | Réécrire `config.json` après chaque `add_admin()` / `remove_admin()` |
| B12 | Faible | **`work_hours` non vérifié avant délégation** — `skills/delegate.py` envoie la tâche sans vérifier si l'agent cible est dans ses heures de travail | Lire `caps.work_hours` depuis le registry et bloquer si hors plage |

---

## Points de vigilance

| # | Description |
|---|-------------|
| W01 | Les agents `agent_debian`, `agent_ansible`, `agent_deploy` n'ont pas encore été installés et testés sur cette machine |
| W02 | OMEMO est un stub non fonctionnel — les conversations XMPP ne sont pas chiffrées |
| W03 | Le broker MQTT est sans authentification (`allow_anonymous true`) — acceptable en réseau local, à sécuriser si exposé |
| W04 | `slixmpp` 1.13 — API asyncio, vérifier la compatibilité des plugins XEP si d'autres sont ajoutés |
| W05 | `_SlixClient.start()` crée un nouveau event loop par thread — s'assurer qu'aucun autre code n'appelle `asyncio.get_event_loop()` sans précaution dans ce thread |

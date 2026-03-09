"""
Skill MEMORY — mémorisation persistante clé/valeur (SQLite).

Usage LLM :
  SKILL:memory ARGS:set | <clé> | <valeur>
  SKILL:memory ARGS:get | <clé>
  SKILL:memory ARGS:list
  SKILL:memory ARGS:delete | <clé>
"""
import sqlite3
import os

DESCRIPTION = "Mémorisation persistante d'informations clé/valeur"
USAGE = "SKILL:memory ARGS:set|<clé>|<valeur>  ou  get|<clé>  ou  list"

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "memory.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    return conn


def run(args: str, context) -> str:
    parts = [p.strip() for p in args.split("|")]
    action = parts[0].lower() if parts else ""

    with _connect() as conn:
        if action == "set" and len(parts) >= 3:
            key, value = parts[1], "|".join(parts[2:])
            conn.execute(
                "INSERT OR REPLACE INTO memory (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value)
            )
            return f"Mémorisé : {key} = {value}"

        if action == "get" and len(parts) >= 2:
            row = conn.execute("SELECT value FROM memory WHERE key = ?", (parts[1],)).fetchone()
            return row[0] if row else f"Clé '{parts[1]}' introuvable."

        if action == "list":
            rows = conn.execute("SELECT key, value FROM memory ORDER BY key").fetchall()
            if not rows:
                return "Mémoire vide."
            return "\n".join(f"  {k}: {v}" for k, v in rows)

        if action == "delete" and len(parts) >= 2:
            conn.execute("DELETE FROM memory WHERE key = ?", (parts[1],))
            return f"Clé '{parts[1]}' supprimée."

    return "Usage : SKILL:memory ARGS:set|clé|valeur  ou  get|clé  ou  list  ou  delete|clé"

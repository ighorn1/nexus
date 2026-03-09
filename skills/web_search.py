"""
Skill WEB_SEARCH — recherche DuckDuckGo.

Usage LLM : SKILL:web_search ARGS:<requête>
"""
DESCRIPTION = "Recherche web via DuckDuckGo"
USAGE = "SKILL:web_search ARGS:<requête de recherche>"


def run(args: str, context) -> str:
    query = args.strip()
    if not query:
        return "Requête vide."
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(f"- {r['title']}\n  {r['href']}\n  {r['body'][:200]}")
        return "\n\n".join(results) if results else "Aucun résultat."
    except ImportError:
        return "Module duckduckgo_search non installé (pip install duckduckgo-search)"
    except Exception as e:
        return f"Erreur recherche : {e}"

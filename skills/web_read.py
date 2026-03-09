"""
Skill WEB_READ — lire le contenu d'une URL.

Usage LLM : SKILL:web_read ARGS:<url>
"""
DESCRIPTION = "Lire le contenu d'une page web"
USAGE = "SKILL:web_read ARGS:<url>"


def run(args: str, context) -> str:
    url = args.strip()
    if not url:
        return "URL vide."
    try:
        import requests
        from bs4 import BeautifulSoup
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Supprime scripts et styles
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Tronqué à 3000 caractères
        return text[:3000] + ("..." if len(text) > 3000 else "")
    except Exception as e:
        return f"Erreur lecture URL : {e}"

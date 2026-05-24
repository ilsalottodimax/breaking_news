import os
import re
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

SOURCES = {
    "Variety": "variety.com",
    "Hollywood Reporter": "hollywoodreporter.com",
    "Deadline": "deadline.com",
    "The Wrap": "thewrap.com",
}

ARTICLES_PER_SITE = 3

# Query mirata solo su nuove uscite e annunci di film
RELEASE_QUERY = "new movie film release date announced 2025 2026"

# Parole nel titolo che indicano contenuto da escludere
EXCLUDE_TITLE_KEYWORDS = {
    "interview", "review", "opinion", "column", "podcast", "ranking",
    "best of", "worst of", "list", "quiz", "gallery", "photos", "watch",
    "recap", "explainer", "analysis", "awards season", "box office report",
    "streaming guide", "where to watch",
}

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def is_release_news(title):
    title_lower = title.lower()
    if any(kw in title_lower for kw in EXCLUDE_TITLE_KEYWORDS):
        return False
    release_signals = {
        "release", "release date", "sets release", "coming to", "arrives",
        "premiere", "first look", "trailer", "teaser", "greenlit", "green-lit",
        "in production", "starts production", "begins filming", "wraps",
        "acquired", "buys", "picks up", "lands", "sets", "announced",
        "cast", "joins", "attached", "taps", "hires", "will star",
    }
    return any(kw in title_lower for kw in release_signals)


def fetch_from_tavily(source_name, domain):
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": RELEASE_QUERY,
            "search_depth": "advanced",
            "topic": "news",
            "days": 3,
            "include_domains": [domain],
            "max_results": 10,  # ne chiediamo di più per poter filtrare
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Tavily error per {source_name}: {resp.status_code} {resp.text}")
        return []

    results = resp.json().get("results", [])
    articles = []
    for r in results:
        if len(articles) >= ARTICLES_PER_SITE:
            break
        title = r.get("title", "").strip()
        if not is_release_news(title):
            print(f"  [skip] {title}")
            continue
        articles.append({
            "title": title,
            "link": r.get("url", ""),
            "summary": r.get("content", "")[:600].strip(),
        })
    print(f"{source_name}: {len(articles)} articoli nuove uscite trovati")
    return articles


def fetch_all():
    articles = {}
    for source_name, domain in SOURCES.items():
        articles[source_name] = fetch_from_tavily(source_name, domain)
    return articles


def build_prompt(articles):
    lines = [
        "Sei un assistente editoriale cinematografico. "
        "Ricevi notizie sulle nuove uscite e annunci di film dal cinema americano, in inglese. "
        "Per ogni articolo traduci il contenuto in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese. "
        "Focalizzati esclusivamente su: nuove uscite, date di uscita annunciate, casting, "
        "film in produzione, trailer, acquisizioni di diritti. "
        "Ignora interviste, recensioni, classifiche e contenuti editoriali generici. "
        "Restituisci HTML ben formattato per una email, con sezioni divise per testata, "
        "titolo come link cliccabile e testo tradotto sotto. "
        "Usa uno stile pulito e professionale.\n"
    ]
    for source, items in articles.items():
        if not items:
            continue
        lines.append(f"\n--- {source.upper()} ---")
        for i, art in enumerate(items, 1):
            lines.append(f"{i}. Titolo: {art['title']}")
            lines.append(f"   Link: {art['link']}")
            lines.append(f"   Contenuto: {art['summary']}\n")
    return "\n".join(lines)


def call_groq(prompt):
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4000,
        },
        timeout=60,
    )
    if not resp.ok:
        print(f"Groq error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def send_email(html_body):
    today = datetime.now().strftime("%d/%m/%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🎬 Cinema News – {today}"
    msg["From"] = GMAIL_USER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
    print(f"Email inviata a {EMAIL_TO}")


def main():
    print("Fetching news con Tavily...")
    articles = fetch_all()

    total = sum(len(v) for v in articles.values())
    if total == 0:
        print("Nessun articolo trovato, email non inviata.")
        return

    print(f"Totale articoli: {total}. Chiamata a Groq per traduzione...")
    prompt = build_prompt(articles)
    html_body = call_groq(prompt)

    print("Invio email...")
    send_email(html_body)


if __name__ == "__main__":
    main()

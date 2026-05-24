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
CINEMA_QUERY = "cinema film movie Hollywood release"

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def fetch_from_tavily(source_name, domain):
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": CINEMA_QUERY,
            "search_depth": "basic",
            "include_domains": [domain],
            "max_results": ARTICLES_PER_SITE,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"Tavily error per {source_name}: {resp.status_code} {resp.text}")
        return []

    results = resp.json().get("results", [])
    articles = []
    for r in results:
        articles.append({
            "title": r.get("title", "").strip(),
            "link": r.get("url", ""),
            "summary": r.get("content", "")[:600].strip(),
        })
    print(f"{source_name}: {len(articles)} articoli trovati")
    return articles


def fetch_all():
    articles = {}
    for source_name, domain in SOURCES.items():
        articles[source_name] = fetch_from_tavily(source_name, domain)
    return articles


def build_prompt(articles):
    lines = [
        "Sei un assistente editoriale cinematografico. "
        "Ricevi notizie dal cinema americano in inglese. "
        "Per ogni articolo traduci il contenuto in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese. "
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

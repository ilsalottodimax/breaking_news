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

MAJOR_STUDIOS = {
    "sony", "sony pictures", "columbia pictures",
    "warner bros", "warner brothers", "hbo", "max",
    "universal", "universal pictures", "amblin",
    "disney", "walt disney", "marvel", "pixar", "lucasfilm", "searchlight",
    "paramount", "paramount pictures", "miramax",
}

# Due query distinte: uscite/annunci + trending, filtrate sui major studios
QUERIES = [
    "Sony Warner Disney Universal Paramount movie film release announced trailer 2025 2026",
    "Sony Warner Disney Universal Paramount movie film trending box office now playing",
]

EXCLUDE_TITLE_KEYWORDS = {
    "interview", "opinion", "column", "podcast", "ranking",
    "best of", "worst of", "quiz", "gallery", "photos",
    "recap", "explainer", "streaming guide", "where to watch",
    "talks about", "opens up", "speaks out", "reflects on",
}

TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def mentions_major_studio(title, summary):
    text = (title + " " + summary).lower()
    return any(studio in text for studio in MAJOR_STUDIOS)


def is_valid_article(title):
    title_lower = title.lower()
    return not any(kw in title_lower for kw in EXCLUDE_TITLE_KEYWORDS)


def fetch_from_tavily(source_name, domain):
    seen_urls = set()
    candidates = []

    for query in QUERIES:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "topic": "news",
                "days": 2,
                "include_domains": [domain],
                "max_results": 10,
            },
            timeout=30,
        )
        if not resp.ok:
            print(f"Tavily error per {source_name}: {resp.status_code} {resp.text}")
            continue

        for r in resp.json().get("results", []):
            url = r.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = r.get("title", "").strip()
            summary = r.get("content", "")[:600].strip()
            if not is_valid_article(title):
                print(f"  [skip - formato] {title}")
                continue
            if not mentions_major_studio(title, summary):
                print(f"  [skip - studio] {title}")
                continue
            candidates.append({
                "title": title,
                "link": url,
                "summary": summary,
            })

    articles = candidates[:ARTICLES_PER_SITE]
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
        "Ricevi notizie fresche (ultimi 2 giorni) dal cinema americano su: nuove uscite, "
        "annunci di film, casting, trailer, film trending o attualmente al cinema. "
        "Per ogni articolo traduci il contenuto in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese come link cliccabili. "
        "NON includere interviste generiche sul cinema o contenuti editoriali non legati a un film specifico. "
        "Struttura la risposta come HTML per email: una sezione per ogni testata giornalistica "
        "(Variety, Hollywood Reporter, Deadline, The Wrap), con titolo linkato e testo tradotto sotto. "
        "Stile pulito e professionale, senza CSS inline eccessivo.\n"
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

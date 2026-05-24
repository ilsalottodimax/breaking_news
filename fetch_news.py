import os
import smtplib
import feedparser
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

FEEDS = {
    "Variety": "https://variety.com/feed/",
    "Hollywood Reporter": "https://www.hollywoodreporter.com/feed/",
    "Deadline": "https://deadline.com/feed/",
    "The Wrap": "https://www.thewrap.com/feed/",
}

ARTICLES_PER_SITE = 3

CINEMA_KEYWORDS = {
    "film", "movie", "cinema", "box office", "director", "actor", "actress",
    "screenplay", "script", "sequel", "prequel", "reboot", "premiere", "release",
    "trailer", "casting", "cast", "studio", "production", "streaming", "netflix",
    "amazon", "apple tv", "disney", "hulu", "a24", "warner", "universal",
    "paramount", "sony pictures", "lionsgate", "miramax", "award", "oscar",
    "golden globe", "cannes", "sundance", "toronto", "venice film", "bafta",
    "animated", "documentary", "thriller", "horror", "comedy film", "biopic",
    "blockbuster", "indie film", "short film", "feature film", "cinematographer",
    "producer", "distributor", "box-office", "ticket sales", "limited series",
    "miniseries",
}

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def is_cinema_related(title, summary):
    text = (title + " " + summary).lower()
    return any(kw in text for kw in CINEMA_KEYWORDS)


def fetch_articles():
    import re
    articles = {}
    for source, url in FEEDS.items():
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries:
            if len(items) >= ARTICLES_PER_SITE:
                break
            summary = entry.get("summary", entry.get("description", ""))
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            title = entry.get("title", "").strip()
            if not is_cinema_related(title, summary):
                continue
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary[:600],
            })
        articles[source] = items
        print(f"{source}: {len(items)} articoli cinema trovati")
    return articles


def build_prompt(articles):
    lines = [
        "Sei un assistente editoriale cinematografico. "
        "Ricevi notizie dal cinema americano in inglese. "
        "Per ogni articolo traduci il summary in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese. "
        "Restituisci HTML ben formattato per una email, con sezioni per ogni testata, "
        "titolo come link cliccabile e summary tradotto sotto. "
        "Usa uno stile pulito, senza CSS inline eccessivo.\n"
    ]
    for source, items in articles.items():
        lines.append(f"\n--- {source.upper()} ---")
        for i, art in enumerate(items, 1):
            lines.append(f"{i}. Titolo: {art['title']}")
            lines.append(f"   Link: {art['link']}")
            lines.append(f"   Summary: {art['summary']}\n")
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
    print("Fetching RSS feeds...")
    articles = fetch_articles()

    print("Chiamata a Groq per traduzione...")
    prompt = build_prompt(articles)
    html_body = call_groq(prompt)

    print("Invio email...")
    send_email(html_body)


if __name__ == "__main__":
    main()

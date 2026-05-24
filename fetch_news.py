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

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def fetch_articles():
    articles = {}
    for source, url in FEEDS.items():
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:ARTICLES_PER_SITE]:
            summary = entry.get("summary", entry.get("description", ""))
            # strip basic HTML tags from summary
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            items.append({
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "summary": summary[:600],
            })
        articles[source] = items
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
            "model": "llama3-70b-8192",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4000,
        },
        timeout=60,
    )
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

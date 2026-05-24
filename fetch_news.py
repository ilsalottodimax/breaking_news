import os
import re
import smtplib
import requests
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# Feed RSS sezione cinema di ogni testata
SOURCES = {
    "Variety":             "https://variety.com/v/film/feed/",
    "Deadline":            "https://deadline.com/category/film/feed/",
    "Hollywood Reporter":  "https://www.hollywoodreporter.com/c/movies/feed/",
    "The Wrap":            "https://www.thewrap.com/category/movies/feed/",
    "IndieWire":           "https://www.indiewire.com/category/film/feed/",
    "Collider":            "https://collider.com/feed/",
}

ARTICLES_PER_SITE = 3

MAJOR_STUDIOS = {
    "sony", "sony pictures", "columbia pictures",
    "warner bros", "warner brothers", "hbo", "max",
    "universal", "universal pictures", "dreamworks",
    "disney", "walt disney", "marvel", "pixar", "lucasfilm", "searchlight",
    "paramount", "paramount pictures", "miramax", "lionsgate",
}

EXCLUDE_TITLE_KEYWORDS = {
    "interview", "opinion", "column", "podcast", "ranking",
    "best of", "worst of", "quiz", "gallery", "photos",
    "recap", "explainer", "streaming guide", "where to watch",
    "talks about", "opens up", "speaks out", "reflects on",
}

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
EMAIL_TO = os.environ.get("EMAIL_TO", GMAIL_USER)


def clean_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def is_valid_article(title):
    title_lower = title.lower()
    return not any(kw in title_lower for kw in EXCLUDE_TITLE_KEYWORDS)


def mentions_major_studio(title, summary):
    text = (title + " " + summary).lower()
    return any(studio in text for studio in MAJOR_STUDIOS)


def fetch_from_rss(source_name, feed_url):
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        print(f"Errore fetch {source_name}: {e}")
        return []

    articles = []
    for entry in feed.entries:
        if len(articles) >= ARTICLES_PER_SITE:
            break
        title = clean_html(entry.get("title", "")).strip()
        summary = clean_html(entry.get("summary", entry.get("description", "")))[:600]
        link = entry.get("link", "")

        if not is_valid_article(title):
            print(f"  [skip - formato] {title}")
            continue
        if not mentions_major_studio(title, summary):
            print(f"  [skip - studio] {title}")
            continue

        articles.append({"title": title, "link": link, "summary": summary})

    print(f"{source_name}: {len(articles)} articoli trovati")
    return articles


def fetch_all():
    articles = {}
    for source_name, feed_url in SOURCES.items():
        articles[source_name] = fetch_from_rss(source_name, feed_url)
    return articles


def build_prompt(articles):
    lines = [
        "Sei un assistente editoriale cinematografico italiano. "
        "Ricevi notizie fresche dal cinema americano su film dei major studios "
        "(Sony, Warner Bros, Universal, Disney/Marvel, Paramount). "
        "Per ogni articolo traduci il contenuto in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese come link cliccabili. "
        "Struttura la risposta come HTML per email: una sezione per ogni testata, "
        "con titolo linkato e testo tradotto sotto. "
        "Stile pulito e professionale.\n"
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
    print("Fetching news via RSS...")
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

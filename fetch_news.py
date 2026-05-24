import os
import re
import smtplib
import requests
import feedparser
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

# Feed RSS sezione cinema di ogni testata
RSS_SOURCES = {
    "Variety":             "https://variety.com/v/film/feed/",
    "Deadline":            "https://deadline.com/category/film/feed/",
    "Hollywood Reporter":  "https://www.hollywoodreporter.com/c/movies/feed/",
    "The Wrap":            "https://www.thewrap.com/category/movies/feed/",
    "IndieWire":           "https://www.indiewire.com/category/film/feed/",
    "Collider":            "https://collider.com/feed/",
}

# Account Bluesky verificati — notizie cinema e major studios
BLUESKY_ACCOUNTS = {
    "DiscussingFilm":  "discussingfilm.net",
    "Film Updates":    "thefilmupdates.bsky.social",
    "THR Bluesky":     "thr.com",
}

# Newsletter Substack — industry insider letti da capi studio e distributori
SUBSTACK_SOURCES = {
    "Further & Better":             "https://furtherandbetter.substack.com/feed",
    "FranchiseRe (Box Office)":     "https://franchisere.substack.com/feed",
    "Entertainment Strategy Guy":   "https://entertainment.substack.com/feed",
}

ARTICLES_PER_SITE = 3
BLUESKY_POSTS_PER_ACCOUNT = 3
BLUESKY_API = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"

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


# ── RSS ──────────────────────────────────────────────────────────────────────

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

    print(f"{source_name}: {len(articles)} articoli RSS trovati")
    return articles


def fetch_all_rss():
    articles = {}
    for source_name, feed_url in RSS_SOURCES.items():
        articles[source_name] = fetch_from_rss(source_name, feed_url)
    return articles


# ── SUBSTACK ─────────────────────────────────────────────────────────────────

def fetch_from_substack(source_name, feed_url):
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        print(f"Errore Substack {source_name}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=5)
    articles = []

    for entry in feed.entries:
        if len(articles) >= 2:
            break
        title = clean_html(entry.get("title", "")).strip()
        summary = clean_html(entry.get("summary", entry.get("description", "")))[:600]
        link = entry.get("link", "")

        # filtra per data
        published = entry.get("published_parsed")
        if published:
            pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
            if pub_dt < cutoff:
                continue

        if not is_valid_article(title):
            continue

        articles.append({"title": title, "link": link, "summary": summary})

    print(f"{source_name} (Substack): {len(articles)} articoli trovati")
    return articles


def fetch_all_substack():
    articles = {}
    for source_name, feed_url in SUBSTACK_SOURCES.items():
        result = fetch_from_substack(source_name, feed_url)
        if result:
            articles[source_name] = result
    return articles


# ── BLUESKY ──────────────────────────────────────────────────────────────────

def fetch_from_bluesky(account_name, handle):
    try:
        resp = requests.get(
            BLUESKY_API,
            params={"actor": handle, "limit": 25},
            timeout=15,
        )
        if not resp.ok:
            print(f"Bluesky error {account_name}: {resp.status_code}")
            return []
    except Exception as e:
        print(f"Errore Bluesky {account_name}: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    posts = []

    for item in resp.json().get("feed", []):
        if len(posts) >= BLUESKY_POSTS_PER_ACCOUNT:
            break

        post = item.get("post", {})
        record = post.get("record", {})
        text = record.get("text", "").strip()
        created_at = record.get("createdAt", "")

        if not text:
            continue

        # filtra post più vecchi di 2 giorni
        try:
            post_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if post_time < cutoff:
                continue
        except Exception:
            continue

        if not mentions_major_studio(text, ""):
            continue

        # estrai eventuale link embed
        link = ""
        embed = post.get("embed", {})
        external = embed.get("external", {})
        if external:
            link = external.get("uri", "")

        uri = post.get("uri", "")
        if not link and uri:
            parts = uri.split("/")
            if len(parts) >= 2:
                link = f"https://bsky.app/profile/{handle}/post/{parts[-1]}"

        posts.append({"title": text[:120], "link": link, "summary": text[:600]})

    print(f"{account_name} (Bluesky): {len(posts)} post trovati")
    return posts


def fetch_all_bluesky():
    results = {}
    for account_name, handle in BLUESKY_ACCOUNTS.items():
        posts = fetch_from_bluesky(account_name, handle)
        if posts:
            results[account_name] = posts
    return results


# ── PROMPT & EMAIL ────────────────────────────────────────────────────────────

def build_prompt(rss_articles, bluesky_posts, substack_articles):
    lines = [
        "Sei un assistente editoriale cinematografico italiano. "
        "Ricevi notizie fresche (ultimi 2 giorni) dal cinema americano su film dei major studios "
        "(Sony, Warner Bros, Universal, Disney/Marvel, Paramount). "
        "Per ogni articolo o post traduci il contenuto in italiano in modo fluente e giornalistico. "
        "Mantieni i titoli originali in inglese come link cliccabili dove disponibili. "
        "Struttura la risposta come HTML per email, divisa in tre sezioni: "
        "1) TESTATE GIORNALISTICHE (Variety, Deadline, ecc.) "
        "2) NEWSLETTER SUBSTACK – INDUSTRY INSIDER "
        "3) BLUESKY – ACCOUNT CINEMA "
        "Per ogni sezione, sottodividi per fonte con titolo linkato e testo tradotto sotto. "
        "Stile pulito e professionale.\n"
    ]

    lines.append("\n=== TESTATE GIORNALISTICHE ===")
    for source, items in rss_articles.items():
        if not items:
            continue
        lines.append(f"\n--- {source.upper()} ---")
        for i, art in enumerate(items, 1):
            lines.append(f"{i}. Titolo: {art['title']}")
            lines.append(f"   Link: {art['link']}")
            lines.append(f"   Contenuto: {art['summary']}\n")

    lines.append("\n=== NEWSLETTER SUBSTACK – INDUSTRY INSIDER ===")
    for source, items in substack_articles.items():
        if not items:
            continue
        lines.append(f"\n--- {source.upper()} ---")
        for i, art in enumerate(items, 1):
            lines.append(f"{i}. Titolo: {art['title']}")
            lines.append(f"   Link: {art['link']}")
            lines.append(f"   Contenuto: {art['summary']}\n")

    lines.append("\n=== BLUESKY – INSIDER & ACCOUNT CINEMA ===")
    for account, posts in bluesky_posts.items():
        if not posts:
            continue
        lines.append(f"\n--- {account.upper()} ---")
        for i, post in enumerate(posts, 1):
            lines.append(f"{i}. Post: {post['summary']}")
            if post["link"]:
                lines.append(f"   Link: {post['link']}")
            lines.append("")

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
    rss_articles = fetch_all_rss()

    print("Fetching newsletter Substack...")
    substack_articles = fetch_all_substack()

    print("Fetching post Bluesky...")
    bluesky_posts = fetch_all_bluesky()

    total_rss = sum(len(v) for v in rss_articles.values())
    total_sub = sum(len(v) for v in substack_articles.values())
    total_bsky = sum(len(v) for v in bluesky_posts.values())
    print(f"Totale: {total_rss} RSS + {total_sub} Substack + {total_bsky} Bluesky")

    if total_rss + total_sub + total_bsky == 0:
        print("Nessun contenuto trovato, email non inviata.")
        return

    print("Chiamata a Groq per traduzione...")
    prompt = build_prompt(rss_articles, bluesky_posts, substack_articles)
    html_body = call_groq(prompt)

    print("Invio email...")
    send_email(html_body)


if __name__ == "__main__":
    main()

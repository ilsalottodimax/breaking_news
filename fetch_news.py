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
    "The Film Stage":      "https://thefilmstage.com/feed/",
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
    "Scott Mendelson":              "https://scottmendelson.substack.com/feed",
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


# ── TRADUZIONE GROQ ───────────────────────────────────────────────────────────

def build_translation_prompt(rss_articles, substack_articles, bluesky_posts):
    """Chiede a Groq di tradurre solo i testi, restituendo JSON strutturato."""
    lines = [
        "Sei un assistente editoriale cinematografico italiano. "
        "Traduci in italiano fluente e giornalistico i seguenti contenuti dal cinema americano. "
        "Per ogni voce restituisci SOLO un JSON array nel formato:\n"
        '[{"source": "nome fonte", "title": "titolo originale", "link": "url", "translated": "testo tradotto in italiano"}]\n'
        "Non aggiungere testo fuori dal JSON. Mantieni i titoli in inglese.\n\n"
    ]

    for source, items in rss_articles.items():
        for art in items:
            lines.append(f'SOURCE: {source} | TITLE: {art["title"]} | LINK: {art["link"]} | TEXT: {art["summary"]}')

    for source, items in substack_articles.items():
        for art in items:
            lines.append(f'SOURCE: {source} (Substack) | TITLE: {art["title"]} | LINK: {art["link"]} | TEXT: {art["summary"]}')

    for account, posts in bluesky_posts.items():
        for post in posts:
            lines.append(f'SOURCE: {account} (Bluesky) | TITLE: {post["title"]} | LINK: {post["link"]} | TEXT: {post["summary"]}')

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


# ── HTML TEMPLATE ─────────────────────────────────────────────────────────────

SECTION_ICONS = {
    "rss":       "📰",
    "substack":  "✉️",
    "bluesky":   "🦋",
}

def render_article_card(art):
    title = art.get("title", "")
    link  = art.get("link", "")
    text  = art.get("translated", art.get("summary", ""))
    title_html = f'<a href="{link}" style="color:#1a1a2e;text-decoration:none;font-weight:700;font-size:15px;line-height:1.4;">{title}</a>' if link else f'<span style="font-weight:700;font-size:15px;">{title}</span>'
    return f"""
        <div style="background:#ffffff;border-radius:10px;padding:18px 22px;margin-bottom:14px;border-left:4px solid #e63946;box-shadow:0 1px 4px rgba(0,0,0,0.07);">
          <p style="margin:0 0 8px 0;">{title_html}</p>
          <p style="margin:0;color:#444;font-size:13px;line-height:1.6;">{text}</p>
        </div>"""

def render_source_block(source_name, articles):
    cards = "".join(render_article_card(a) for a in articles)
    return f"""
      <div style="margin-bottom:10px;">
        <p style="margin:0 0 10px 0;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#888;">{source_name}</p>
        {cards}
      </div>"""

def render_section(icon, title, source_map):
    if not any(source_map.values()):
        return ""
    blocks = "".join(render_source_block(src, arts) for src, arts in source_map.items() if arts)
    return f"""
    <div style="margin-bottom:36px;">
      <h2 style="margin:0 0 18px 0;font-size:18px;color:#1a1a2e;border-bottom:2px solid #e63946;padding-bottom:8px;">
        {icon}&nbsp; {title}
      </h2>
      {blocks}
    </div>"""

def build_html_email(translated_items, rss_articles, substack_articles, bluesky_posts):
    import json

    # Mappa source → lista articoli tradotti
    translated_map = {}
    try:
        raw = translated_items.strip()
        # rimuovi eventuale markdown code block
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()
        items = json.loads(raw)
        for item in items:
            src = item.get("source", "")
            translated_map.setdefault(src, []).append(item)
    except Exception as e:
        print(f"JSON parse error: {e} — uso testo grezzo")
        # fallback: usa testi originali non tradotti
        for src, arts in {**rss_articles, **substack_articles, **bluesky_posts}.items():
            translated_map[src] = arts

    def get_translated(original_source, articles):
        result = []
        for art in articles:
            match = next((t for t in translated_map.get(original_source, []) if art["title"][:40] in t.get("title", "")), None)
            if match:
                result.append({**art, "translated": match.get("translated", art.get("summary", ""))})
            else:
                result.append({**art, "translated": art.get("summary", "")})
        return result

    rss_translated      = {src: get_translated(src, arts) for src, arts in rss_articles.items()}
    substack_translated = {src: get_translated(f"{src} (Substack)", arts) for src, arts in substack_articles.items()}
    bluesky_translated  = {src: get_translated(f"{src} (Bluesky)", arts) for src, arts in bluesky_posts.items()}

    today = datetime.now().strftime("%d %B %Y").upper()
    sec_rss      = render_section("📰", "Testate Giornalistiche", rss_translated)
    sec_substack = render_section("✉️", "Newsletter Substack — Industry Insider", substack_translated)
    sec_bluesky  = render_section("🦋", "Bluesky — Insider & Account Cinema", bluesky_translated)

    return f"""<!DOCTYPE html>
<html lang="it">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:32px 0;">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0" style="max-width:620px;width:100%;">

        <!-- HEADER -->
        <tr><td style="background:#1a1a2e;border-radius:12px 12px 0 0;padding:32px 36px;text-align:center;">
          <p style="margin:0 0 4px 0;font-size:11px;letter-spacing:3px;color:#e63946;text-transform:uppercase;font-weight:700;">La tua rassegna stampa</p>
          <h1 style="margin:0;font-size:30px;color:#ffffff;font-weight:800;letter-spacing:-0.5px;">Il Salotto di Max</h1>
          <p style="margin:10px 0 0 0;font-size:13px;color:#aaa;">Cinema &amp; Major Studios &mdash; {today}</p>
        </td></tr>

        <!-- BODY -->
        <tr><td style="background:#f4f4f8;padding:28px 24px;">
          {sec_rss}
          {sec_substack}
          {sec_bluesky}
        </td></tr>

        <!-- FOOTER -->
        <tr><td style="background:#1a1a2e;border-radius:0 0 12px 12px;padding:20px 36px;text-align:center;">
          <p style="margin:0;font-size:11px;color:#666;">
            Il Salotto di Max &mdash; Sony &bull; Warner Bros &bull; Universal &bull; Disney &bull; Paramount<br>
            <span style="color:#444;">Fonti: Variety, Deadline, THR, The Wrap, IndieWire, Collider, The Film Stage, Substack, Bluesky</span>
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_email(html_body):
    today = datetime.now().strftime("%d/%m/%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Il Salotto di Max – Cinema News {today}"
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
    prompt = build_translation_prompt(rss_articles, substack_articles, bluesky_posts)
    translated_json = call_groq(prompt)
    html_body = build_html_email(translated_json, rss_articles, substack_articles, bluesky_posts)

    print("Invio email...")
    send_email(html_body)


if __name__ == "__main__":
    main()

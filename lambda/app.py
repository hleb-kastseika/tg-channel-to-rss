"""AWS Lambda function for converting a Telegram channel to an RSS feed."""

from datetime import datetime
from typing import Optional, List
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from html import escape as html_escape
from rfeed import Feed, Item, Enclosure, Guid, Extension

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}
TIMEOUT = 30
URL_RE = re.compile(r'(https?://[^\s<>"\']+)')
BG_URL_RE = re.compile(r"background-image:\s*url\(['\"]?(?P<u>[^'\")]+)['\"]?\)", re.IGNORECASE)


def autolink_plain(text: str) -> str:
    """Convert plain URLs to <a href>…</a>, escape other text."""
    if not text:
        return ""

    out, last = [], 0
    for m in URL_RE.finditer(text):
        out.append(html_escape(text[last : m.start()]))
        url = m.group(1)
        safe_url = html_escape(url, quote=True)
        out.append(f'<a href="{safe_url}" rel="noopener" target="_blank">{safe_url}</a>')
        last = m.end()

    out.append(html_escape(text[last:]))
    return "".join(out)


class ContentEncoded(Extension):
    """Adds <content:encoded> without relying on rfeed.Element."""

    def __init__(self, html: str):
        """Wrap HTML content for the RSS content module."""
        self._html = f"<![CDATA[{html}]]>"

    def get_namespace(self):
        """Return the RSS module namespace."""
        return ("content", "http://purl.org/rss/1.0/modules/content/")

    def get_elements(self):
        """Return raw XML string for <content:encoded>."""
        return [f"<content:encoded>{self._html}</content:encoded>"]


def lambda_handler(event, _):
    """AWS Lambda entrypoint."""
    if not event.get("queryStringParameters") or event["queryStringParameters"].get("key") != os.environ["API_KEY"]:
        return {"statusCode": 401, "body": "Unauthorized"}

    try:
        channel = event["pathParameters"]["channel_name"]
        rss_xml = get_rss_feed(channel)
        return {
            "statusCode": 200,
            "body": rss_xml,
            "headers": {
                "Content-Type": "application/rss+xml; charset=UTF-8",
                "Cache-Control": "max-age=60, public",
            },
        }
    except Exception as ex:
        return {"statusCode": 400, "body": str(ex)}


def get_rss_feed(channel_name: str) -> str:
    """Build the RSS XML for a public Telegram channel."""
    url = f"https://t.me/s/{channel_name}"
    doc = get_doc(url)

    title = (doc.title.text or channel_name).strip() if doc.title else channel_name
    og_desc_tag = doc.select_one("meta[property='og:description'][content]")
    description = og_desc_tag["content"].strip() if og_desc_tag else f"Posts from {title}"

    items: List[Item] = []
    for bubble in doc.select("div.tgme_widget_message_bubble"):
        itm = build_item(bubble, channel_name)
        if itm:
            items.append(itm)

    feed = Feed(
        title=title,
        link=url,
        description=description,
        lastBuildDate=datetime.now(),
        items=items,
    )
    return feed.rss()


def get_doc(url: str) -> BeautifulSoup:
    """Fetch and parse the Telegram channel HTML page."""
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    if res.status_code != 200:
        raise Exception("Telegram channel not found")

    return BeautifulSoup(res.content, "lxml")


def build_item(div, channel_name: str) -> Optional[Item]:
    """Convert a Telegram message bubble <div> into an RSS Item."""
    link = get_link(div)
    if not link:
        return None

    time_tag = div.select_one("time.time[datetime]")
    pub = datetime.fromisoformat(time_tag["datetime"]) if time_tag else datetime.now()

    raw_html = get_html(div)
    first_para_html = sanitize_keep_links(raw_html) or f"<p>{autolink_plain(get_plain_text(div))}</p>"

    photos = get_photo_assets(div)
    media_html = "".join(f'<p><img src="{escape_attr(u)}" referrerpolicy="no-referrer"/></p>' for u in photos)

    description_html = first_para_html + media_html
    full_html = (raw_html + media_html) if (raw_html or media_html) else link

    enclosure = Enclosure(photos[0], 0, guess_mime(photos[0])) if photos else None
    guid = Guid(link, isPermaLink=True)

    return Item(
        title=f"New post in channel @{channel_name}",
        link=link,
        description=description_html,
        pubDate=pub,
        guid=guid,
        enclosure=enclosure,
        extensions=[ContentEncoded(full_html)],
    )


def get_link(div) -> Optional[str]:
    """Extract the canonical link to the Telegram post."""
    a = div.select_one("a.tgme_widget_message_date[href]")
    if not a:
        return None

    return a["href"].replace("://t.me/", "://t.me/s/")


def get_html(div) -> str:
    """Return Telegram post HTML."""
    el = div.select_one("div.tgme_widget_message_text")
    if not el:
        return ""

    html = el.decode_contents(formatter="minimal").strip()
    return absolutize_links(html, base="https://t.me/")


def get_plain_text(div) -> str:
    """Return plain text content of the message."""
    el = div.select_one("div.tgme_widget_message_text")
    if not el:
        return ""

    return el.get_text(" ", strip=True)


def sanitize_keep_links(html: str) -> str:
    """Produce a safe first paragraph that preserves only links and line breaks."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "lxml")
    container = soup if soup.body is None else soup.body

    for tag in container.find_all(True):
        if tag.name == "a":
            href = tag.get("href")
            tag.attrs = {}
            if href:
                tag["href"] = href
            tag["rel"] = "noopener"
            tag["target"] = "_blank"
        elif tag.name == "br":
            continue
        else:
            tag.unwrap()

    inner = "".join(str(x) for x in container.contents)
    return f"<p>{inner}</p>" if inner else ""


def get_photo_assets(div) -> List[str]:
    """Collect photo URLs while filtering out emoji/reaction images."""
    photos: List[str] = []

    def is_reaction_or_emoji(node) -> bool:
        """Heuristically detect reaction/emoji nodes to skip their images."""
        for parent in node.parents:
            cls = " ".join(parent.get("class", []))
            if "tgme_widget_message_reactions" in cls or "tgme_widget_message_reactions_small" in cls:
                return True

        cls_self = " ".join(node.get("class", []))
        if any(x in cls_self for x in ["emoji", "tgme_widget_emoji", "emoji_image"]):
            return True

        src = node.get("src") or ""
        if any(part in src for part in ["/emoji/", "/stickers/", "emoji-static", "emoji-animated"]):
            return True

        style = node.get("style", "")
        if "emoji" in style or "sticker" in style:
            return True

        return False

    for el in div.select("*[style]"):
        m = BG_URL_RE.search(el.get("style", ""))
        if not m:
            continue

        if is_reaction_or_emoji(el):
            continue

        url = m.group("u")
        photos.append(url)

    img = div.select_one("a.tgme_widget_message_link_preview img[src]")
    if img and not is_reaction_or_emoji(img):
        photos.append(img["src"])

    for img in div.select("img[src]"):
        if is_reaction_or_emoji(img):
            continue
        photos.append(img["src"])

    seen: set[str] = set()
    uniq: List[str] = []
    for u in photos:
        if u in seen:
            continue
        uniq.append(u)
        seen.add(u)

    return uniq


def absolutize_links(html: str, base: str) -> str:
    """Convert relative href/src values to absolute URLs against a base."""
    html = re.sub(r'href="(/[^"]+)"', lambda m: f'href="{urljoin(base, m.group(1))}"', html)
    html = re.sub(r"href='(/[^']+)'", lambda m: f"href='{urljoin(base, m.group(1))}'", html)
    html = re.sub(r'src="(/[^"]+)"', lambda m: f'src="{urljoin(base, m.group(1))}"', html)
    html = re.sub(r"src='(/[^']+)'", lambda m: f"src='{urljoin(base, m.group(1))}'", html)
    return html


def to_plain_text(html: str) -> str:
    """Strip an HTML fragment down to readable plain text."""
    if not html:
        return ""

    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def guess_mime(url: str) -> str:
    """Best-effort MIME type inference from URL/file extension."""
    u = url.lower()
    if u.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    if u.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def escape_attr(s: str) -> str:
    """Escape double quotes in attribute values for safe HTML attribute usage."""
    return s.replace('"', "&quot;")

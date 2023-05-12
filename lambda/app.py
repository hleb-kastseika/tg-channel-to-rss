"""AWS Lambda function for converting of Telegram channel to RSS feed."""
from datetime import datetime
import os

import requests

from bs4 import BeautifulSoup
from rfeed import Feed, Item


def lambda_handler(event, _):
    """Handle API Gateway event."""
    if not event["queryStringParameters"] or event["queryStringParameters"]["key"] != os.environ["API_KEY"]:
        return {
            "statusCode": 401,
            "body": "Unauthorized",
        }

    try:
        return {
            "statusCode": 200,
            "body": get_rss_feed(event["pathParameters"]["channel_name"]),
            "headers": {
                "Content-Type": "text/xml;charset=UTF-8",
                "Cache-Control": " Max-age=0, no-cache, no-store, must-revalidate",
            },
        }
    except Exception as ex:
        return {
            "statusCode": 400,
            "body": str(ex),
        }


def get_rss_feed(channel_name):
    """Build RSS XML from the Telegram channel."""
    url = f"https://t.me/s/{channel_name}"
    doc = get_doc(url)
    feed = Feed(
        title=doc.title.text,
        link=url,
        description=doc.select("meta[content][property='og:description']")[0].attrs["content"],
        lastBuildDate=datetime.now(),
        items=[Item(**get_item(d)) for d in doc.select("div[class~='tgme_widget_message_bubble']")],
    )
    return feed.rss()


def get_doc(url):
    """Build RSS XML from the Telegram channel."""
    res = requests.get(url, allow_redirects=False)
    if res.status_code != 200:
        raise Exception("Telegram channel not found")

    return BeautifulSoup(res.content, "lxml")


def get_item(div):
    """Create RSS feed item from the Telegram post."""
    return {
        "link": get_link(div),
        "title": get_text(div, 80),
        "description": get_text(div),
        "pubDate": datetime.fromisoformat(div.select("time[class='time']")[0].attrs["datetime"]),
    }


def get_link(div):
    """Get link to the Telegram post."""
    return div.select("a[href][class='tgme_widget_message_date']")[0].attrs["href"]


def get_text(div, cut_to=0):
    """Get content of the Telegram post."""
    elements = div.select("div[class~='tgme_widget_message_text']")
    if elements:
        text = elements[0].get_text(separator=" ")
        return text if cut_to == 0 else text[0:cut_to] + "..."

    return get_link(div)

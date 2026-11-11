"""IndexNow (design §7.8): tell search engines (Bing, Yandex and others that share IndexNow) at once that a claimset's
pages are new or changed, instead of waiting for their crawlers.

    key()                    -> the site's IndexNow key (PORTAL_INDEXNOW_KEY), or None: then nothing is sent
    notify(urls, base_url)   -> asks the engines to fetch these addresses; True if they took the request

The key is not a secret: IndexNow checks it against the file the site serves at /indexnow.txt (written by
site.write_fixed). Best effort: a failure is logged and nothing else happens; the sitemap still lists everything.
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request

ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_FILE = "/indexnow.txt"
log = logging.getLogger("portal.indexnow")


def key():
    k = os.environ.get("PORTAL_INDEXNOW_KEY", "").strip()
    return k if re.fullmatch(r"[A-Za-z0-9-]{8,128}", k) else None


def notify(urls, base_url, opener=urllib.request.urlopen):
    k = key()
    if not k or not urls:
        return False
    host = urllib.parse.urlparse(base_url).hostname
    body = json.dumps({"host": host, "key": k, "keyLocation": base_url.rstrip("/") + KEY_FILE,
                       "urlList": list(urls)[:10000]}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with opener(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:  # noqa: BLE001 - best effort: the sitemap still lists everything
        log.exception("IndexNow request failed")
        return False


def claimset_urls(concept, version, base_url):
    """The addresses of a newly published version: the claimset's page, the version's, the lists that changed."""
    from . import ids
    key_ = ids.url_key(concept)
    base = base_url.rstrip("/")
    return [f"{base}/p/{key_}", f"{base}/p/{key_}@v{version}", f"{base}/", f"{base}/all", f"{base}/sitemap.xml"]

# Sintergica CE extension: link previews for chat messages.
#
# The card data (og:title/description/image) is fetched SERVER-side: the
# browser can't (CORS), and routing it through Django lets us cache one fetch
# per URL for the whole workspace. Fetching arbitrary user-supplied URLs from
# inside the compose network is textbook SSRF, so every hop is validated:
# scheme, resolved addresses, redirect targets, content type and size.

import hashlib
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

from plane.app.views.base import BaseAPIView
from plane.chat.permissions import allow_chat

MAX_URL_CHARS = 2000
MAX_BODY_BYTES = 512 * 1024
MAX_REDIRECTS = 3
FETCH_TIMEOUT = (3, 4)  # connect, read
CACHE_HIT_TTL = 60 * 60 * 24
CACHE_MISS_TTL = 60 * 60
USER_AGENT = "TequioBot/1.0 (+https://tequio.sintergica.ai; link previews)"


def _is_public_http_url(url):
    """True only for http(s) URLs whose host resolves EXCLUSIVELY to global
    addresses. A single private/loopback/link-local/reserved record rejects
    the URL: one bad A record is all DNS rebinding needs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if parts.username or parts.password:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for raw in addresses:
        try:
            if not ipaddress.ip_address(raw).is_global:
                return False
        except ValueError:
            return False
    return True


class _MetaParser(HTMLParser):
    """og:/twitter: meta tags plus <title>, first wins per property."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self._in_title = False
        self.title = ""
        self._done = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if tag == "meta":
            attr = dict(attrs)
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = (attr.get("content") or "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "title" and not self.title:
            self._in_title = True
        elif tag == "body":
            # Everything we want lives in <head>; stop feeding early.
            self._done = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _first(meta, *keys):
    for key in keys:
        value = meta.get(key)
        if value:
            return value
    return None


def _fetch_preview(url):
    """Returns the preview dict, or None when the URL yields nothing usable.
    Raises nothing: every failure is a None (the card just doesn't render)."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _is_public_http_url(current):
            return None
        try:
            response = requests.get(
                current,
                timeout=FETCH_TIMEOUT,
                stream=True,
                allow_redirects=False,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
            )
        except requests.RequestException:
            return None
        try:
            if response.is_redirect or response.is_permanent_redirect:
                target = response.headers.get("Location")
                if not target:
                    return None
                current = urljoin(current, target)
                continue
            if response.status_code != 200:
                return None
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return None
            body = response.raw.read(MAX_BODY_BYTES, decode_content=True)
        finally:
            response.close()

        parser = _MetaParser()
        try:
            parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
        except Exception:
            return None

        meta = parser.meta
        title = _first(meta, "og:title", "twitter:title") or parser.title.strip()
        if not title:
            return None
        image = _first(meta, "og:image", "og:image:url", "twitter:image")
        if image:
            image = urljoin(current, image)
            # The browser fetches the image itself; keep only web schemes so
            # the card can't smuggle javascript:/data: into an <img>.
            if urlsplit(image).scheme not in ("http", "https"):
                image = None
        return {
            "url": url,
            "title": title[:300],
            "description": (_first(meta, "og:description", "twitter:description", "description") or "")[:500],
            "image": image,
            "site_name": (_first(meta, "og:site_name") or "")[:100],
            "domain": urlsplit(current).hostname or "",
        }
    return None  # redirect chain too long


class ChatLinkPreviewEndpoint(BaseAPIView):
    """GET ?url= → the og card of one external link, cached workspace-wide.

    204 (cached too) means "nothing to show": the client renders no card and
    won't ask again for a while. Any workspace member may resolve any URL —
    the preview leaks nothing that following the link wouldn't.
    """

    @allow_chat
    def get(self, request, slug):
        url = (request.query_params.get("url") or "").strip()
        if not url or len(url) > MAX_URL_CHARS:
            return Response({"error": "Invalid url."}, status=status.HTTP_400_BAD_REQUEST)
        if urlsplit(url).scheme not in ("http", "https"):
            return Response({"error": "Invalid url."}, status=status.HTTP_400_BAD_REQUEST)

        key = "chat:linkpreview:" + hashlib.sha256(url.encode()).hexdigest()
        cached = cache.get(key)
        if cached is not None:
            if cached == "":
                return Response(status=status.HTTP_204_NO_CONTENT)
            return Response(cached, status=status.HTTP_200_OK)

        preview = _fetch_preview(url)
        if preview is None:
            cache.set(key, "", CACHE_MISS_TTL)
            return Response(status=status.HTTP_204_NO_CONTENT)
        cache.set(key, preview, CACHE_HIT_TTL)
        return Response(preview, status=status.HTTP_200_OK)

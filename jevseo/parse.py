"""Turn one HTML document into the page facts every later stage reads."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from requests.utils import requote_uri

BOILERPLATE = ["script", "style", "noscript", "template", "svg", "iframe"]
CHROME = ["nav", "header", "footer", "aside", "form"]
WORD = re.compile(r"[\w'-]+", re.UNICODE)


def normalize_url(url: str) -> str:
    """Drop the fragment and a trailing slash on non-root paths; keep the query."""
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    # Percent-encode like requests does, so /café and /caf%C3%A9 are one URL.
    return requote_uri(p._replace(scheme=p.scheme.lower(), netloc=p.netloc.lower(), path=path).geturl())


def host_key(host: str) -> str:
    host = host.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


NOISE = re.compile(r"\S{41,}")  # base64 blobs, hashes and minified code are not reader-facing words


def _text(el) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", NOISE.sub(" ", el.get_text(" ", strip=True))).strip()


def _node_summary(node: dict, types: list[str]) -> dict:
    """What the property checks need from a JSON-LD node, without keeping its content."""
    offers = node.get("offers")
    offer_list = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    items = node.get("itemListElement")
    items = items if isinstance(items, list) else []

    def item_ok(i):
        return isinstance(i, dict) and "position" in i and ("name" in i or (isinstance(i.get("item"), dict) and "name" in i["item"]))

    return {
        "types": types,
        "keys": sorted(k for k in node if not k.startswith("@")),
        "offers_price": any(isinstance(o, dict) and ("price" in o or "lowPrice" in o) for o in offer_list),
        "list_items": len(items),
        "list_items_ok": all(item_ok(i) for i in items) if items else False,
    }


def _jsonld(soup) -> tuple[list[str], list[str], list[dict]]:
    types, errors, nodes = [], [], []

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            ts = [t] if isinstance(t, str) else [str(x) for x in t] if isinstance(t, list) else []
            types.extend(ts)
            if ts and len(nodes) < 40:
                nodes.append(_node_summary(node, ts))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v.lower()):
        raw = tag.string or tag.get_text() or ""
        try:
            walk(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as err:
            errors.append(str(err)[:120])
    return sorted(set(types)), errors, nodes


def parse_page(url: str, html: str, site_host: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    head = soup.head or soup

    def meta(name=None, prop=None):
        attrs = {"name": re.compile(f"^{re.escape(name)}$", re.I)} if name else {"property": re.compile(f"^{re.escape(prop)}$", re.I)}
        tag = head.find("meta", attrs=attrs) or soup.find("meta", attrs=attrs)
        return (tag.get("content") or "").strip() if tag else None

    titles = [_text(t) for t in soup.find_all("title") if not t.find_parent("svg")]
    canon = soup.find("link", rel=lambda v: v and "canonical" in [r.lower() for r in (v if isinstance(v, list) else [v])])
    hreflang = [
        {"lang": link.get("hreflang"), "href": urljoin(url, link.get("href", ""))}
        for link in soup.find_all("link", hreflang=True)
    ]
    schema_types, schema_errors, schema_nodes = _jsonld(soup)
    microdata = sorted({i.get("itemtype", "").rsplit("/", 1)[-1] for i in soup.find_all(itemtype=True)} - {""})

    headings = {f"h{i}": [_text(h) for h in soup.find_all(f"h{i}")] for i in range(1, 4)}
    outline = [(h.name, _text(h)) for h in soup.find_all(re.compile("^h[1-6]$"))]
    heading_skips = 0
    last = 0
    for name, _ in outline:
        level = int(name[1])
        if last and level > last + 1:
            heading_skips += 1
        last = level

    # Mixed content means insecure subresources, never plain outbound links.
    mixed = []
    if url.startswith("https://"):
        for tag in soup.find_all(["img", "script", "iframe", "video", "audio", "source", "embed"], src=True):
            if tag["src"].strip().startswith("http://"):
                mixed.append(tag["src"].strip())
        for tag in soup.find_all("link", href=True, rel=True):
            rel = " ".join(tag["rel"]).lower()
            if tag["href"].strip().startswith("http://") and any(r in rel for r in ("stylesheet", "icon", "preload", "manifest")):
                mixed.append(tag["href"].strip())
    images = soup.find_all("img")
    missing_alt = [urljoin(url, i.get("src") or i.get("data-src") or "") for i in images if i.get("alt") is None]
    empty_alt = sum(1 for i in images if i.get("alt") is not None and not i.get("alt").strip())
    lazy = sum(1 for i in images if (i.get("loading") or "").lower() == "lazy")
    no_dims = sum(1 for i in images if not (i.get("width") and i.get("height")))

    internal, external, nofollow = [], [], 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        absolute = urljoin(url, href)
        p = urlparse(absolute)
        if p.scheme not in ("http", "https"):
            continue
        rel = [r.lower() for r in (a.get("rel") or [])]
        nofollow += "nofollow" in rel
        target = normalize_url(absolute)
        anchor = _text(a)[:120] or (a.find("img").get("alt", "") if a.find("img") else "")
        (internal if host_key(p.netloc) == site_host else external).append({"url": target, "anchor": anchor})

    for tag in soup(BOILERPLATE):
        tag.decompose()
    body = soup.body or soup
    full_text = _text(body)
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"})
    if main is None:
        clone = BeautifulSoup(str(body), "lxml")
        for tag in clone(CHROME):
            tag.decompose()
        main_text = _text(clone)
    else:
        main_text = _text(main)
    if len(WORD.findall(main_text)) < 40:
        main_text = full_text
    # Link and button labels inside the main content: the evidence for "is there a next step".
    scope = main if main is not None else clone
    ctas = list(dict.fromkeys(t for t in (_text(el) for el in scope.find_all(["a", "button"])) if 1 <= len(t.split()) <= 8))[:25]
    words = WORD.findall(main_text)
    nav = soup.find("nav")

    html_tag = soup.find("html")

    return {
        "title": titles[0] if titles else None,
        "title_count": len(titles),
        "meta_description": meta(name="description"),
        "meta_robots": (meta(name="robots") or "").lower() or None,
        "canonical": normalize_url(urljoin(url, canon.get("href", ""))) if canon and canon.get("href") else None,
        "lang": (html_tag.get("lang") if html_tag else None) or None,
        "viewport": meta(name="viewport"),
        "charset": bool(soup.find("meta", charset=True)) or "charset" in (html[:2000].lower()),
        "og": {k: meta(prop=f"og:{k}") for k in ("title", "description", "image", "type", "url")},
        "twitter_card": meta(name="twitter:card"),
        "favicon": bool(soup.find("link", rel=lambda v: v and "icon" in " ".join(v if isinstance(v, list) else [v]).lower())),
        "hreflang": hreflang,
        "h1": headings["h1"],
        "h2": headings["h2"][:30],
        "h3": headings["h3"][:30],
        "outline": [f"{n}: {t}" for n, t in outline[:60]],
        "heading_skips": heading_skips,
        "word_count": len(words),
        "text_excerpt": main_text[:8000],
        "calls_to_action": ctas,
        "nav_labels": [_text(a) for a in nav.find_all("a")][:40] if nav else [],
        "text_hash": hashlib.sha1(" ".join(words).lower().encode()).hexdigest(),
        "images": {"total": len(images), "missing_alt": len(missing_alt), "empty_alt": empty_alt, "lazy": lazy, "no_dimensions": no_dims, "missing_alt_samples": missing_alt[:10]},
        "links_internal": internal,
        "links_external": external,
        "nofollow_links": nofollow,
        "schema_types": schema_types + [f"microdata:{m}" for m in microdata],
        "schema_errors": schema_errors,
        "schema_nodes": schema_nodes,
        "mixed_content": sorted(set(mixed))[:20],
        "script_count": html.lower().count("<script"),
    }

"""Live, polite crawl from a homepage: robots.txt, sitemaps, BFS over internal links.

The crawler stays on the submitted host (www and apex count as one), honours
robots.txt and Crawl-delay for its own user agent, refuses private network
targets, and renders pages with a headless browser only when raw HTML is
missing the visible content.
"""
from __future__ import annotations

import gzip
import ipaddress
import random
import re
import socket
import string
import threading
import time
import urllib.robotparser
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from lxml import etree

from jevseo import USER_AGENT
from jevseo.parse import host_key, normalize_url, parse_page

TIMEOUT = 20
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif|svg|ico|pdf|zip|gz|mp4|mp3|webm|woff2?|ttf|css|js|xml|json|txt|md|markdown|docx?|xlsx?|pptx?)$", re.I)
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider"]
SEARCH_BOTS = ["Googlebot", "Bingbot"]
SECURITY_HEADERS = ["strict-transport-security", "content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def public_host(host: str) -> bool:
    """SSRF guard: refuse hosts that resolve to private, loopback or link-local space."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


class Fetcher:
    def __init__(self, delay: float = 0.0):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8", "Accept-Language": "en;q=0.9,*;q=0.5"})
        self.delay = delay
        self.lock = threading.Lock()
        self.last = 0.0
        self.requests = 0
        self.public: dict[str, bool] = {}

    def _pace(self) -> None:
        with self.lock:
            self.requests += 1
            if self.delay:
                wait = self.last + self.delay - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()

    def _allowed_host(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if host not in self.public:
            self.public[host] = public_host(host)
        return self.public[host]

    def _send(self, method: str, url: str, **kw) -> requests.Response | None:
        """Follow redirects by hand so every hop passes the private-network guard."""
        history = []
        for _ in range(10):
            if urlparse(url).scheme not in ("http", "https") or not self._allowed_host(url):
                return None
            self._pace()
            try:
                r = self.session.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kw)
            except (requests.RequestException, ValueError):
                return None
            if r.is_redirect and r.headers.get("location"):
                history.append(r)
                r.close()
                url = urljoin(r.url, r.headers["location"])
                continue
            r.history = history
            return r
        return None

    def get(self, url: str, **kw) -> requests.Response | None:
        return self._send("GET", url, **kw)

    def head(self, url: str) -> int | None:
        r = self._send("HEAD", url)
        # Some servers (support.google.com among them) fail HEAD but serve GET: never call a link broken on HEAD alone.
        if r is None or r.status_code >= 400:
            r = self._send("GET", url, stream=True)
            if r is not None:
                r.close()
        return r.status_code if r is not None else None


def read_robots(fetcher: Fetcher, origin: str) -> dict:
    url = origin + "/robots.txt"
    r = fetcher.get(url)
    body = r.text if r is not None and r.status_code == 200 and "html" not in r.headers.get("content-type", "") else ""
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.splitlines())
    sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", body)
    probe = origin + "/"
    return {
        "url": url,
        "status": r.status_code if r is not None else None,
        "present": bool(body),
        "bytes": len(body.encode()),
        "sitemaps": sitemaps,
        "crawl_delay": parser.crawl_delay(USER_AGENT.split("/")[0]) or parser.crawl_delay("*"),
        "disallow_all": not parser.can_fetch("*", probe) if body else False,
        "search_bots": {b: parser.can_fetch(b, probe) for b in SEARCH_BOTS},
        "ai_bots": {b: parser.can_fetch(b, probe) for b in AI_BOTS},
        "ai_bots_named": [b for b in AI_BOTS if re.search(rf"(?im)^\s*user-agent:\s*{re.escape(b)}\s*$", body)],
        "_parser": parser,
    }


def read_sitemaps(fetcher: Fetcher, urls: list[str], limit: int = 5000) -> dict:
    found, seen, out = [], set(), []
    queue = deque(urls)
    while queue and len(seen) < 25:
        sm = queue.popleft()
        if sm in seen:
            continue
        seen.add(sm)
        r = fetcher.get(sm)
        entry = {"url": sm, "status": r.status_code if r is not None else None, "urls": 0, "error": None, "lastmod": 0}
        if r is None or r.status_code != 200:
            entry["error"] = "unreachable" if r is None else f"HTTP {r.status_code}"
            out.append(entry)
            continue
        content = r.content
        if sm.endswith(".gz") or content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
        try:
            root = etree.fromstring(content, parser=etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
        except etree.XMLSyntaxError:
            root = None
        if root is None:
            entry["error"] = "not valid XML"
            out.append(entry)
            continue
        tag = etree.QName(root).localname
        # "{*}" matches elements in any namespace and skips comments and processing instructions.
        locs = [el.text.strip() for el in root.iter("{*}loc") if el.text]
        entry["lastmod"] = sum(1 for _ in root.iter("{*}lastmod"))
        entry["type"] = tag
        if tag == "sitemapindex":
            queue.extend(locs)
            entry["children"] = len(locs)
        else:
            entry["urls"] = len(locs)
            found.extend(locs)
        out.append(entry)
    unique = list(dict.fromkeys(normalize_url(u) for u in found))
    return {"files": out, "urls": unique[:limit], "total_urls": len(unique)}


class Renderer:
    """Headless Chromium through Playwright, started lazily and only if needed."""

    def __init__(self):
        self._pw = self._browser = None
        self.available = None

    def render(self, url: str) -> str | None:
        try:
            if self._browser is None:
                from playwright.sync_api import sync_playwright

                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch()
                self.available = True
            page = self._browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=30000)
            html = page.content()
            page.close()
            return html
        except Exception:  # noqa: BLE001  rendering is best effort; raw HTML remains the evidence
            self.available = False
            return None

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()


def fetch_page(fetcher: Fetcher, url: str, site_host: str) -> dict:
    """One page fetch; any parser failure becomes an error record, never a crashed crawl."""
    try:
        return _fetch_page(fetcher, url, site_host)
    except Exception as err:  # noqa: BLE001
        return {"url": url, "fetched_at": now(), "status": None, "error": f"parse failure: {type(err).__name__}"}


def _fetch_page(fetcher: Fetcher, url: str, site_host: str) -> dict:
    started = time.monotonic()
    r = fetcher.get(url)
    elapsed = round((time.monotonic() - started) * 1000)
    rec = {"url": url, "fetched_at": now(), "fetch_ms": elapsed}
    if r is None:
        return rec | {"status": None, "error": "network error or timeout"}
    ctype = r.headers.get("content-type", "")
    rec |= {
        "status": r.status_code,
        "final_url": normalize_url(r.url),
        "redirect_chain": [{"url": h.url, "status": h.status_code} for h in r.history],
        "content_type": ctype.split(";")[0].strip(),
        "bytes": len(r.content),
        "ttfb_ms": round(r.elapsed.total_seconds() * 1000),
        "x_robots": r.headers.get("x-robots-tag"),
        "headers": {h: r.headers.get(h) for h in SECURITY_HEADERS if r.headers.get(h)},
        "rendered": False,
        "js_dependent": False,
    }
    if r.status_code != 200 or "html" not in ctype:
        return rec
    facts = parse_page(rec["final_url"], decode(r), site_host)
    rec["raw_word_count"] = facts["word_count"]
    return rec | facts


def decode(r: requests.Response) -> str:
    """Header charset first, then the page's own meta charset, then UTF-8. Never requests' Latin-1 default."""
    if "charset=" in r.headers.get("content-type", "").lower():
        return r.text
    head = r.content[:4096].decode("ascii", "ignore")
    m = re.search(r"""<meta[^>]+charset=["']?([\w-]+)""", head, re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8"]:
        try:
            return r.content.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return r.content.decode("utf-8", "replace")


def needs_render(rec: dict) -> bool:
    return rec.get("status") == 200 and "raw_word_count" in rec and rec["raw_word_count"] < 60 and rec.get("script_count", 0) >= 3


def rerender(rec: dict, renderer: Renderer, site_host: str) -> dict:
    """Main-thread only: Playwright's sync objects are bound to their creating thread."""
    html = renderer.render(rec["final_url"])
    if not html:
        return rec
    facts = parse_page(rec["final_url"], html, site_host)
    if facts["word_count"] <= rec.get("word_count", 0):
        return rec
    return rec | facts | {"rendered": True, "js_dependent": True}


def crawl(start_url: str, max_pages: int = 60, max_depth: int = 5, workers: int = 6, render_mode: str = "auto", time_budget: int = 600, log=print) -> dict:
    if not re.match(r"^https?://", start_url):
        start_url = "https://" + start_url
    start = normalize_url(start_url)
    host = urlparse(start).netloc
    if not public_host(host.split(":")[0]):
        raise SystemExit(f"Refusing to crawl {host}: it does not resolve to a public address.")

    fetcher = Fetcher()
    home = fetcher.get(start)
    if home is None:
        raise SystemExit(f"Could not reach {start}.")
    final_home = normalize_url(home.url)
    origin = f"{urlparse(final_home).scheme}://{urlparse(final_home).netloc}"
    site = host_key(urlparse(final_home).netloc)
    log(f"homepage {start} -> {final_home} (HTTP {home.status_code})")

    robots = read_robots(fetcher, origin)
    parser = robots.pop("_parser")
    if robots["crawl_delay"]:
        fetcher.delay = min(float(robots["crawl_delay"]), 5.0)
        workers = 1
    sitemap_urls = robots["sitemaps"] or [origin + "/sitemap.xml"]
    sitemaps = read_sitemaps(fetcher, sitemap_urls)
    in_sitemap = {u for u in sitemaps["urls"] if host_key(urlparse(u).netloc) == site}
    log(f"robots.txt {'found' if robots['present'] else 'missing'}; sitemap URLs {sitemaps['total_urls']}")

    # Site-level probes: HTTP to HTTPS, host variant, soft 404, llms.txt
    probes = {}
    http_home = "http://" + urlparse(final_home).netloc + "/"
    r = fetcher.get(http_home)
    probes["http_to_https"] = bool(r is not None and r.url.startswith("https://"))
    probes["http_redirect_status"] = r.history[0].status_code if r is not None and r.history else None
    alt = urlparse(final_home).netloc
    alt = alt[4:] if alt.startswith("www.") else "www." + alt
    r = fetcher.get(f"{urlparse(final_home).scheme}://{alt}/")
    probes["host_variant"] = {"host": alt, "status": r.status_code if r is not None else None, "redirect_status": r.history[0].status_code if r is not None and r.history else None, "redirects_to_canonical_host": bool(r is not None and host_key(urlparse(r.url).netloc) == site and urlparse(r.url).netloc == urlparse(final_home).netloc)}
    junk = "".join(random.choices(string.ascii_lowercase, k=14))
    r = fetcher.get(f"{origin}/jevseo-{junk}-not-found")
    probes["not_found_status"] = r.status_code if r is not None else None
    r = fetcher.get(origin + "/llms.txt")
    probes["llms_txt"] = bool(r is not None and r.status_code == 200 and "html" not in r.headers.get("content-type", "") and len(r.text.strip()) > 20)

    renderer = Renderer() if render_mode != "never" else None
    pages: dict[str, dict] = {}
    depth: dict[str, int] = {final_home: 0}
    queue = deque([final_home])
    blocked: list[str] = []
    for u in sorted(in_sitemap, key=len):
        depth.setdefault(u, 99)
    sitemap_seed = deque(sorted(in_sitemap - {final_home}, key=len))
    deadline = time.monotonic() + time_budget

    def allowed(u: str) -> bool:
        return parser.can_fetch(USER_AGENT, u) if robots["present"] else True

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while (queue or sitemap_seed) and len(pages) < max_pages and time.monotonic() < deadline:
            batch = []
            while queue and len(batch) + len(pages) < max_pages and len(batch) < workers * 2:
                u = queue.popleft()
                if u in pages or SKIP_EXT.search(urlparse(u).path):
                    continue
                if not allowed(u):
                    blocked.append(u)
                    pages[u] = {"url": u, "status": None, "error": "blocked by robots.txt", "depth": depth.get(u)}
                    continue
                batch.append(u)
                pages[u] = {}
            if not batch:
                # Link discovery ran dry: fall back to sitemap URLs the links never reached.
                while sitemap_seed and len(queue) < workers * 2:
                    u = sitemap_seed.popleft()
                    if u not in pages:
                        queue.append(u)
                continue
            results = list(pool.map(lambda u: fetch_page(fetcher, u, site), batch))
            if renderer and renderer.available is not False:
                results = [rerender(rec, renderer, site) if render_mode == "always" and rec.get("status") == 200 and "word_count" in rec or needs_render(rec) else rec for rec in results]
            for rec in results:
                u = rec["url"]
                rec["depth"] = depth.get(u, 99)
                target = rec.get("final_url") or u
                if target != u:
                    # Keep the redirect as its own record; the content belongs to the target only.
                    pages[u] = {k: rec.get(k) for k in ("url", "status", "final_url", "redirect_chain", "fetched_at", "depth")} | {
                        "kind": "redirect",
                        "status": rec["redirect_chain"][0]["status"] if rec.get("redirect_chain") else rec.get("status"),
                        "final_status": rec.get("status"),
                        "in_sitemap": u in in_sitemap,
                    }
                    if target in pages or host_key(urlparse(target).netloc) != site:
                        continue
                    depth[target] = min(depth.get(target, 99), rec["depth"])
                    rec = rec | {"url": target, "reached_via": u, "depth": depth[target]}
                    u = target
                rec["kind"] = "page"
                rec["in_sitemap"] = u in in_sitemap
                pages[u] = rec
                for link in rec.get("links_internal", []):
                    v = link["url"]
                    if urlparse(v).query and len(pages) > max_pages // 2:
                        continue
                    if v not in depth or depth[v] > rec["depth"] + 1:
                        depth[v] = min(depth.get(v, 99), rec["depth"] + 1)
                    if v not in pages and v not in queue and depth[v] <= max_depth:
                        queue.append(v)
            rendered = sum(1 for p in pages.values() if p.get("rendered"))
            log(f"crawled {len(pages)}/{max_pages} URLs, {len(queue)} queued" + (f", {rendered} rendered with JavaScript" if rendered else ""))
    if renderer:
        renderer.close()
    hit_time = time.monotonic() >= deadline
    hit_cap = sum(1 for p in pages.values() if p.get("kind") != "redirect") >= max_pages or len(pages) >= max_pages

    # Inlinks and link status for internal targets never crawled (bounded HEAD checks).
    inlinks: dict[str, int] = {}
    anchors: dict[str, list[str]] = {}
    for rec in pages.values():
        for link in {l["url"]: l for l in rec.get("links_internal", [])}.values():
            if link["url"] != rec["url"]:
                inlinks[link["url"]] = inlinks.get(link["url"], 0) + 1
                if link["anchor"]:
                    anchors.setdefault(link["url"], []).append(link["anchor"])
    redirect_to = {u: p["final_url"] for u, p in pages.items() if p.get("kind") == "redirect" and p.get("final_url")}
    for src, n in list(inlinks.items()):
        target = redirect_to.get(src)
        if target and target != src:
            inlinks[target] = inlinks.get(target, 0) + n
            anchors.setdefault(target, []).extend(anchors.get(src, []))
    # A link is broken when its final destination fails; robots-blocked targets are unknown, not broken.
    status_of = {}
    for u, p in pages.items():
        if p.get("error") == "blocked by robots.txt":
            status_of[u] = "blocked"
        elif p.get("kind") == "redirect":
            final = p.get("final_status")
            status_of[u] = final if final is None or final >= 400 else p.get("status")
        else:
            status_of[u] = p.get("status")
    log("checking link targets and a sample of outbound links")
    unchecked = [u for u in inlinks if u not in status_of and not SKIP_EXT.search(urlparse(u).path) and allowed(u)][:150]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for u, st in zip(unchecked, pool.map(fetcher.head, unchecked)):
            status_of[u] = st
    externals = list(dict.fromkeys(l["url"] for p in pages.values() for l in p.get("links_external", [])))
    ext_sample = externals[:80]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        ext_status = dict(zip(ext_sample, pool.map(fetcher.head, ext_sample)))
    for p in pages.values():
        u = p.get("url")
        p["inlinks"] = inlinks.get(u, 0)
        p["inlink_anchors"] = sorted(set(anchors.get(u, [])))[:15]

    home_rec = pages.get(final_home, {})
    return {
        "input_url": start_url,
        "start_url": start,
        "final_url": final_home,
        "origin": origin,
        "domain": site,
        "https": final_home.startswith("https://"),
        "robots": robots,
        "sitemaps": sitemaps,
        "probes": probes,
        "pages": list(pages.values()),
        "link_status": status_of,
        "external_status": ext_status,
        "external_total": len(externals),
        "blocked_by_robots": blocked,
        "render": {"mode": render_mode, "browser_available": renderer.available if renderer else None, "homepage_rendered": home_rec.get("rendered", False)},
        "requests": fetcher.requests,
        "limits": {"max_pages": max_pages, "max_depth": max_depth, "time_budget_s": time_budget, "hit_page_cap": hit_cap, "hit_time_budget": hit_time},
    }

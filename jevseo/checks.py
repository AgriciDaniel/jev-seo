"""Deterministic checks. Code decides anything a count, a status code or a string match can decide.

Each finding names the rule, the affected URLs, the measured evidence, the fix
and a primary source. Rules marked `heuristic` are editorial conventions, not
search engine requirements, and the report says so.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

from jevseo.parse import normalize_url

G = "https://developers.google.com/search/docs/"
SRC = {
    "robots": G + "crawling-indexing/robots/intro",
    "sitemaps": G + "crawling-indexing/sitemaps/overview",
    "http": "https://developers.google.com/crawling/docs/troubleshooting/http-status-codes",
    "redirects": G + "crawling-indexing/301-redirects",
    "canonical": G + "crawling-indexing/consolidate-duplicate-urls",
    "noindex": G + "crawling-indexing/block-indexing",
    "links": G + "crawling-indexing/links-crawlable",
    "js": G + "crawling-indexing/javascript/javascript-seo-basics",
    "title": G + "appearance/title-link",
    "snippet": G + "appearance/snippet",
    "images": G + "appearance/google-images",
    "sd": G + "appearance/structured-data/intro-structured-data",
    "sd_general": G + "appearance/structured-data/sd-policies",
    "hreflang": G + "specialty/international/localized-versions",
    "mobile": G + "crawling-indexing/mobile/mobile-sites-mobile-first-indexing",
    "helpful": G + "fundamentals/creating-helpful-content",
    "starter": G + "fundamentals/seo-starter-guide",
    "https": G + "appearance/page-experience",
    "ai": G + "appearance/ai-features",  # Google: no special optimization is required for AI features
    "broken": "https://developers.google.com/crawling/docs/troubleshooting/http-status-codes",
    "soft404": "https://developers.google.com/crawling/docs/troubleshooting/http-status-codes",
    "og": "https://ogp.me/",
    "hsts": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Strict-Transport-Security",
    "headers": "https://owasp.org/projects/secure-headers-project",
    "mixed": "https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Mixed_content",
    "cls": "https://web.dev/articles/optimize-cls",
    "ttfb": "https://web.dev/articles/ttfb",
    "cwv": "https://web.dev/articles/vitals",
    "llms": "https://llmstxt.org/",
    "crawlers_google": "https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers",
    "lang": "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Global_attributes/lang",
    "dfs_labs": "https://docs.dataforseo.com/v3/dataforseo_labs/overview/",
    "dfs_backlinks": "https://docs.dataforseo.com/v3/backlinks/overview/",
    "dfs_serp": "https://docs.dataforseo.com/v3/serp/overview/",
}

CATEGORIES = {
    "crawl": "Crawl and indexing",
    "onpage": "On-page",
    "content": "Content quality",
    "links": "Links and architecture",
    "structured": "Structured data and sharing",
    "ai": "AI search readiness",
    "performance": "Performance",
    "security": "Security and trust",
    "visibility": "Search visibility and authority",
}
SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1, "info": 0}
GENERIC_ANCHORS = {"click here", "here", "read more", "learn more", "more", "this", "link", "go", "details", "continue", "see more", "view more"}

# id: (category, severity, title, fix, source key, effort 1-4, heuristic)
RULES = {
    "robots_missing": ("crawl", "low", "No robots.txt file", "Publish a robots.txt at the site root that allows crawling and lists the sitemap.", "robots", 1, False),
    "robots_blocks_site": ("crawl", "critical", "robots.txt blocks search crawlers from the whole site", "Remove the site-wide Disallow for search engine user agents.", "robots", 1, False),
    "sitemap_missing": ("crawl", "medium", "No XML sitemap found", "Generate an XML sitemap of canonical, indexable URLs and reference it in robots.txt.", "sitemaps", 2, False),
    "sitemap_errors": ("crawl", "medium", "Sitemap file unreachable or invalid", "Fix the sitemap URL so it returns HTTP 200 with valid XML.", "sitemaps", 1, False),
    "sitemap_bad_urls": ("crawl", "medium", "Sitemap lists URLs that redirect, fail or are noindex", "List only final, indexable, HTTP 200 URLs in the sitemap.", "sitemaps", 2, False),
    "not_in_sitemap": ("crawl", "low", "Indexable pages missing from the sitemap", "Add these canonical pages to the sitemap.", "sitemaps", 1, False),
    "http_errors": ("crawl", "high", "Pages returning HTTP errors", "Restore these URLs or redirect them to the closest live equivalent, and update links.", "http", 2, False),
    "broken_internal_links": ("links", "high", "Internal links pointing to broken URLs", "Update or remove links that point to 4xx, 5xx or unreachable URLs.", "broken", 2, False),
    "redirect_chains": ("crawl", "medium", "Redirect chains (more than one hop)", "Point each redirect straight at its final URL.", "redirects", 1, False),
    "links_to_redirects": ("links", "low", "Internal links that go through a redirect", "Link directly to the final URL.", "redirects", 1, False),
    "noindex": ("crawl", "high", "Pages excluded from search with noindex", "Confirm each noindex is intended; remove it from pages that should rank.", "noindex", 1, False),
    "canonical_missing": ("crawl", "low", "Pages without a canonical link", "Add a self-referencing rel=canonical to each indexable page.", "canonical", 1, False),
    "canonical_elsewhere": ("crawl", "medium", "Canonical points to a different URL", "Check that these pages really are duplicates of their canonical target; otherwise self-canonicalise.", "canonical", 1, False),
    "canonical_broken": ("crawl", "high", "Canonical target redirects or returns an error", "Point canonicals at live, indexable URLs.", "canonical", 1, False),
    "soft_404": ("crawl", "medium", "Missing pages return HTTP 200 (soft 404)", "Return a real 404 or 410 status for URLs that do not exist.", "soft404", 2, False),
    "host_temporary_redirect": ("crawl", "low", "Host or HTTPS redirect is temporary (302 or 307)", "Use a permanent redirect (301 or 308) for www, non-www and HTTP to HTTPS, so search engines consolidate on one host.", "redirects", 1, False),
    "host_variant": ("crawl", "medium", "www and non-www both serve the site", "Redirect the alternate host to the preferred host with a permanent redirect.", "canonical", 1, False),
    "no_https": ("security", "high", "Site not served over HTTPS, or HTTP does not redirect to HTTPS", "Serve every page over HTTPS and permanently redirect HTTP to HTTPS.", "https", 2, False),
    "deep_pages": ("links", "low", "Pages more than three clicks from the homepage", "Link important deep pages from hubs or navigation closer to the homepage.", "links", 2, True),
    "orphan_pages": ("links", "medium", "Sitemap pages with no internal links (orphans)", "Link these pages from relevant pages so users and crawlers can reach them.", "links", 2, False),
    "js_dependent": ("crawl", "medium", "Content only appears after JavaScript runs", "Server-render or pre-render primary content and links.", "js", 4, False),
    "title_missing": ("onpage", "high", "Pages without a title", "Write a unique, descriptive title for each page.", "title", 1, False),
    "title_duplicate": ("onpage", "medium", "Duplicate titles across pages", "Give each page a title that distinguishes it from the others.", "title", 1, False),
    "title_length": ("onpage", "low", "Very short or very long titles", "Aim for a concise, descriptive title. Google truncates by pixel width, so there is no fixed limit; 15 to 65 characters is a display convention.", "title", 1, True),
    "multiple_titles": ("onpage", "low", "More than one title element", "Keep a single title element in the head.", "title", 1, False),
    "meta_missing": ("onpage", "medium", "Pages without a meta description", "Write a page-specific summary. Google may still generate its own snippet.", "snippet", 1, False),
    "meta_duplicate": ("onpage", "low", "Duplicate meta descriptions", "Write a distinct description for each page.", "snippet", 1, False),
    "h1_missing": ("onpage", "medium", "Pages without an H1 heading", "Give each page one visible main heading that states its topic.", "starter", 1, True),
    "h1_multiple": ("onpage", "low", "Pages with several H1 headings", "Use one main heading and H2 or lower for sections.", "starter", 1, True),
    "heading_skips": ("onpage", "low", "Heading levels skipped", "Nest headings in order (H2 under H1, H3 under H2).", "starter", 1, True),
    "lang_missing": ("onpage", "low", "HTML lang attribute missing", "Declare the page language on the html element.", "lang", 1, False),
    "viewport_missing": ("onpage", "high", "No mobile viewport meta tag", "Add a responsive viewport meta tag.", "mobile", 1, False),
    "thin_content": ("content", "medium", "Pages with very little main content", "Expand pages that should rank with substance a visitor needs, or consolidate them. Word count is a warning sign, not a ranking factor.", "helpful", 3, True),
    "duplicate_content": ("content", "medium", "Pages with identical main text", "Consolidate duplicates or canonicalise them to one URL.", "canonical", 2, False),
    "images_alt": ("onpage", "medium", "Images without alt attributes", "Add alt text that describes informative images; use empty alt for decorative ones.", "images", 2, False),
    "images_dimensions": ("performance", "low", "Images without width and height", "Set width and height so layout does not shift while images load.", "cls", 1, False),
    "no_structured_data": ("structured", "medium", "No structured data on the homepage", "Add JSON-LD describing the organisation and website (for example Organization and WebSite).", "sd", 2, False),
    "jsonld_errors": ("structured", "high", "Structured data that fails to parse", "Fix the JSON-LD syntax so search engines can read it.", "sd_general", 1, False),
    "og_missing": ("structured", "low", "Open Graph title or image missing", "Add og:title, og:description and og:image for link previews.", "og", 1, False),
    "hreflang_issues": ("structured", "medium", "hreflang annotations incomplete", "Each language version needs a self-reference and return links; add x-default where useful.", "hreflang", 2, False),
    "ai_bots_blocked": ("ai", "info", "AI crawlers blocked in robots.txt", "Decide deliberately. Blocking Google-Extended does not affect Google Search; blocking search-oriented AI bots can remove the site from those answer engines.", "crawlers_google", 1, False),
    "llms_txt_missing": ("ai", "info", "No llms.txt file", "Optional. llms.txt is a community proposal, not a search engine requirement.", "llms", 1, True),
    "hsts_missing": ("security", "low", "No Strict-Transport-Security header", "Send an HSTS header once HTTPS is stable everywhere.", "hsts", 1, False),
    "security_headers": ("security", "low", "Common security headers missing", "Add X-Content-Type-Options, a Referrer-Policy and a frame policy.", "headers", 1, False),
    "mixed_content": ("security", "high", "HTTPS pages loading HTTP resources", "Load every resource over HTTPS.", "mixed", 1, False),
    "favicon_missing": ("security", "low", "No favicon declared", "Declare a favicon; Google shows it beside results.", "starter", 1, False),
    "slow_ttfb": ("performance", "medium", "Slow server response (TTFB above 0.8 s)", "Cache pages, use a CDN and reduce server work before the first byte.", "ttfb", 3, False),
    "heavy_html": ("performance", "low", "Very large HTML documents (over 500 KB)", "Trim inline data and markup that ships with every page.", "cwv", 2, True),
    "generic_anchors": ("links", "low", "Internal links with generic anchor text", "Use anchor text that describes the destination.", "links", 1, False),
    "broken_external_links": ("links", "low", "External links returning errors", "Update or remove outbound links that no longer resolve.", "broken", 1, False),
}


def finding(rule_id: str, urls: list[str], evidence: str, detail: dict | None = None, severity: str | None = None, fix: str | None = None) -> dict:
    cat, sev, title, default_fix, src, effort, heuristic = RULES[rule_id]
    fix = fix or default_fix
    return {
        "id": rule_id,
        "origin": "rule",
        "category": cat,
        "severity": severity or sev,
        "title": title,
        "fix": fix,
        "source": SRC[src],
        "effort": effort,
        "heuristic": heuristic,
        "urls": urls,
        "count": len(urls),
        "evidence": re.sub(r"\b1 ((?:indexable |sitemap |crawled )?)(page|image|description|title|group|link)s\b", r"1 \1\2", evidence),
        "detail": detail or {},
    }


def html_pages(crawl: dict) -> list[dict]:
    return [p for p in crawl["pages"] if p.get("kind") == "page" and p.get("status") == 200 and "word_count" in p]


def indexable(p: dict) -> bool:
    robots = f"{p.get('meta_robots') or ''} {p.get('x_robots') or ''}".lower()
    canonical = p.get("canonical")
    return "noindex" not in robots and (not canonical or canonical == p["url"])


def run_checks(crawl: dict) -> list[dict]:
    out: list[dict] = []
    pages = html_pages(crawl)
    by_url = {p["url"]: p for p in crawl["pages"]}
    robots, sm, probes = crawl["robots"], crawl["sitemaps"], crawl["probes"]
    status = crawl["link_status"]
    home = crawl["final_url"]

    # Crawl and indexing
    if not robots["present"]:
        out.append(finding("robots_missing", [robots["url"]], f"robots.txt returned {robots['status']}"))
    blocked = [b for b, ok in robots["search_bots"].items() if not ok]
    if robots["present"] and (robots["disallow_all"] or blocked):
        out.append(finding("robots_blocks_site", [robots["url"]], f"Blocked at /: {', '.join(blocked) or 'all user agents'}"))
    good_sm = [f for f in sm["files"] if not f["error"]]
    bad_sm = [f for f in sm["files"] if f["error"]]
    if not good_sm:
        out.append(finding("sitemap_missing", [f["url"] for f in sm["files"]], "No reachable XML sitemap in robots.txt or at /sitemap.xml"))
    elif bad_sm:
        out.append(finding("sitemap_errors", [f["url"] for f in bad_sm], "; ".join(f"{f['url']}: {f['error']}" for f in bad_sm)))
    if good_sm:
        in_sm = set(sm["urls"])
        bad = [u for u in in_sm if u in by_url and (by_url[u].get("kind") == "redirect" or (by_url[u].get("status") or 0) >= 400 or (by_url[u].get("kind") == "page" and "word_count" in by_url[u] and not indexable(by_url[u])))]
        if bad:
            out.append(finding("sitemap_bad_urls", sorted(bad), f"{len(bad)} of the crawled sitemap URLs are not final indexable pages"))
        missing = [p["url"] for p in pages if indexable(p) and not p.get("in_sitemap")]
        if missing:
            out.append(finding("not_in_sitemap", missing, f"{len(missing)} crawled indexable pages are not listed"))

    errors = [p for p in crawl["pages"] if p.get("kind") != "redirect" and (p.get("status") is None and p.get("error") != "blocked by robots.txt" or (p.get("status") or 0) >= 400)]
    if errors:
        out.append(finding("http_errors", [p["url"] for p in errors], ", ".join(f"{p.get('status') or p.get('error')}" for p in errors[:10])))

    broken_src = defaultdict(set)
    redirect_src = defaultdict(set)
    generic = defaultdict(set)
    for p in pages:
        for link in p["links_internal"]:
            st = status.get(link["url"])
            if link["url"] in by_url and by_url[link["url"]].get("kind") == "redirect":
                redirect_src[p["url"]].add(link["url"])
            if link["url"] in status and (st is None or (isinstance(st, int) and st >= 400)):
                broken_src[link["url"]].add(p["url"])
            if generic_anchor(link["anchor"]):
                generic[p["url"]].add(link["anchor"].strip())
    if broken_src:
        out.append(finding("broken_internal_links", sorted({s for v in broken_src.values() for s in v}), f"{len(broken_src)} broken targets: " + "; ".join(f"{status.get(t) or 'unreachable'} {t} (linked from {', '.join(urlparse(x).path or '/' for x in sorted(src)[:2])})" for t, src in list(broken_src.items())[:4]), {"targets": {k: sorted(v)[:10] for k, v in list(broken_src.items())[:50]}, "status": {k: status.get(k) for k in broken_src}}))
    if redirect_src:
        def rel(u: str) -> str:
            q = urlparse(u)
            return (q.path or "/") if q.netloc == urlparse(home).netloc else q.netloc + (q.path or "/")

        pairs = [f"{rel(src)} links to {rel(t)} (redirects to {rel(by_url[t]['final_url'])})" for src, targets in redirect_src.items() for t in sorted(targets)]
        out.append(finding("links_to_redirects", sorted(redirect_src), "; ".join(pairs[:5]) + (f"; and {len(pairs) - 5} more" if len(pairs) > 5 else "")))
    if generic:
        out.append(finding("generic_anchors", sorted(generic), "Anchors such as: " + ", ".join(sorted({a for v in generic.values() for a in v})[:8])))

    chains = [p for p in crawl["pages"] if len(p.get("redirect_chain") or []) > 1]
    if chains:
        out.append(finding("redirect_chains", [p["url"] for p in chains], "; ".join(f"{p['url']} ({len(p['redirect_chain'])} hops)" for p in chains[:5])))

    noindex = [p for p in pages if "noindex" in f"{p.get('meta_robots') or ''} {p.get('x_robots') or ''}".lower()]
    if noindex:
        sev = "critical" if any(p["url"] == home for p in noindex) else None
        out.append(finding("noindex", [p["url"] for p in noindex], f"{len(noindex)} pages carry noindex", severity=sev))
    no_canon = [p["url"] for p in pages if not p.get("canonical")]
    if no_canon:
        out.append(finding("canonical_missing", no_canon, f"{len(no_canon)} of {len(pages)} pages"))
    elsewhere = [p for p in pages if p.get("canonical") and p["canonical"] != p["url"]]
    if elsewhere:
        out.append(finding("canonical_elsewhere", [p["url"] for p in elsewhere], "; ".join(f"{p['url']} -> {p['canonical']}" for p in elsewhere[:5])))
    def canon_bad(target: str) -> bool:
        rec = by_url.get(target, {})
        st = rec.get("status") if rec else status.get(target)
        return rec.get("kind") == "redirect" or (isinstance(st, int) and st >= 400)

    broken_canon = [p for p in elsewhere if canon_bad(p["canonical"])]
    if broken_canon:
        out.append(finding("canonical_broken", [p["url"] for p in broken_canon], "; ".join(p["canonical"] for p in broken_canon[:5])))
    if probes["not_found_status"] == 200:
        out.append(finding("soft_404", [crawl["origin"] + "/jevseo-…-not-found"], "A random nonexistent URL returned HTTP 200"))
    hv = probes["host_variant"]
    if hv["status"] == 200 and not hv["redirects_to_canonical_host"]:
        out.append(finding("host_variant", [f"https://{hv['host']}/"], f"{hv['host']} answers without redirecting to the preferred host"))
    temp = [f"{label} answered {st}" for label, st in (("HTTP to HTTPS", probes.get("http_redirect_status")), (hv["host"], hv.get("redirect_status"))) if st in (302, 303, 307)]
    if temp:
        out.append(finding("host_temporary_redirect", [home], "; ".join(temp)))
    if not crawl["https"] or not probes["http_to_https"]:
        out.append(finding("no_https", [home], "Homepage over HTTPS: %s; HTTP redirects to HTTPS: %s" % (crawl["https"], probes["http_to_https"])))
    deep = [p["url"] for p in pages if 3 < p.get("depth", 0) < 99]
    if deep:
        out.append(finding("deep_pages", deep, f"{len(deep)} pages deeper than three clicks"))
    orphans = [p["url"] for p in pages if p.get("in_sitemap") and p.get("inlinks", 0) == 0 and p["url"] != home]
    if orphans:
        out.append(finding("orphan_pages", orphans, f"{len(orphans)} sitemap pages received no internal links from the crawled pages: " + ", ".join(urlparse(u).path or "/" for u in orphans[:6])))
    js = [p["url"] for p in pages if p.get("js_dependent")]
    if js:
        out.append(finding("js_dependent", js, f"{len(js)} pages had under 60 words in raw HTML and more after rendering"))

    # On-page
    titles = defaultdict(list)
    metas = defaultdict(list)
    texts = defaultdict(list)
    for p in pages:
        if p.get("title"):
            titles[p["title"].strip().lower()].append(p["url"])
        if p.get("meta_description"):
            metas[p["meta_description"].strip().lower()].append(p["url"])
        if p["word_count"] >= 50:
            texts[p["text_hash"]].append(p["url"])
    ix = [p for p in pages if indexable(p)]
    miss = [p["url"] for p in ix if not p.get("title")]
    if miss:
        out.append(finding("title_missing", miss, f"{len(miss)} indexable pages"))
    dup = {t: u for t, u in titles.items() if len(u) > 1}
    if dup:
        out.append(finding("title_duplicate", sorted({x for u in dup.values() for x in u}), f"{len(dup)} titles shared by several pages", {"groups": [{"title": t, "urls": u} for t, u in list(dup.items())[:30]]}))
    odd = [p for p in ix if p.get("title") and not 15 <= len(p["title"]) <= 65]
    if odd:
        out.append(finding("title_length", [p["url"] for p in odd], "; ".join(f"{len(p['title'])} chars" for p in odd[:8])))
    multi = [p["url"] for p in pages if p.get("title_count", 0) > 1]
    if multi:
        out.append(finding("multiple_titles", multi, f"{len(multi)} pages"))
    miss = [p["url"] for p in ix if not p.get("meta_description")]
    if miss:
        out.append(finding("meta_missing", miss, f"{len(miss)} indexable pages"))
    dup = {t: u for t, u in metas.items() if len(u) > 1}
    if dup:
        out.append(finding("meta_duplicate", sorted({x for u in dup.values() for x in u}), f"{len(dup)} descriptions shared by several pages"))
    miss = [p["url"] for p in ix if not p.get("h1")]
    if miss:
        out.append(finding("h1_missing", miss, f"{len(miss)} indexable pages"))
    multi = [p["url"] for p in ix if len(p.get("h1") or []) > 1]
    if multi:
        out.append(finding("h1_multiple", multi, f"{len(multi)} pages"))
    skips = [p["url"] for p in ix if p.get("heading_skips")]
    if skips:
        out.append(finding("heading_skips", skips, f"{len(skips)} pages skip a heading level"))
    miss = [p["url"] for p in pages if not p.get("lang")]
    if miss:
        out.append(finding("lang_missing", miss, f"{len(miss)} pages"))
    miss = [p["url"] for p in pages if not p.get("viewport")]
    if miss:
        out.append(finding("viewport_missing", miss, f"{len(miss)} pages"))
    thin = [p for p in ix if p["word_count"] < 150]
    if thin:
        out.append(finding("thin_content", [p["url"] for p in thin], "; ".join(f"{urlparse(p['url']).path or '/'}: {p['word_count']} words" for p in thin[:8]), {"word_counts": {p["url"]: p["word_count"] for p in thin}}))
    dup = {h: u for h, u in texts.items() if len(u) > 1}
    if dup:
        out.append(finding("duplicate_content", sorted({x for u in dup.values() for x in u}), f"{len(dup)} groups of pages with identical main text", {"groups": list(dup.values())[:20]}))
    alt = [p for p in pages if p["images"]["missing_alt"]]
    if alt:
        total = sum(p["images"]["missing_alt"] for p in alt)
        out.append(finding("images_alt", [p["url"] for p in alt], f"{total} images without alt across {len(alt)} pages", {"samples": [s for p in alt for s in p["images"]["missing_alt_samples"]][:15]}))
    dims = [p for p in pages if p["images"]["no_dimensions"]]
    if dims:
        out.append(finding("images_dimensions", [p["url"] for p in dims], f"{sum(p['images']['no_dimensions'] for p in dims)} images without explicit size"))

    # Structured data and sharing
    home_rec = by_url.get(home, {})
    if home_rec and not home_rec.get("schema_types"):
        out.append(finding("no_structured_data", [home], "No JSON-LD or microdata types on the homepage"))
    errs = [p for p in pages if p.get("schema_errors")]
    if errs:
        out.append(finding("jsonld_errors", [p["url"] for p in errs], "; ".join(e for p in errs[:3] for e in p["schema_errors"][:1])))
    og = [p["url"] for p in ix if not (p.get("og") or {}).get("title") or not (p.get("og") or {}).get("image")]
    if og:
        out.append(finding("og_missing", og, f"{len(og)} pages lack og:title or og:image"))
    hl = [p for p in pages if p.get("hreflang")]
    bad_hl = [p["url"] for p in hl if p["url"] not in {normalize_url(h["href"]) for h in p["hreflang"] if h.get("href")}]
    if bad_hl:
        out.append(finding("hreflang_issues", bad_hl, f"{len(bad_hl)} pages with hreflang but no self-reference"))

    # AI search readiness (deterministic part)
    blocked_ai = [b for b, ok in robots["ai_bots"].items() if not ok]
    if blocked_ai:
        out.append(finding("ai_bots_blocked", [robots["url"]], "Blocked: " + ", ".join(blocked_ai), {"blocked": blocked_ai}))
    if not probes["llms_txt"]:
        out.append(finding("llms_txt_missing", [crawl["origin"] + "/llms.txt"], "No llms.txt at the site root"))

    # Security and trust
    if crawl["https"] and home_rec and "strict-transport-security" not in (home_rec.get("headers") or {}):
        out.append(finding("hsts_missing", [home], "Homepage response has no HSTS header"))
    missing_h = [h for h in ("x-content-type-options", "referrer-policy") if h not in (home_rec.get("headers") or {})]
    if home_rec and "x-frame-options" not in (home_rec.get("headers") or {}) and "frame-ancestors" not in ((home_rec.get("headers") or {}).get("content-security-policy") or ""):
        missing_h.append("x-frame-options or CSP frame-ancestors")
    if home_rec and missing_h:
        out.append(finding("security_headers", [home], "Missing on the homepage response: " + ", ".join(missing_h), fix="Add the missing headers: " + ", ".join(missing_h) + "."))
    mixed = [p for p in pages if p.get("mixed_content")]
    if mixed:
        out.append(finding("mixed_content", [p["url"] for p in mixed], "; ".join(p["mixed_content"][0] for p in mixed[:5])))
    if home_rec and not home_rec.get("favicon"):
        out.append(finding("favicon_missing", [home], "No link rel=icon on the homepage"))

    # Performance (crawl-observed)
    slow = [p for p in pages if (p.get("ttfb_ms") or 0) > 800]
    if slow:
        out.append(finding("slow_ttfb", [p["url"] for p in slow], "; ".join(f"{urlparse(p['url']).path or '/'}: {p['ttfb_ms']} ms" for p in slow[:6])))
    heavy = [p for p in pages if (p.get("bytes") or 0) > 500_000]
    if heavy:
        out.append(finding("heavy_html", [p["url"] for p in heavy], "; ".join(f"{urlparse(p['url']).path or '/'}: {p['bytes'] // 1024} KB" for p in heavy[:6])))
    ext_bad = [u for u, st in crawl["external_status"].items() if st is not None and st >= 400 and st not in (401, 403, 429, 999)]
    if ext_bad:
        out.append(finding("broken_external_links", ext_bad, f"{len(ext_bad)} of {len(crawl['external_status'])} sampled outbound links"))
    return out


def passed_rules(findings: list[dict]) -> list[str]:
    hit = {f["id"] for f in findings}
    return [r for r in RULES if r not in hit]


def generic_anchor(anchor: str) -> bool:
    return re.sub(r"\W+", " ", anchor).strip().lower() in GENERIC_ANCHORS

"""Turn rule findings and Jev judgments into category scores and a ranked action list.

Every number here is a transparent internal rubric, not a ranking or traffic
prediction. The formulas are printed in the report's method section.
"""
from __future__ import annotations

from statistics import mean
from urllib.parse import urlparse

from jevseo.checks import CATEGORIES, SEVERITY_WEIGHT, SRC, html_pages

DEDUCT = {"critical": 25, "high": 12, "medium": 6, "low": 2, "info": 0}
CATEGORY_WEIGHT = {"crawl": 20, "onpage": 15, "content": 20, "links": 10, "structured": 8, "ai": 12, "performance": 10, "security": 5, "visibility": 15}
JUDGED_SHARE = 0.7  # content and AI readiness: 70% Jev judgment, 30% rules

# id: (category, severity, title, fix, source key, effort)
JEV_RULES = {
    "jev_value_prop": ("content", "high", "Homepage does not make the offer clear", "State what you offer, for whom, and why choose you in the first screen of the homepage.", "helpful", 2),
    "jev_entity_clarity": ("ai", "medium", "Homepage does not state who, what and where plainly", "Say the organisation's name, what it does and its market or location in plain words near the top. Editorial heuristic: Google states no special optimization is required for its AI features.", "ai", 1),
    "jev_local_schema": ("structured", "medium", "Local business without LocalBusiness structured data", "Add LocalBusiness JSON-LD with name, address, phone and opening hours that match the page.", "sd", 2),
    "jev_helpfulness": ("content", "high", "Important pages that do not satisfy the visitor", "Expand these pages with the substance a visitor needs: answers, specifics, examples and next steps.", "helpful", 3),
    "jev_specificity": ("content", "medium", "Generic content that any competitor could publish", "Add first-hand specifics: your own numbers, processes, examples, locations, names and results.", "helpful", 3),
    "jev_trust": ("content", "medium", "Key pages show little evidence of expertise or trust", "Add named people, credentials, reviews, sources, results and contact details where they help the reader.", "helpful", 2),
    "jev_next_step": ("content", "medium", "Commercial pages without a clear next step", "Give each commercial page one obvious, relevant call to action.", "starter", 1),
    "jev_title_fit": ("onpage", "medium", "Titles that do not describe the page well", "Rewrite these titles to name what the page offers in the searcher's words.", "title", 1),
    "jev_meta_fit": ("onpage", "low", "Weak meta descriptions", "Rewrite these descriptions as a specific summary of what the page delivers.", "snippet", 1),
    "jev_h1_fit": ("onpage", "low", "Main headings that do not state the topic", "Make the H1 name the page's topic rather than a slogan.", "starter", 1),
    "jev_answer_first": ("ai", "low", "Pages that bury the main point", "Open with a one or two sentence answer or offer before any preamble. Editorial heuristic for readers and answer engines, not a Google requirement.", "ai", 1),
    "jev_citable": ("ai", "medium", "Few self-contained, quotable facts", "Add clear statements of fact, definitions and figures that make sense on their own. Editorial heuristic, not a Google requirement.", "ai", 2),
    "jev_rewrite": ("content", "medium", "Pages Jev would rewrite or consolidate", "Review each page against the suggested action. This is Jev's editorial judgment, not a search engine rule.", "helpful", 3),
    "jev_cannibalization": ("content", "medium", "Pages competing for the same searches", "Decide one page per search need: merge, differentiate, or canonicalise the weaker page.", "canonical", 2),
}
LOW = 0.45  # normalised Score below this becomes a finding
# Jev findings whose advice is editorial rather than a documented search engine requirement
HEURISTIC_JEV = {"jev_entity_clarity", "jev_answer_first", "jev_citable", "jev_rewrite", "jev_h1_fit", "jev_next_step"}
REACHABLE_KD = 30  # DataForSEO keyword difficulty treated as winnable without major authority (heuristic)
DFS_RULES = {
    "dfs_striking": ("visibility", "medium", "Relevant keywords close to page one", "Strengthen the ranking page for each keyword: answer the search more fully, add internal links to it and tighten its title.", "dfs_labs", 2),
    "dfs_existing_page": ("visibility", "medium", "Relevant keywords an existing page could win", "Expand the named page to cover each keyword's search need, then link to it from related pages.", "dfs_labs", 2),
    "dfs_new_page": ("visibility", "medium", "Relevant keywords with no page to rank", "Plan one page per distinct search need; start with the highest volume, lowest difficulty keywords.", "dfs_labs", 3),
    "dfs_backlink_gap": ("visibility", "medium", "Far fewer referring domains than sites ranking for the same keywords", "Earn links from sites your audience already reads: original data, tools, guest expertise and partner pages.", "dfs_backlinks", 4),
    "dfs_broken_backlinks": ("visibility", "medium", "Backlinks pointing at broken pages", "Redirect each broken target to its closest live page so the links count again.", "dfs_backlinks", 1),
    "dfs_aio_not_cited": ("ai", "low", "AI Overviews that do not cite the site", "Study who is cited today and make sure the page answers the search directly. Google states there are no extra requirements to appear in AI Overviews beyond normal Search eligibility.", "ai", 2),
}
LABEL = {"helpfulness": "helpfulness", "specificity": "specificity", "trust": "trust", "clear_next_step": "P(clear next step)", "title_fit": "title fit",
         "meta_fit": "meta description fit", "h1_fit": "P(H1 states the topic)", "answer_first": "P(opens with the point)", "citable": "citability"}
SITE_LEVEL = {
    "dfs_striking", "dfs_existing_page", "dfs_new_page", "dfs_backlink_gap", "dfs_broken_backlinks", "dfs_aio_not_cited",
    "robots_missing", "robots_blocks_site", "sitemap_missing", "sitemap_errors", "soft_404", "host_variant", "no_https",
    "no_structured_data", "ai_bots_blocked", "llms_txt_missing", "hsts_missing", "security_headers", "favicon_missing",
    "jev_value_prop", "jev_entity_clarity", "jev_local_schema",
}


def reach(f: dict, n_pages: int) -> float:
    return 1.0 if f["id"] in SITE_LEVEL else min(1.0, f["count"] / max(n_pages, 1))


def jev_finding(rule_id: str, urls: list[str], evidence: str, review: int, detail: dict | None = None, severity: str | None = None) -> dict:
    cat, sev, title, fix, src, effort = JEV_RULES[rule_id]
    sev = severity or sev
    return {"id": rule_id, "origin": "jev", "category": cat, "severity": sev, "title": title, "fix": fix, "source": SRC[src], "effort": effort, "heuristic": rule_id in HEURISTIC_JEV, "urls": urls, "count": len(urls), "evidence": evidence, "needs_review": review, "detail": detail or {}}


def jev_findings(crawl: dict, judged: dict) -> list[dict]:
    out = []
    site = judged.get("site") or {}
    pages = judged.get("pages") or {}
    home = crawl["final_url"]
    if site:
        vp = site["value_prop"]
        if vp["value"] < 0.6:
            # An undecided Jev answer is a signal to check, not a headline finding.
            out.append(jev_finding("jev_value_prop", [home], f"Jev value proposition {vp['value']:.2f} (confidence {vp['confidence']:.2f})", int(vp["band"] == "review"),
                                   severity=None if vp["band"] == "act" else "low"))
        ec = site["entity_clarity"]
        if ec["band"] == "no" or (ec["band"] == "review" and ec["value"] < 0.5):
            out.append(jev_finding("jev_entity_clarity", [home], f"Jev P(homepage states who, what and where) {ec['value']:.2f}", int(ec["band"] == "review"),
                                   severity=None if ec["band"] == "no" else "low"))
        local = site["serves_local_area"]
        home_types = " ".join(next((p.get("schema_types", []) for p in crawl["pages"] if p.get("url") == home), [])).lower()
        if local["value"] >= 0.5 and "localbusiness" not in home_types and not any(t in home_types for t in ("restaurant", "store", "dentist", "attorney", "plumber", "medical")):
            out.append(jev_finding("jev_local_schema", [home], f"Serves a local area P(yes) {local['value']:.2f}; homepage schema: {home_types or 'none'}", int(local["band"] == "review")))

    def collect(key, test, only=None):
        urls, review, ev = [], 0, []
        for url, ans in pages.items():
            if not ans or key not in ans or (only and not only(ans)):
                continue
            # Policy and contact pages are not expected to be citable, specific or answer-first.
            if key not in ("title_fit", "h1_fit") and ans["page_type"]["value"] in ("legal_or_policy", "contact_or_location") and ans["page_type"]["band"] == "act":
                continue
            a = ans[key]
            if test(a):
                urls.append(url)
                review += a["band"] == "review"
                ev.append(a["value"])
        return urls, review, ev

    important = lambda ans: ans["importance"]["value"] >= 0.5  # noqa: E731
    commercial = lambda ans: ans["page_type"]["value"] in ("homepage", "product_or_service", "pricing") or ans["intent"]["value"] in ("commercial", "transactional", "local")  # noqa: E731
    specs = [
        ("jev_helpfulness", "helpfulness", lambda a: a["value"] < LOW, important),
        ("jev_specificity", "specificity", lambda a: a["value"] < LOW, None),
        ("jev_trust", "trust", lambda a: a["value"] < LOW, important),
        ("jev_next_step", "clear_next_step", lambda a: a["value"] < 0.5, commercial),
        ("jev_title_fit", "title_fit", lambda a: a["value"] < LOW, None),
        ("jev_meta_fit", "meta_fit", lambda a: a["value"] < LOW, None),
        ("jev_h1_fit", "h1_fit", lambda a: a["value"] < 0.5, None),
        ("jev_answer_first", "answer_first", lambda a: a["value"] < 0.5, None),
        ("jev_citable", "citable", lambda a: a["value"] < LOW, None),
        ("jev_rewrite", "action", lambda a: a["value"] in ("rewrite", "consolidate", "noindex_or_remove"), None),
    ]
    words = {p["url"]: p.get("word_count", 0) for p in crawl["pages"] if p.get("kind") == "page"}
    for rule_id, key, test, only in specs:
        urls, review, vals = collect(key, test, only)
        if key == "action":
            # Code checks Jev against the evidence: a removal verdict on a substantial page is not acted on.
            keep = [i for i, u in enumerate(urls) if not (pages[u]["action"]["value"] == "noindex_or_remove" and words.get(u, 0) >= 600)]
            urls, vals = [urls[i] for i in keep], [vals[i] for i in keep]
            review = sum(1 for u in urls if pages[u]["action"]["band"] == "review")
        if urls:
            if key == "action":
                detail = {"actions": {u: pages[u]["action"]["value"] for u in urls}}
                evidence = f"{len(urls)} page{'s' if len(urls) != 1 else ''}: " + "; ".join(f"{urlparse(u).path or '/'} ({pages[u]['action']['value'].replace('_', ' ')})" for u in urls[:6])
            else:
                detail = {"values": {u: pages[u][key]["value"] for u in urls}}
                where = ": " + ", ".join(urlparse(u).path or "/" for u in urls) if len(urls) <= 3 else ""
                evidence = f"Jev {LABEL[key]} averaged {mean(vals):.2f} (0 worst, 1 best) on {len(urls)} page{'s' if len(urls) != 1 else ''}{where}"
            out.append(jev_finding(rule_id, urls, evidence, review, detail))
    pairs = [p for p in judged.get("pairs", []) if p["judgment"] and p["judgment"]["value"] >= 0.6]
    if pairs:
        urls = sorted({u for p in pairs for u in (p["a"], p["b"])})
        out.append(jev_finding("jev_cannibalization", urls, f"{len(pairs)} page pairs judged to compete (P(yes) at least 0.6)", sum(p["judgment"]["band"] == "review" for p in pairs), {"pairs": pairs}))
    return out


def opportunity_key(k: dict) -> tuple:
    """Tiers: reachable (difficulty 30 or less), difficulty unknown, then longer term. Within a tier,
    searches discounted by difficulty. Sort with reverse=True."""
    kd = k.get("difficulty")
    tier = 2 if kd is not None and kd <= REACHABLE_KD else 1 if kd is None else 0
    return (tier, (k.get("volume") or 0) * (1 - min(kd if kd is not None else 50, 100) / 100))


def dfs_finding(rule_id: str, urls: list[str], count: int, evidence: str, detail: dict | None = None, review: int = 0, heuristic: bool = False) -> dict:
    cat, sev, title, fix, src, effort = DFS_RULES[rule_id]
    return {"id": rule_id, "origin": "dataforseo", "category": cat, "severity": sev, "title": title, "fix": fix, "source": SRC[src], "effort": effort,
            "heuristic": heuristic, "urls": urls, "count": count, "evidence": evidence, "needs_review": review, "detail": detail or {}}


def dfs_findings(crawl: dict, judged: dict, dfs: dict | None) -> list[dict]:
    """Keyword and authority findings. Jev relevance decides which keywords matter to this business."""
    if not dfs or not dfs.get("available"):
        return []
    out = []
    home = crawl["final_url"]
    kj = judged.get("keywords") or {}

    def rel(kw):
        if not kj:
            return 0.5  # no Jev: keep ranked keywords, but opportunities need a relevance judgment
        a = kj.get(kw)
        return a["relevance"]["value"] if a else None

    def fmt(k):
        hard = k.get("difficulty") is not None and k["difficulty"] > REACHABLE_KD
        return ("longer term: " if hard else "difficulty unknown: " if k.get("difficulty") is None else "") + f"{k['keyword']}" + (f" (+{k['variants']} rewordings)" if k.get("variants") else "") + f" ({k.get('volume') or 0}/mo" + (f", position {k['position']}" if k.get("position") else "") + (f", difficulty {k['difficulty']}" if k.get("difficulty") is not None else "") + ")"

    def other_brand(kw):
        a = kj.get(kw) or {}
        return (a.get("other_brand") or {}).get("value", 0) >= 0.5

    def opportunity(k):
        return opportunity_key(k)

    striking = [k for k in dfs.get("ranked") or [] if k.get("position") and 4 <= k["position"] <= 20 and (rel(k["keyword"]) or 0) >= 0.5 and not other_brand(k["keyword"])]
    if striking:
        striking.sort(key=opportunity, reverse=True)
        out.append(dfs_finding("dfs_striking", sorted({k["url"] for k in striking if k.get("url")}) or [home], len(striking),
                               "; ".join(fmt(k) for k in striking[:6]), {"keywords": striking},
                               sum(1 for k in striking if kj.get(k["keyword"]) and kj[k["keyword"]]["relevance"]["band"] == "review")))
    ranked_kw = {k["keyword"] for k in dfs.get("ranked") or []}
    from jevseo.dfs import norm_kw

    seen_norm, unique, variants = {norm_kw(k) for k in ranked_kw}, [], {}
    for k in sorted(dfs.get("opportunities") or [], key=lambda k: -(k.get("volume") or 0)):
        key = norm_kw(k["keyword"])
        if key in seen_norm:
            variants[key] = variants.get(key, 0) + 1
            continue
        seen_norm.add(key)
        unique.append(dict(k))
    for k in unique:
        n = variants.get(norm_kw(k["keyword"]), 0)
        if n:
            k["variants"] = n
    opps = [k for k in unique if k["keyword"] not in ranked_kw and (k.get("volume") or 0) > 0
            and (rel(k["keyword"]) or 0) >= 0.66 and not other_brand(k["keyword"])]
    existing = [k | {"page_url": kj[k["keyword"]]["page_url"]} for k in opps if kj[k["keyword"]]["page"]["value"] != "none_fit" and kj[k["keyword"]]["page_url"]]
    new = [k for k in opps if kj[k["keyword"]]["page"]["value"] == "none_fit"]
    for rule, rows in (("dfs_existing_page", existing), ("dfs_new_page", new)):
        if rows:
            rows.sort(key=opportunity, reverse=True)
            urls = sorted({k["page_url"] for k in rows}) if rule == "dfs_existing_page" else [home]
            review = sum(1 for k in rows if kj[k["keyword"]]["relevance"]["band"] == "review" or kj[k["keyword"]]["page"]["band"] == "review")
            out.append(dfs_finding(rule, urls, len(rows), "; ".join(fmt(k) + (f" -> {k['page_url']}" if k.get("page_url") else "") for k in rows[:6]), {"keywords": rows}, review))
    rd = {r["domain"]: r["referring_domains"] for r in dfs.get("referring_domains") or [] if r.get("referring_domains") is not None}
    own = rd.get(crawl["domain"])
    rivals = sorted(v for d, v in rd.items() if d != crawl["domain"])
    if own is not None and len(rivals) >= 2:
        median = rivals[len(rivals) // 2]
        if own < median / 4:
            others = ", ".join(f"{d} {v}" for d, v in sorted(rd.items(), key=lambda kv: -kv[1]) if d != crawl["domain"])
            out.append(dfs_finding("dfs_backlink_gap", [home], 1, f"{own} referring domains against a median of {median} across {len(rivals)} domains ranking for the same keywords ({others})", {"referring_domains": rd}, heuristic=True))
    bl = dfs.get("backlinks") or {}
    if (bl.get("broken_backlinks") or 0) > 0:
        out.append(dfs_finding("dfs_broken_backlinks", [home], bl["broken_backlinks"], f"{bl['broken_backlinks']} backlinks point at {bl.get('broken_pages') or 'some'} broken pages"))
    # Only searches that matter to this business: relevant, and not someone else's brand.
    pos = {k["keyword"]: k.get("position") for k in dfs.get("ranked") or []}
    aio = [s for s in dfs.get("serps") or [] if s["ai_overview"] and not s["ai_overview_cites_site"]
           and (rel(s["keyword"]) or 0) >= 0.5 and not other_brand(s["keyword"])]
    if aio:
        out.append(dfs_finding("dfs_aio_not_cited", [home], len(aio), "; ".join(f"{s['keyword']} (site " + (f"at position {pos[s['keyword']]}" if pos.get(s["keyword"]) else "not ranking") + f"; AI Overview cites {', '.join(s['ai_overview_domains'][:3]) or 'no domains'})" for s in aio[:5]), {"serps": aio}, heuristic=True))
    return out


def importance_of(url: str, judged: dict) -> float | None:
    ans = (judged.get("pages") or {}).get(url)
    return ans["importance"]["value"] if ans and "importance" in ans else None


def rule_component(findings: list[dict], cat: str, n_pages: int) -> float:
    total = 0.0
    for f in findings:
        if f["category"] != cat:
            continue
        total += DEDUCT[f["severity"]] * (0.5 + 0.5 * reach(f, n_pages))
    return max(0.0, 100.0 - total)


def weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    w = sum(x for _, x in pairs)
    return sum(v * x for v, x in pairs) / w if w else None


def score(crawl: dict, findings: list[dict], judged: dict, perf: dict | None, dfs: dict | None = None) -> dict:
    pages = html_pages(crawl)
    n = len(pages)
    jp = judged.get("pages") or {}
    cats = {}
    notes = {}
    for cat in CATEGORIES:
        cats[cat] = rule_component(findings, cat, n)
    # Jev-judged components, weighted by page importance
    def judged_mean(keys):
        vals = []
        for url, ans in jp.items():
            if not ans:
                continue
            present = [ans[k]["value"] for k in keys if k in ans]
            if present:
                vals.append((mean(present), 0.5 + (ans["importance"]["value"] if "importance" in ans else 0.5)))
        return weighted_mean(vals)

    content_j = judged_mean(["helpfulness", "specificity", "trust"])
    ai_j = judged_mean(["citable", "answer_first"])
    if content_j is not None:
        cats["content"] = JUDGED_SHARE * content_j * 100 + (1 - JUDGED_SHARE) * cats["content"]
        notes["content"] = "70% Jev judgment (helpfulness, specificity, trust), 30% rules"
    else:
        cats["content"] = None
        notes["content"] = "Not assessed: Jev judgments unavailable"
    if ai_j is not None:
        site = judged.get("site") or {}
        ent = [site["entity_clarity"]["value"]] if site else []
        cats["ai"] = JUDGED_SHARE * mean([ai_j] + ent) * 100 + (1 - JUDGED_SHARE) * cats["ai"]
        notes["ai"] = "70% Jev judgment (citability, answer-first, entity clarity), 30% rules"
    else:
        notes["ai"] = "Rules only: Jev judgments unavailable"
    runs = [r for r in (perf or {}).get("runs", []) if "error" not in r and r["strategy"] == "mobile" and "performance" in r.get("scores", {})]
    if runs:
        lab = mean(r["scores"]["performance"] for r in runs)
        cats["performance"] = 0.5 * lab + 0.5 * cats["performance"]
        notes["performance"] = "50% Lighthouse mobile performance, 50% crawl observations"
    else:
        notes["performance"] = "Crawl observations only: PageSpeed Insights unavailable"
    if dfs and dfs.get("available") and dfs.get("overview") is not None:
        notes["visibility"] = "DataForSEO rankings, keywords and backlinks, filtered by Jev relevance"
    else:
        cats["visibility"] = None
        notes["visibility"] = "Not assessed: run with --full (DataForSEO)"
    jev_hit = {f["category"] for f in findings if f.get("origin") == "jev"}
    dfs_hit = {f["category"] for f in findings if f.get("origin") == "dataforseo"}
    for cat in cats:
        if cat not in notes:
            extra = [n for n, hit in (("Jev findings", jev_hit), ("DataForSEO findings", dfs_hit)) if cat in hit]
            notes[cat] = "Rules" + (" plus " + " and ".join(extra) if extra else " only")
    notes["ai"] += "; editorial heuristics, since Google states no special optimization is required for AI features"

    available = {c: v for c, v in cats.items() if v is not None}
    overall = sum(v * CATEGORY_WEIGHT[c] for c, v in available.items()) / sum(CATEGORY_WEIGHT[c] for c in available)
    caps = []
    ids = {f["id"] for f in findings}
    if "robots_blocks_site" in ids or any(f["id"] == "noindex" and f["severity"] == "critical" for f in findings):
        overall = min(overall, 20)
        caps.append("Capped at 20: the homepage or whole site is blocked from search")
    elif "no_https" in ids:
        overall = min(overall, 60)
        caps.append("Capped at 60: the site is not reliably served over HTTPS")
    overall = round(overall)
    return {
        "overall": overall,
        "grade": "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F",
        "categories": {c: (round(v) if v is not None else None) for c, v in cats.items()},
        "category_names": CATEGORIES,
        "weights": CATEGORY_WEIGHT,
        "notes": notes,
        "caps": caps,
        "completeness": {"categories_scored": len(available), "categories_total": len(cats), "jev": any(jp.values()), "jev_pages_not_judged": sum(1 for a in jp.values() if a is None), "pagespeed": bool(runs), "dataforseo": bool(dfs and dfs.get("available"))},
    }


def actions(findings: list[dict], judged: dict, n_pages: int) -> list[dict]:
    rows = []
    for f in findings:
        if f["severity"] == "info":
            continue
        imps = [i for i in (importance_of(u, judged) for u in f["urls"]) if i is not None]
        importance = max(imps) if imps else None
        share = reach(f, n_pages)
        impact = SEVERITY_WEIGHT[f["severity"]] * (0.6 + 0.4 * share) * (0.6 + 0.8 * importance if importance is not None else 1.0)
        rows.append({"finding": f, "impact_raw": impact, "importance": importance, "reach": share})
    top = max((r["impact_raw"] for r in rows), default=1) or 1
    out = []
    for r in rows:
        f = r["finding"]
        impact = round(100 * r["impact_raw"] / top)
        if f["severity"] == "critical" or (f["severity"] == "high" and impact >= 40):
            pri = "P1"
        elif impact >= 30 or f["severity"] == "high":
            pri = "P2"
        else:
            pri = "P3"
        out.append({
            "priority": pri,
            "impact": impact,
            "effort": f["effort"],
            "quick_win": impact >= 35 and f["effort"] <= 1,
            "importance": None if r["importance"] is None else round(r["importance"], 2),
            **{k: f[k] for k in ("id", "origin", "category", "severity", "title", "fix", "source", "count", "evidence", "heuristic")},
            "needs_review": f.get("needs_review", 0),
            "urls": f["urls"],
        })
    out.sort(key=lambda a: (a["priority"], -a["impact"], a["effort"]))
    for i, a in enumerate(out, 1):
        a["action_id"] = f"JEV-{i:03d}"
        a["status"] = "to_do"
    return out

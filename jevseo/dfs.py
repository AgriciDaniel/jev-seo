"""DataForSEO (full mode): rankings, keywords, competitors, backlinks, SERPs and AI mentions.

Paid per call. Every request is checked against a hard budget before it is
sent, and the cost DataForSEO reports is recorded per call. Response shapes
were confirmed live on 2026-09-22. Positions use `rank_group` (organic rank),
not `rank_absolute`, which also counts SERP features.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from jevseo.env import secret

BASE = "https://api.dataforseo.com/v3/"
# Pre-dispatch estimates in USD, deliberately above the observed cost, so the cap is never overrun.
ESTIMATE = {
    "dataforseo_labs/google/domain_rank_overview/live": 0.02,
    "dataforseo_labs/google/ranked_keywords/live": 0.05,
    "dataforseo_labs/google/competitors_domain/live": 0.02,
    "dataforseo_labs/google/keyword_suggestions/live": 0.02,
    "dataforseo_labs/google/keyword_ideas/live": 0.02,
    "dataforseo_labs/google/domain_intersection/live": 0.02,
    "backlinks/summary/live": 0.03,
    "backlinks/bulk_referring_domains/live": 0.03,
    "serp/google/organic/live/advanced": 0.005,
    "ai_optimization/llm_mentions/search/live": 0.12,
}
# Platforms that "compete" with everyone in the rankings but are not business rivals.
PLATFORMS = {
    "github.com", "reddit.com", "youtube.com", "linkedin.com", "wikipedia.org", "medium.com", "x.com", "twitter.com",
    "facebook.com", "instagram.com", "amazon.com", "quora.com", "apple.com", "google.com", "microsoft.com", "tiktok.com",
    "pinterest.com", "stackoverflow.com", "npmjs.com", "pypi.org", "producthunt.com", "substack.com", "dev.to",
}
SERP_FEATURES = ["ai_overview", "featured_snippet", "people_also_ask", "local_pack", "video", "images", "shopping", "top_stories", "knowledge_graph", "discussions_and_forums"]


def bare(domain: str | None) -> str:
    d = (domain or "").lower()
    return d[4:] if d.startswith("www.") else d


class DataForSEO:
    def __init__(self, budget_usd: float, log=print):
        self.auth = (secret("DATAFORSEO_USERNAME"), secret("DATAFORSEO_PASSWORD"))
        self.budget = budget_usd
        self.log = log
        self.lock = threading.Lock()
        self.ledger = {"requests": 0, "cost_usd": 0.0, "reserved_usd": 0.0, "skipped_budget": 0, "failed": 0, "errors": [], "calls": []}

    @property
    def available(self) -> bool:
        return all(self.auth)

    def post(self, path: str, task: dict) -> dict | None:
        est = ESTIMATE.get(path, 0.05)
        with self.lock:
            if self.ledger["cost_usd"] + self.ledger["reserved_usd"] + est > self.budget:
                self.ledger["skipped_budget"] += 1
                return None
            self.ledger["reserved_usd"] += est
        cost = None
        try:
            r = requests.post(BASE + path, auth=self.auth, json=[task], timeout=120)
            data = r.json()
            cost = data.get("cost")
            t = (data.get("tasks") or [{}])[0]
            if r.status_code != 200 or (t.get("status_code") or 0) >= 40000:
                raise RuntimeError(f"{t.get('status_code')} {t.get('status_message') or data.get('status_message')}")
            return (t.get("result") or [None])[0] or {}
        except Exception as err:  # noqa: BLE001  a failed call is recorded, never fatal
            with self.lock:
                self.ledger["failed"] += 1
                self.ledger["errors"].append(f"{path}: {type(err).__name__}: {str(err)[:160]}")
            return None
        finally:
            with self.lock:
                self.ledger["reserved_usd"] -= est
                self.ledger["requests"] += 1
                # Unknown cost is charged at the estimate so the ledger never understates spend.
                charged = float(cost) if isinstance(cost, (int, float)) else est
                self.ledger["cost_usd"] = round(self.ledger["cost_usd"] + charged, 6)
                self.ledger["calls"].append({"endpoint": path, "cost_usd": charged, "reported": isinstance(cost, (int, float))})


STOP = {"for", "of", "in", "the", "a", "an", "to", "and", "on", "with", "best", "top"}


def norm_kw(k: str) -> str:
    """Merge rewordings: 'claude-code' = 'claude code', 'tools for seo' = 'seo tool' = 'seo seo tools'."""
    words = "".join(c if c.isalnum() else " " for c in (k or "").lower()).split()
    stems = {w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words if w not in STOP}
    return " ".join(sorted(stems)) or " ".join(words)


def keyword_row(item: dict) -> dict:
    kd = item.get("keyword_data", item)
    info = kd.get("keyword_info") or {}
    return {
        "keyword": kd.get("keyword"),
        "volume": info.get("search_volume"),
        "cpc": info.get("cpc"),
        "difficulty": (kd.get("keyword_properties") or {}).get("keyword_difficulty"),
        "intent": (kd.get("search_intent_info") or {}).get("main_intent"),
    }


def collect(domain: str, homepage: dict, loc: int, lang: str, budget: float, log=print) -> dict:
    dfs = DataForSEO(budget, log)
    out = {"available": dfs.available, "location_code": loc, "language_code": lang, "ledger": dfs.ledger}
    if not dfs.available:
        log("DATAFORSEO_USERNAME or DATAFORSEO_PASSWORD not found: full mode skipped.")
        return out
    L = {"location_code": loc, "language_code": lang}

    log("DataForSEO: visibility overview, rankings, competitors, backlinks")
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_over = pool.submit(dfs.post, "dataforseo_labs/google/domain_rank_overview/live", {"target": domain, **L})
        f_rank = pool.submit(dfs.post, "dataforseo_labs/google/ranked_keywords/live", {"target": domain, **L, "limit": 200, "order_by": ["keyword_data.keyword_info.search_volume,desc"]})
        f_comp = pool.submit(dfs.post, "dataforseo_labs/google/competitors_domain/live", {"target": domain, **L, "limit": 20, "exclude_top_domains": True})
        f_back = pool.submit(dfs.post, "backlinks/summary/live", {"target": domain, "include_subdomains": True})
        over, rank, comp, back = f_over.result(), f_rank.result(), f_comp.result(), f_back.result()

    organic = ((over or {}).get("items") or [{}])[0].get("metrics", {}).get("organic") if over else None
    out["overview"] = None if organic is None else {k: organic.get(k) for k in ("count", "etv", "estimated_paid_traffic_cost", "pos_1", "pos_2_3", "pos_4_10", "pos_11_20", "pos_21_30", "pos_31_40", "pos_41_50", "pos_51_60", "pos_61_70", "pos_71_80", "pos_81_90", "pos_91_100", "is_new", "is_up", "is_down", "is_lost")}
    ranked = []
    for it in (rank or {}).get("items") or []:
        se = (it.get("ranked_serp_element") or {}).get("serp_item") or {}
        ranked.append(keyword_row(it) | {"position": se.get("rank_group"), "url": se.get("url"), "etv": se.get("etv")})
    out["ranked"] = ranked
    out["ranked_total"] = (rank or {}).get("total_count")
    comps = [
        {"domain": bare(i.get("domain")), "shared_keywords": i.get("intersections"), "avg_position": i.get("avg_position"),
         "etv": ((i.get("full_domain_metrics") or {}).get("organic") or {}).get("etv"), "keywords": ((i.get("full_domain_metrics") or {}).get("organic") or {}).get("count")}
        for i in (comp or {}).get("items") or []
    ]
    out["competitors_all"] = [c for c in comps if c["domain"] != bare(domain)]
    out["competitors"] = [c for c in out["competitors_all"] if c["domain"] not in PLATFORMS][:8]
    out["backlinks"] = None if back is None else {k: back.get(k) for k in ("rank", "backlinks", "referring_domains", "referring_main_domains", "referring_ips", "broken_backlinks", "broken_pages", "backlinks_spam_score", "crawled_pages", "referring_links_types", "referring_links_attributes")}

    log("DataForSEO: referring domains for competitors, keyword ideas, gaps")
    # Compare against sites of a similar size first: a giant's keyword gap is mostly unrelated to a small site.
    own_kw = (out["overview"] or {}).get("count") or 1
    comparable = sorted(out["competitors"], key=lambda c: (not (c.get("keywords") or 0) <= 50 * own_kw, -(c.get("shared_keywords") or 0)))
    rivals = [c["domain"] for c in comparable[:5]]
    # Grow ideas from where the site is already strong (top 10), not from head terms it barely ranks for.
    strong = sorted((k for k in ranked if k.get("position") and k["position"] <= 10), key=lambda k: -(k["volume"] or 0))
    rest = sorted((k for k in ranked if k not in strong), key=lambda k: (k.get("position") or 999))
    seeds = list(dict.fromkeys(k["keyword"] for k in strong + rest))[:3]
    if not seeds and homepage.get("title"):
        seeds = [homepage["title"].split("|")[0].split(" - ")[0].strip()[:60]]
    jobs = {"bulk": ("backlinks/bulk_referring_domains/live", {"targets": [domain] + rivals})}
    for i, s in enumerate(seeds):
        jobs[f"sugg{i}"] = ("dataforseo_labs/google/keyword_suggestions/live", {"keyword": s, **L, "limit": 30, "include_seed_keyword": True})
    if seeds:
        jobs["ideas"] = ("dataforseo_labs/google/keyword_ideas/live", {"keywords": seeds, **L, "limit": 40})
    for i, r in enumerate(rivals[:2]):
        jobs[f"gap{i}"] = ("dataforseo_labs/google/domain_intersection/live", {"target1": r, "target2": domain, "intersections": False, **L, "limit": 30,
                                                                              "order_by": ["keyword_data.keyword_info.search_volume,desc"], "filters": ["first_domain_serp_element.rank_group", "<=", 20]})
    with ThreadPoolExecutor(max_workers=4) as pool:
        res = dict(zip(jobs, pool.map(lambda j: dfs.post(*j), jobs.values())))
    out["referring_domains"] = [{"domain": bare(i.get("target")), "referring_domains": i.get("referring_domains"), "referring_main_domains": i.get("referring_main_domains")} for i in (res.get("bulk") or {}).get("items") or []]
    ideas, seen = [], {norm_kw(k["keyword"]) for k in ranked}
    for key in [k for k in res if k.startswith("sugg")] + ["ideas"]:
        for it in (res.get(key) or {}).get("items") or []:
            row = keyword_row(it) | {"source": "suggestion" if key.startswith("sugg") else "idea"}
            if row["keyword"] and norm_kw(row["keyword"]) not in seen:
                seen.add(norm_kw(row["keyword"]))
                ideas.append(row)
    for i, r in enumerate(rivals[:2]):
        for it in (res.get(f"gap{i}") or {}).get("items") or []:
            row = keyword_row(it) | {"source": f"gap vs {r}", "rival_position": ((it.get("first_domain_serp_element") or {}).get("rank_group"))}
            if row["keyword"] and norm_kw(row["keyword"]) not in seen:
                seen.add(norm_kw(row["keyword"]))
                ideas.append(row)
    out["opportunities"] = ideas
    out["seeds"] = seeds

    # Check live results where the site actually competes (page one or two), not its highest-volume long shots.
    competing = sorted((k for k in ranked if k.get("position") and k["position"] <= 20 and (k.get("volume") or 0) > 0), key=lambda k: (k["position"] > 10, -(k["volume"] or 0)))
    targets = list(dict.fromkeys(k["keyword"] for k in competing + sorted(ranked, key=lambda k: -(k["volume"] or 0))))[:5]
    log(f"DataForSEO: live Google results for {len(targets)} keywords, AI answer mentions")
    serp_jobs = [("serp/google/organic/live/advanced", {"keyword": k, **L, "depth": 10, "load_async_ai_overview": True}) for k in targets]
    with ThreadPoolExecutor(max_workers=5) as pool:
        serp_res = list(pool.map(lambda j: dfs.post(*j), serp_jobs))
        f_ment = pool.submit(dfs.post, "ai_optimization/llm_mentions/search/live", {"target": [{"domain": domain}], "limit": 20})
        ment = f_ment.result()
    serps = []
    for kw, r in zip(targets, serp_res):
        if r is None:
            continue
        items = r.get("items") or []
        organic_items = [i for i in items if i.get("type") == "organic"]
        ov = next((i for i in items if i.get("type") == "ai_overview"), None)
        refs = (ov.get("references") or []) + [x for sub in (ov.get("items") or []) for x in (sub.get("references") or [])] if ov else []
        ref_domains = sorted({bare(x.get("domain")) for x in refs if x.get("domain")})
        own = next((i for i in organic_items if bare(i.get("domain")) == bare(domain)), None)
        serps.append({
            "keyword": kw,
            "features": [f for f in SERP_FEATURES if any(i.get("type") == f for i in items)],
            "top": [{"position": i.get("rank_group"), "domain": bare(i.get("domain")), "url": i.get("url"), "title": i.get("title")} for i in organic_items[:10]],
            "own_position": own.get("rank_group") if own else None,
            "ai_overview": bool(ov),
            "ai_overview_cites_site": bare(domain) in ref_domains,
            "ai_overview_domains": ref_domains[:12],
        })
    out["serps"] = serps
    out["mentions"] = None if ment is None else {
        "total": ment.get("total_count"),
        "items": [{"platform": i.get("platform"), "model": i.get("model_name"), "question": i.get("question"), "ai_search_volume": i.get("ai_search_volume"),
                   "sources": sorted({bare(s.get("domain")) for s in (i.get("sources") or []) if s.get("domain")})[:8]} for i in (ment.get("items") or [])],
    }
    log(f"DataForSEO: {dfs.ledger['requests']} requests, ${dfs.ledger['cost_usd']:.4f}, {dfs.ledger['failed']} failed, {dfs.ledger['skipped_budget']} skipped by budget")
    return out

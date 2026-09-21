"""Build report.pdf, report.xlsx and report.md from one audit.json (and optional narrative.json).

All three exports read the same view model, so a number cannot differ between them.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from urllib.parse import urlparse

from jevseo.report import charts

PRIORITY_TEXT = {"P1": "Fix first", "P2": "Plan next", "P3": "When convenient"}
EFFORT_TEXT = {1: "Hours", 2: "About a day", 3: "Several days", 4: "A project"}
JEV_COLUMNS = [("helpfulness", "helpful"), ("specificity", "specific"), ("trust", "trust"), ("citable", "citable"), ("answer_first", "answer 1st"), ("title_fit", "title"), ("meta_fit", "meta"), ("clear_next_step", "next step")]
NARRATIVE_KEYS = {"executive_summary", "strengths", "risks", "plan"}


def short(url: str, site: str = "") -> str:
    p = urlparse(url)
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    host = p.netloc.removeprefix("www.")
    return path if not site or host == site else f"{host}{path}"


def load_narrative(folder: Path, data: dict) -> dict:
    path = folder / "narrative.json"
    ids = {a["action_id"] for a in data["actions"]}
    if path.is_file():
        n = json.loads(path.read_text())
        missing = NARRATIVE_KEYS - set(n)
        if missing:
            raise SystemExit(f"narrative.json is missing {sorted(missing)}")
        text = json.dumps(n)
        unknown = sorted(set(re.findall(r"JEV-\d{3}", text)) - ids)
        if unknown:
            raise SystemExit(f"narrative.json cites action IDs that do not exist: {unknown}")
        n.setdefault("author", "Claude, from the audit evidence")
        n["automatic"] = False
        n["unverified_numbers"] = unverified_numbers(text, data)
        n["effort_mismatches"] = effort_mismatches(n, data)
        return n
    return auto_narrative(data)


def effort_mismatches(n: dict, data: dict) -> list[str]:
    """Plan items that state an effort band different from every action they cite."""
    effort = {a["action_id"]: EFFORT_TEXT[a["effort"]].lower() for a in data["actions"]}
    bad = []
    for block in n.get("plan", []):
        for item in block.get("items", []):
            ids = re.findall(r"JEV-\d{3}", item)
            stated = re.search(r"\((hours|about a day|several days|a project)\)\s*$", item.strip(), re.I)
            if ids and stated and stated.group(1).lower() not in {effort.get(i) for i in ids}:
                bad.append(f"{'/'.join(ids)} says '{stated.group(1)}' but the action table says '{', '.join(effort.get(i, '?') for i in ids)}'")
    return bad


def unverified_numbers(text: str, data: dict) -> list[str]:
    """Numbers in the narrative that match nothing in the audit, allowing rounding and ms to seconds."""
    text = re.sub(r"JEV-\d{3}", "", text)
    text = re.sub(r"(https?://|/|@)[\w@./%-]*", " ", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}(?:T[\d:.+-]+)?", " ", text)  # ISO dates and timestamps  # digits inside URLs, paths and handles are not claims
    known: set[float] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            known.add(float(v))
        elif isinstance(v, str):
            known.update(float(x) for x in re.findall(r"\d+(?:\.\d+)?", v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
            for k in v:
                walk(k if isinstance(k, str) else None)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    # Only citable facts count; per-page probabilities are too numerous to prove anything.
    sc = data["scores"]
    walk([sc["overall"], list(sc["categories"].values()), sc["weights"]])
    walk([[a["impact"], a["count"], a["evidence"], a["title"]] for a in data["actions"]])
    for a in (data["jev"].get("site") or {}).values():
        walk([a["value"], a.get("confidence")])
    walk({k: v for k, v in (data["jev"].get("ledger") or {}).items() if k != "errors"})
    for r in (data.get("performance") or {}).get("runs", []):
        walk([r.get("scores"), [m["p75"] for f in (r.get("field_url"), r.get("field_origin")) if f for m in f["metrics"].values()]])
    walk([[p.get("word_count"), p.get("inlinks"), p.get("depth")] for p in data["pages"]])
    walk([data["site"]["sitemaps"]["total_urls"], data["site"]["requests"], len(data["site"]["robots"]["ai_bots"]), data["site"]["probes"]["not_found_status"], data["site"]["probes"]["host_variant"]["status"]])
    home = next((p for p in data["pages"] if p.get("url") == data["site"]["final_url"]), {})
    walk([home.get("title"), home.get("h1"), home.get("meta_description")])
    x = data.get("dataforseo") or {}
    if x.get("available"):
        walk([x.get("overview"), x.get("backlinks"), x.get("referring_domains"), x.get("competitors"), x.get("ranked_total")])
        walk([[k.get("volume"), k.get("position"), k.get("difficulty")] for k in (x.get("ranked") or []) + (x.get("opportunities") or [])])
        walk([[sp.get("own_position")] for sp in x.get("serps") or []] + [(x.get("mentions") or {}).get("total"), x["ledger"].get("cost_usd"), x["ledger"].get("requests")])
    for a in (data["jev"].get("keywords") or {}).values():
        if a:
            walk([a["relevance"]["value"], a["relevance"].get("confidence")])
    known.update({float(len(data["actions"])), float(len(data["pages"])), float(sum(1 for p in data["pages"] if p.get("kind") == "page" and p.get("status") == 200))})
    loose = set()
    for k in known:
        for scale in (1, 100, 0.001):
            for digits in (0, 1, 2):
                loose.add(round(k * scale, digits))
    bad = []
    for tok in re.findall(r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.,])\d+(?:\.\d+)?", text):
        v = float(tok.replace(",", ""))
        if v <= 10 and "." not in tok:
            continue  # small counts are too common to check mechanically
        if v not in known and v not in loose:
            bad.append(tok)
    return sorted(set(bad))


def auto_narrative(d: dict) -> dict:
    """Evidence-only fallback used when no lead-agent narrative exists."""
    s = d["scores"]
    cats = {c: v for c, v in s["categories"].items() if v is not None}
    best = sorted(cats, key=lambda c: -cats[c])[:3]
    worst = sorted(cats, key=lambda c: cats[c])[:3]
    acts = d["actions"]
    p1 = [a for a in acts if a["priority"] == "P1"]
    quick = [a for a in acts if a["quick_win"]]
    names = s["category_names"]
    summary = (
        f"{d['site']['domain']} scores {s['overall']} out of 100 (grade {s['grade']}) across {len(cats)} scored areas. "
        f"The strongest areas are {', '.join(names[c].lower() for c in best)}; the weakest are {', '.join(names[c].lower() for c in worst)}. "
        f"The audit produced {len(acts)} actions, {len(p1)} of them marked fix first and {len(quick)} quick wins."
    )
    return {
        "executive_summary": [summary],
        "strengths": [f"{names[c]} scores {cats[c]}." for c in best],
        "risks": [f"{a['action_id']}: {a['title']} ({a['evidence']})" for a in (p1 or acts)[:4]],
        "plan": [
            {"horizon": "This week", "items": [f"{a['action_id']} {a['title']}" for a in (quick or acts)[:4]]},
            {"horizon": "This month", "items": [f"{a['action_id']} {a['title']}" for a in acts if a["priority"] in ("P1", "P2") and a not in quick][:5]},
            {"horizon": "This quarter", "items": [f"{a['action_id']} {a['title']}" for a in acts if a["priority"] == "P3"][:5]},
        ],
        "author": "Automatic summary (no lead-agent narrative was written)",
        "automatic": True,
    }


def view_model(d: dict, folder: Path) -> dict:
    site = d["site"]
    domain = site["domain"]
    pages = [p for p in d["pages"] if p.get("kind") == "page" and p.get("status") == 200 and "word_count" in p]
    jp = d["jev"].get("pages") or {}
    acts = d["actions"]
    for a in acts:
        a["priority_text"] = PRIORITY_TEXT[a["priority"]]
        a["effort_text"] = EFFORT_TEXT[a["effort"]]
        a["short_urls"] = [short(u, domain) for u in a["urls"][:6]]
        a["by"] = {"jev": "Jev judged", "dataforseo": "DataForSEO"}.get(a["origin"], "rule")
        a["by_class"] = {"jev": "tag-jev", "dataforseo": "tag-dfs"}.get(a["origin"], "tag-rule")

    status_counts = Counter(str(p.get("status") or "error") for p in d["pages"] if p.get("kind") != "redirect")
    redirects = sum(1 for p in d["pages"] if p.get("kind") == "redirect")
    depth_counts = Counter(p.get("depth") if p.get("depth", 99) < 99 else "not linked" for p in pages)
    types = Counter(a["page_type"]["value"] for a in jp.values() if a)
    intents = Counter(a["intent"]["value"] for a in jp.values() if a)
    page_actions = Counter(a["action"]["value"] for a in jp.values() if a)

    # Jev heatmap: most important pages first
    ranked = sorted((u for u in jp if jp[u]), key=lambda u: -jp[u]["importance"]["value"])[:18]
    matrix = [[jp[u][k]["value"] if k in jp[u] else None for k, _ in JEV_COLUMNS] for u in ranked]
    conf_rows = []
    for key, label in [("page_type", "page type"), ("intent", "intent"), ("importance", "importance"), ("action", "action")] + JEV_COLUMNS + [("h1_fit", "h1")]:
        answers = [a[key] for a in jp.values() if a and key in a]
        if answers:
            decisive = sum(1 for x in answers if x["band"] in ("act", "yes", "no"))
            conf_rows.append((label, decisive, len(answers) - decisive))

    perf = d.get("performance") or {}
    runs = [r for r in perf.get("runs", []) if "error" not in r]
    home_mobile = next((r for r in runs if r["url"] == site["final_url"] and r["strategy"] == "mobile"), None)
    home_desktop = next((r for r in runs if r["url"] == site["final_url"] and r["strategy"] == "desktop"), None)
    field = (home_mobile or {}).get("field_url") or (home_mobile or {}).get("field_origin")

    cs = charts.ChartSet(folder / "charts")
    s = d["scores"]
    charts.gauge(cs, s["overall"], s["grade"])
    charts.category_bars(cs, s, s["category_names"])
    sev = Counter(a["severity"] for a in acts)
    charts.donut(cs, "severity", [(k, sev.get(k, 0)) for k in ("critical", "high", "medium", "low")], [charts.STATUS[k] for k in ("critical", "high", "medium", "low") if sev.get(k)], "actions")
    charts.severity_by_category(cs, acts, s["category_names"])
    charts.impact_effort(cs, acts)
    charts.donut(cs, "page_types", types.most_common(), center="pages judged")
    charts.donut(cs, "intents", intents.most_common(), center="pages judged")
    charts.donut(cs, "page_actions", page_actions.most_common(), center="Jev verdicts")
    charts.bars(cs, "status", list(status_counts), list(status_counts.values()) , "HTTP status", highlight={"200"})
    dk = sorted(depth_counts, key=lambda k: 99 if k == "not linked" else k)
    charts.bars(cs, "depth", [str(k) for k in dk], [depth_counts[k] for k in dk], "clicks from homepage")
    edges = [(0, 150, "<150"), (150, 300, "150+"), (300, 600, "300+"), (600, 1000, "600+"), (1000, 2000, "1k+"), (2000, 10**9, "2k+")]
    charts.bars(cs, "words", [e[2] for e in edges], [sum(1 for p in pages if e[0] <= p["word_count"] < e[1]) for e in edges], "words of main content", highlight={"150+", "300+", "600+", "1k+", "2k+"})
    charts.histogram(cs, "title_len", [len(p["title"]) for p in pages if p.get("title")], list(range(0, 121, 10)), 65, "title length (characters)")
    charts.heatmap(cs, [short(u, domain)[:42] for u in ranked], [label for _, label in JEV_COLUMNS], matrix)
    charts.confidence_bars(cs, conf_rows)
    charts.lighthouse(cs, home_mobile, home_desktop)
    charts.cwv_bullets(cs, field)

    urls = {p["url"] for p in pages}
    nodes = [{"url": p["url"], "label": short(p["url"], domain), "depth": p.get("depth"), "importance": (jp.get(p["url"]) or {}).get("importance", {}).get("value"),
              "type": (jp.get(p["url"]) or {}).get("page_type", {}).get("value")} for p in pages]
    edges = sorted({(p["url"], l["url"]) for p in pages for l in p.get("links_internal", []) if l["url"] in urls})
    charts.site_map(cs, nodes, edges, site["final_url"])
    discovered = set(site["sitemaps"]["urls"]) | {l["url"] for p in d["pages"] for l in p.get("links_internal", [])} | {p["url"] for p in d["pages"]}
    indexable_n = sum(1 for p in pages if "noindex" not in f"{p.get('meta_robots') or ''} {p.get('x_robots') or ''}" and (not p.get("canonical") or p["canonical"] == p["url"]))
    charts.funnel(cs, [("URLs discovered", len(discovered)), ("URLs crawled", len(d["pages"])), ("HTML pages (200)", len(pages)), ("Indexable", indexable_n), ("Judged by Jev", sum(1 for a in jp.values() if a))])
    invest = [{"label": short(u, domain), "importance": a["importance"]["value"], "quality": mean([a[k]["value"] for k in ("helpfulness", "specificity", "trust") if k in a])} for u, a in jp.items() if a]
    charts.invest_matrix(cs, invest)

    # Full mode: DataForSEO views, with Jev relevance and page mapping attached
    x = d.get("dataforseo") if (d.get("dataforseo") or {}).get("available") else None
    kj = d["jev"].get("keywords") or {}
    dfs_vm = None
    if x:
        from jevseo.dfs import norm_kw

        def kjv(kw, key):
            a = kj.get(kw) or {}
            return (a.get(key) or {}).get("value")

        ranked_rows = [k | {"relevance": kjv(k["keyword"], "relevance"), "page": short(k.get("url") or "", domain)} for k in (x.get("ranked") or [])[:25]]
        opp_actions = {a["id"]: a for a in d["findings"] if a["id"] in ("dfs_existing_page", "dfs_new_page")}
        opp_rows = []
        for fid, f in opp_actions.items():
            for k in f["detail"].get("keywords", []):
                opp_rows.append(k | {"relevance": kjv(k["keyword"], "relevance"), "new_page": fid == "dfs_new_page", "target": "new page" if fid == "dfs_new_page" else short(k.get("page_url") or "", domain)})
        from jevseo.score import opportunity_key

        opp_rows.sort(key=opportunity_key, reverse=True)
        charts.positions(cs, x.get("overview"))
        charts.referring_domains(cs, x.get("referring_domains") or [], domain)
        charts.opportunities(cs, opp_rows)
        ment = x.get("mentions") or {}
        plat = Counter(m.get("platform") or "unknown" for m in ment.get("items") or [])
        charts.donut(cs, "mention_platforms", plat.most_common(), center="sampled mentions")
        dfs_vm = {
            "overview": x.get("overview") or {}, "backlinks": x.get("backlinks") or {}, "ranked": ranked_rows, "ranked_total": x.get("ranked_total"),
            "opportunities": opp_rows[:15], "n_opportunities": len(opp_rows), "serps": x.get("serps") or [], "competitors": x.get("competitors") or [],
            "referring_domains": x.get("referring_domains") or [], "mentions": ment, "ledger": x["ledger"], "reused_from": x.get("reused_from"),
            "location_code": x["location_code"], "language_code": x["language_code"],
        }

    page_rows = []
    for p in sorted(pages, key=lambda p: (p.get("depth", 99), p["url"])):
        j = jp.get(p["url"]) or {}
        page_rows.append({
            "url": p["url"], "short": short(p["url"], domain), "status": p["status"], "depth": p.get("depth"), "title": p.get("title"), "title_len": len(p.get("title") or ""),
            "meta_len": len(p.get("meta_description") or ""), "h1": (p.get("h1") or [""])[0], "h1_count": len(p.get("h1") or []), "words": p["word_count"],
            "inlinks": p.get("inlinks", 0), "outlinks": len(p.get("links_internal", [])), "images": p["images"]["total"], "missing_alt": p["images"]["missing_alt"],
            "schema": ", ".join(p.get("schema_types") or []), "canonical": p.get("canonical"), "indexable": "noindex" not in f"{p.get('meta_robots') or ''} {p.get('x_robots') or ''}", "in_sitemap": p.get("in_sitemap"),
            "ttfb": p.get("ttfb_ms"), "kb": round((p.get("bytes") or 0) / 1024), "rendered": p.get("rendered"),
            "page_type": j.get("page_type", {}).get("value"), "intent": j.get("intent", {}).get("value"), "importance": j.get("importance", {}).get("value"), "action": j.get("action", {}).get("value"),
            **{k: j.get(k, {}).get("value") for k, _ in JEV_COLUMNS},
        })

    ledger = d["jev"].get("ledger") or {}
    jev_site = d["jev"].get("site")
    site_cards = []
    if jev_site:
        labels = {"business_model": "What kind of business is this?", "value_prop": "How clear is the offer on the homepage?", "entity_clarity": "Does the homepage say who, what and where?", "topical_focus": "How focused is the site's topic set?", "serves_local_area": "Does it serve a specific local area?"}
        for key, question in labels.items():
            a = jev_site[key]
            card = {"key": key, "question": question, "type": a["type"], "band": a["band"]}
            if a["type"] == "choice":
                top = sorted(a["probabilities"].items(), key=lambda kv: -kv[1])[:3]
                card |= {"answer": a["value"].replace("_", " "), "confidence": a["confidence"], "bars": [(k.replace("_", " "), v) for k, v in top]}
            elif a["type"] == "score":
                levels = ((d["jev"].get("questions") or {}).get("site") or {}).get(key, {}).get("criteria") or []
                name = lambda k: levels[int(k)][:34] if int(k) < len(levels) else f"level {k}"  # noqa: E731
                card |= {"answer": f"{a['value']:.2f}", "confidence": a["confidence"], "bars": [(name(k), v) for k, v in sorted(a["probabilities"].items(), key=lambda kv: int(kv[0]))]}
            else:
                card |= {"answer": f"P(yes) {a['value']:.2f}", "bars": [("yes", a["value"]), ("no", 1 - a["value"])]}
            site_cards.append(card)

    robots = site["robots"]
    return {
        "d": d,
        "domain": domain,
        "site": site,
        "scores": s,
        "actions": acts,
        "top_actions": acts[:10],
        "quick_wins": [a for a in acts if a["quick_win"]][:8],
        "pages": page_rows,
        "n_pages": len(pages),
        "n_fetched": len(d["pages"]),
        "redirects": redirects,
        "status_counts": dict(status_counts),
        "charts": cs,
        "narrative": load_narrative(folder, d),
        "ledger": ledger,
        "site_cards": site_cards,
        "dfs": dfs_vm,
        "jev_available": any(jp.values()),
        "not_judged": [u for u, a in jp.items() if a is None],
        "p1_count": sum(1 for a in acts if a["priority"] == "P1"),
        "invest_pages": sorted(
            [{"short": short(u, domain), "importance": a["importance"]["value"], "quality": mean([a[k]["value"] for k in ("helpfulness", "specificity", "trust") if k in a]), "action": a["action"]["value"]}
             for u, a in jp.items() if a and a["importance"]["value"] >= 0.5 and mean([a[k]["value"] for k in ("helpfulness", "specificity", "trust") if k in a]) < 0.5],
            key=lambda r: -r["importance"],
        )[:8],
        "jev_pairs": sorted((p for p in d["jev"].get("pairs", []) if p.get("judgment")), key=lambda p: -p["judgment"]["value"]),
        "questions": d["jev"].get("questions") or {},
        "perf_runs": runs,
        "perf_errors": [r for r in perf.get("runs", []) if "error" in r],
        "field": field,
        "home_mobile": home_mobile,
        "ai_bots": robots["ai_bots"],
        "search_bots": robots["search_bots"],
        "findings_by_cat": {c: [a for a in acts if a["category"] == c] for c in s["category_names"]},
        "passed": d["passed_rules"],
        "sev_counts": dict(sev),
        "avg_words": round(mean([p["word_count"] for p in pages])) if pages else 0,
        "decisive_share": round(100 * sum(r[1] for r in conf_rows) / max(1, sum(r[1] + r[2] for r in conf_rows))),
        "n_judgments": sum(r[1] + r[2] for r in conf_rows) + (5 if jev_site else 0) + len([p for p in d["jev"].get("pairs", []) if p.get("judgment")]),
    }


def build(folder: Path, formats: list[str], log=print) -> dict:
    data = json.loads((folder / "audit.json").read_text())
    log("building charts")
    vm = view_model(data, folder)
    written = {}
    if "pdf" in formats:
        from jevseo.report.pdf import write_pdf

        log("rendering PDF")
        written["pdf"] = write_pdf(vm, folder / "report.pdf")
    if "xlsx" in formats:
        from jevseo.report.xlsx import write_xlsx

        log("writing workbook")
        written["xlsx"] = write_xlsx(vm, folder / "report.xlsx")
    if "md" in formats:
        from jevseo.report.md import write_md

        written["md"] = write_md(vm, folder / "report.md")
    for k, v in written.items():
        log(f"{k}: {v}")
    for issue in vm["narrative"].get("effort_mismatches") or []:
        log(f"WARNING narrative effort mismatch: {issue}")
    if vm["narrative"].get("unverified_numbers"):
        log("WARNING narrative.json contains numbers not found in the audit: " + ", ".join(vm["narrative"]["unverified_numbers"]) + ". Check them against digest.md and re-render.")
    return written

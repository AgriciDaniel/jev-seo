"""Markdown report: readable anywhere, with chart images and Mermaid pies for GitHub and Obsidian."""
from __future__ import annotations

from collections import Counter
from pathlib import Path


def cell(v) -> str:
    return str("" if v is None else v).replace("|", "\\|").replace("\n", " ")


def label(v) -> str:
    return cell((v or "").replace("_", " "))


WIDTH = {"gauge": 220, "severity": 320, "page_types": 360, "intents": 360, "positions": 380, "referring_domains": 380}


def img(vm: dict, name: str, alt: str) -> str:
    """HTML image tags so GitHub and Obsidian show charts at a readable size."""
    p = vm["charts"].png.get(name)
    return f'<img src="charts/{p.name}" alt="{alt}" width="{WIDTH.get(name, 640)}">\n' if p else ""


def pie(title: str, counts: dict) -> str:
    if not counts:
        return ""
    body = "\n".join(f'    "{k.replace("_", " ")}" : {v}' for k, v in counts.items() if v)
    return f"```mermaid\npie showData title {title}\n{body}\n```\n"


def write_md(vm: dict, path: Path) -> Path:
    d, s, n = vm["d"], vm["scores"], vm["narrative"]
    L = []
    add = L.append
    add(f"# Jev SEO audit: {vm['domain']}\n")
    add(f"Audited {d['run']['finished_at']} · {vm['n_fetched']} URLs crawled · {vm['n_pages']} HTML pages · {vm['n_judgments']} Jev judgments · Jev cost ${(vm['ledger'].get('cost_usd') or 0):.4f}\n")
    add(f"**Overall score: {s['overall']}/100 (grade {s['grade']})**" + (f". {'; '.join(s['caps'])}" if s["caps"] else "") + "\n")
    add(img(vm, "gauge", "Overall score"))
    add("| Area | Score | Weight | How it is scored |\n|---|---:|---:|---|")
    for c, name in s["category_names"].items():
        v = s["categories"][c]
        add(f"| {name} | {v if v is not None else 'n/a'} | {s['weights'][c]} | {s['notes'][c]} |")
    add("")
    add(img(vm, "categories", "Score by area"))

    toc = ["Executive summary", "How this audit was made", "Priority actions"] + (["Search visibility (DataForSEO)"] if vm.get("dfs") else []) + ["What the crawl found"] + (["How Jev reads the site"] if vm["jev_available"] else []) + ["Findings by area", "Robots access", "Page inventory", "Method and limits"]
    anchor = lambda h: "#" + "".join(c for c in h.lower().replace(" ", "-") if c.isalnum() or c == "-")  # noqa: E731
    add("**Contents:** " + " · ".join(f"[{h}]({anchor(h)})" for h in toc) + "\n")
    add("## Executive summary\n")
    for para in n["executive_summary"]:
        add(para + "\n")
    add("**What is working**\n")
    add("\n".join(f"- {x}" for x in n["strengths"]) + "\n")
    add("**What is holding the site back**\n")
    add("\n".join(f"- {x}" for x in n["risks"]) + "\n")
    add("### Plan\n")
    for block in n["plan"]:
        add(f"**{block['horizon']}**\n")
        add("\n".join(f"- {x}" for x in block["items"]) + "\n")
    if n.get("closing"):
        add(n["closing"] + "\n")
    add(f"_Written by: {n['author']}._\n")

    add("## How this audit was made\n")
    add("A source finds, code decides, Jev judges, Claude writes. Code crawls, counts and scores. Jev (TypeSafe's System One model) answers narrow typed questions about meaning, with probabilities. Missing data is shown as missing.\n")
    add("```mermaid\nflowchart LR\n  A[Crawl<br/>" + f"{vm['n_fetched']} URLs" + "] --> B[Rules<br/>" + f"{sum(1 for f in d['findings'] if f['origin'] == 'rule')} findings" + "] --> C[Jev judges<br/>" + f"{vm['n_judgments']} judgments" + "] --> D[PageSpeed<br/>" + f"{len(vm['perf_runs'])} runs" + "] --> E[Score and write<br/>" + f"{len(vm['actions'])} actions" + "]\n  style C fill:#d45bb6,color:#fff\n```\n")

    add("## Priority actions\n")
    add(img(vm, "impact_effort", "Impact versus effort"))
    add("| ID | Action | Priority | Impact | Effort | Pages | By | Verify |\n|---|---|---|---:|---|---:|---|---:|")
    for a in vm["actions"]:
        add(f"| {a['action_id']} | {cell(a['title'])}{' (quick win)' if a['quick_win'] else ''} | {a['priority']} {a['priority_text']} | {a['impact']} | {a['effort_text']} | {a['count']} | {a['by']} | {a['needs_review'] or ''} |")
    add("")
    add(pie("Actions by severity", {k: vm["sev_counts"].get(k, 0) for k in ("critical", "high", "medium", "low")}))
    add(img(vm, "severity_by_category", "Actions by area and severity"))

    x = vm.get("dfs")
    if x:
        ov, bl = x["overview"], x["backlinks"]
        add("## Search visibility (DataForSEO)\n")
        add(f"Location {x['location_code']}, language {x['language_code']}. Traffic (ETV) is DataForSEO's estimate, not measured visits.\n")
        add(f"| Ranking keywords | Est. monthly visits | Referring domains | Backlinks | AI answer mentions |\n|---:|---:|---:|---:|---:|\n| {ov.get('count')} | {round(ov['etv']) if ov.get('etv') is not None else 'n/a'} | {bl.get('referring_domains')} | {bl.get('backlinks')} | {(x['mentions'] or {}).get('total')} |\n")
        add(img(vm, "positions", "Ranking keywords by position"))
        add(img(vm, "referring_domains", "Referring domains compared"))
        add("| Keyword | Position | Searches/mo | Ranking page | Jev relevance |\n|---|---:|---:|---|---:|")
        for k in x["ranked"][:20]:
            add(f"| {cell(k['keyword'])} | {k.get('position')} | {k.get('volume')} | {k['page']} | {'' if k['relevance'] is None else format(k['relevance'], '.2f')} |")
        add("\n### Keywords worth winning\n")
        add(img(vm, "opportunities", "Keyword opportunities"))
        add("| Keyword | Searches/mo | Difficulty | Intent | Jev relevance | Page to own it |\n|---|---:|---:|---|---:|---|")
        for k in x["opportunities"]:
            rel = "" if k.get("relevance") is None else f"{k['relevance']:.2f}"
            add(f"| {cell(k['keyword'])} | {k.get('volume')} | {k.get('difficulty') if k.get('difficulty') is not None else 'n/a'} | {cell(k.get('intent'))} | {rel} | {k['target']} |")
        add("")
        if x["serps"]:
            add("| Keyword | Site position | AI Overview | Top 3 |\n|---|---:|---|---|")
            for sp in x["serps"]:
                aio = ("yes, cites the site" if sp["ai_overview_cites_site"] else "yes, site not cited") if sp["ai_overview"] else "none"
                add(f"| {cell(sp['keyword'])} | {sp['own_position'] or 'not in top 10'} | {aio} | {', '.join(t['domain'] for t in sp['top'][:3])} |")
            add("")

    add("## What the crawl found\n")
    add(img(vm, "funnel", "From discovered URLs to Jev judgments"))
    add(img(vm, "site_map", "Site structure by click depth"))

    if vm["jev_available"]:
        add("## How Jev reads the site\n")
        for c in vm["site_cards"]:
            conf = f", confidence {c['confidence']:.2f}" if "confidence" in c else ""
            flag = "" if c["band"] in ("act", "yes", "no") else " _(verify)_"
            add(f"- **{c['question']}** {c['answer']}{conf}{flag}")
        add("")
        jp = d["jev"]["pages"]
        add(pie("Page types (Jev)", dict(Counter(a["page_type"]["value"] for a in jp.values() if a).most_common())))
        add(pie("Search intent (Jev)", dict(Counter(a["intent"]["value"] for a in jp.values() if a).most_common())))
        add(img(vm, "jev_heatmap", "Jev page quality heatmap"))
        add(img(vm, "jev_confidence", "How sure Jev was"))
        add("### Where to invest\n")
        add(img(vm, "invest", "Importance versus judged quality"))
        if vm["invest_pages"]:
            add("| Important but weak | Importance | Quality | Jev suggests |\n|---|---:|---:|---|")
            for p in vm["invest_pages"]:
                add(f"| {p['short']} | {p['importance']:.2f} | {p['quality']:.2f} | {cell((p['action'] or '').replace('_', ' '))} |")
            add("")
        if vm["jev_pairs"]:
            add("**Pages that may compete for the same searches**\n")
            add("| Page A | Page B | Title overlap | P(compete) |\n|---|---|---:|---:|")
            for p in vm["jev_pairs"][:20]:
                add(f"| {p['a']} | {p['b']} | {p['title_overlap']} | {p['judgment']['value']:.2f} |")
            add("")

    add("## Findings by area\n")
    for c, name in s["category_names"].items():
        acts = vm["findings_by_cat"][c]
        if not acts:
            continue
        add(f"### {name} ({s['categories'][c] if s['categories'][c] is not None else 'n/a'})\n")
        if c == "performance":
            add(img(vm, "lighthouse", "Lighthouse scores"))
            add(img(vm, "cwv", "Core Web Vitals field data"))
        for a in acts:
            tags = [a["priority"], a["severity"], a["by"]]
            if a["needs_review"]:
                tags.append(f"{a['needs_review']} to verify")
            if a["heuristic"]:
                tags.append("heuristic")
            add(f"**{a['action_id']} · {a['title']}** `{'` `'.join(tags)}`\n")
            add(f"- Evidence: {a['count']} affected · {a['evidence']}")
            add(f"- Fix: {a['fix']} ([source]({a['source']}))")
            add("- URLs: " + ", ".join(a["urls"][:8]) + (f" and {a['count'] - 8} more" if a["count"] > 8 else ""))
            add("")

    add("## Robots access\n")
    add("| User agent | Access |\n|---|---|")
    for b, ok in {**vm["search_bots"], **vm["ai_bots"]}.items():
        add(f"| {b} | {'allowed' if ok else 'blocked'} |")
    add("")

    add("## Page inventory\n")
    add("| Page | Depth | Words | Inlinks | Type (Jev) | Intent (Jev) | Importance | Action (Jev) |\n|---|---:|---:|---:|---|---|---:|---|")
    for p in vm["pages"]:
        imp = f"{p['importance']:.2f}" if p["importance"] is not None else ""
        add(f"| {p['url']} | {p['depth'] if p['depth'] != 99 else ''} | {p['words']} | {p['inlinks']} | {label(p['page_type'])} | {label(p['intent'])} | {imp} | {label(p['action'])} |")
    add("")

    add("## Method and limits\n")
    add("- Area score: 100 minus, per finding, severity amount (critical 25, high 12, medium 6, low 2) × (0.5 + 0.5 × share of pages affected). Content and AI readiness blend 70% Jev judgment with 30% rules. Performance blends 50% Lighthouse mobile with 50% crawl observations.")
    add("- Overall: weighted mean of scored areas; unscored areas are excluded, never zero.")
    add("- Impact: severity weight × (0.6 + 0.4 × reach) × (0.6 + 0.8 × highest Jev importance of affected pages), scaled to 100.")
    add("- Jev answers are decisive at confidence 0.80 (Choice, Score) or P(yes) at least 0.80 or at most 0.20 (Noul). Others are flagged to verify.")
    lg = vm["ledger"]
    add(f"- Jev: model {lg.get('model_returned') or 'n/a'}, {lg.get('requests', 0)} requests, {lg.get('input_tokens', 0)} input tokens, {lg.get('failed', 0)} failed, cost ${(lg.get('cost_usd') or 0):.4f}.")
    if vm.get("dfs"):
        x = vm["dfs"]
        add(f"- DataForSEO: {x['ledger']['requests']} requests, ${x['ledger']['cost_usd']:.4f}" + (f"; data reused from the collection at {x['reused_from']}" if x.get("reused_from") else "") + ". Rankings, volumes, difficulty and traffic (ETV) are DataForSEO estimates. No Search Console or analytics data was used.")
    else:
        add("- No Search Console, analytics, backlink or keyword data was used (run with --full for DataForSEO).")
    add("- Scores rank work; they do not predict rankings or traffic.")
    add(f"\n_Generated by jev-seo {d['tool']['version']}._\n")
    path.write_text("\n".join(L))
    return path

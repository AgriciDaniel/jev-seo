"""jevseo command line.

  audit  <url>        crawl, check, measure, judge, score -> audit.json + digest.md
  render <dir>        audit.json (+ narrative.json) -> report.pdf, report.xlsx, report.md
  run    <url>        audit then render in one step
  rescore <dir>       rebuild findings and scores from a saved audit (no network, no spend)
  doctor              check dependencies and credentials without printing secrets
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from jevseo import VERSION

STAGES = ["Crawl", "Rule checks", "DataForSEO", "Jev judgments", "PageSpeed", "Scoring", "Render"]
T0 = time.monotonic()


def log(msg: str) -> None:
    """Progress line with elapsed time, flushed immediately so callers see it live."""
    e = int(time.monotonic() - T0)
    print(f"[jevseo {e // 60:02d}:{e % 60:02d}] {msg}", file=sys.stderr, flush=True)


def stage(n: int, detail: str = "") -> None:
    log(f"== {n}/{len(STAGES)} {STAGES[n - 1]}" + (f": {detail}" if detail else ""))


def default_out(url: str) -> Path:
    host = urlparse(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    return Path.cwd() / "jev-seo-reports" / f"{re.sub(r'[^a-z0-9.-]', '-', host)}-{stamp}"


def audit(args) -> Path:
    from jevseo import checks, crawl, dfs as dfs_mod, jev, psi, score

    out = Path(args.out) if args.out else default_out(args.url)
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    timings = {}

    log(f"Auditing {args.url}: up to {args.max_pages} pages{', full mode with DataForSEO' if args.full else ''}. Typical run {'2 to 5' if args.full else '1 to 4'} minutes; progress follows.")
    stage(1, "robots.txt, sitemaps, then pages")
    t = time.monotonic()
    site = crawl.crawl(args.url, max_pages=args.max_pages, max_depth=args.max_depth, render_mode=args.render, time_budget=args.time_budget, log=log)
    timings["crawl"] = round(time.monotonic() - t, 1)

    stage(2)
    t = time.monotonic()
    findings = checks.run_checks(site)
    timings["checks"] = round(time.monotonic() - t, 1)
    log(f"{len(findings)} rule findings from {len(checks.RULES)} rules")

    pages = [p for p in checks.html_pages(site) if checks.indexable(p) or p["url"] == site["final_url"]]
    pages.sort(key=lambda p: (p.get("depth", 99), -p.get("inlinks", 0)))

    dfs = None
    stage(3, f"location {args.location_code}, language {args.language}, budget ${args.dfs_budget:.2f}" if args.full else "skipped (add --full for rankings, keywords and backlinks)")
    t = time.monotonic()
    if args.full and args.reuse_dfs:
        prev = json.loads((Path(args.reuse_dfs) / "audit.json").read_text())
        if prev["site"]["domain"] != site["domain"] or not prev.get("dataforseo"):
            raise SystemExit(f"--reuse-dfs: {args.reuse_dfs} holds no DataForSEO data for {site['domain']}")
        dfs = prev["dataforseo"] | {"reused_from": prev["run"]["finished_at"]}
        log(f"reusing DataForSEO data collected {prev['run']['finished_at']} (no new spend)")
    elif args.full:
        home = next((p for p in pages if p["url"] == site["final_url"]), {})
        dfs = dfs_mod.collect(site["domain"], home, args.location_code, args.language, args.dfs_budget, log=log)
    timings["dataforseo"] = round(time.monotonic() - t, 1)

    stage(4, "skipped (--no-jev)" if args.no_jev else f"{min(len(pages), args.jev_pages)} pages, budget ${args.jev_budget:.2f}")
    t = time.monotonic()
    if args.no_jev:
        judged = {"available": False, "skipped": "disabled with --no-jev", "site": None, "pages": {}, "pairs": [], "ledger": {}, "questions": {}}
    else:
        judged = jev.judge(site, pages[: args.jev_pages], args.jev_budget, log=log, dfs=dfs)
    timings["jev"] = round(time.monotonic() - t, 1)
    findings += score.jev_findings(site, judged) + score.dfs_findings(site, judged, dfs)

    stage(5, "skipped (--no-psi)" if args.no_psi else f"{args.psi_pages} pages x mobile and desktop, about 30 to 60 seconds")
    t = time.monotonic()
    perf = None
    if not args.no_psi:
        ranked = sorted(pages[1:], key=lambda p: -(score.importance_of(p["url"], judged) or 0))
        perf = psi.run([site["final_url"]] + [p["url"] for p in ranked[: args.psi_pages - 1]], log=log)
        findings += perf_findings(perf)
    timings["pagespeed"] = round(time.monotonic() - t, 1)

    stage(6)
    scores = score.score(site, findings, judged, perf, dfs)
    acts = score.actions(findings, judged, len(checks.html_pages(site)))
    data = {
        "schema_version": "1.0",
        "tool": {"name": "jev-seo", "version": VERSION},
        "run": {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "timings_s": timings,
            "options": {k: v for k, v in vars(args).items() if k not in ("func", "out")},
        },
        "site": {k: v for k, v in site.items() if k != "pages"},
        "pages": site["pages"],
        "findings": findings,
        "passed_rules": checks.passed_rules(findings),
        "jev": judged,
        "performance": perf,
        "dataforseo": dfs,
        "scores": scores,
        "actions": acts,
    }
    (out / "audit.json").write_text(json.dumps(data, indent=1, default=str))
    (out / "digest.md").write_text(digest(data))
    log(f"audit written: {out / 'audit.json'}")
    log(f"score {scores['overall']} ({scores['grade']}), {len(acts)} actions, Jev ${judged.get('ledger', {}).get('cost_usd', 0):.4f}" + (f", DataForSEO ${dfs['ledger']['cost_usd']:.4f}" if dfs else ""))
    return out


def perf_findings(perf: dict | None) -> list[dict]:
    """Findings from PageSpeed results: real-user Core Web Vitals and the Lighthouse lab score."""
    from jevseo import checks

    findings: list[dict] = []
    if not perf:
        return findings
    for run in perf["runs"]:
        field = (run.get("field_url") or run.get("field_origin") or {})
        poor = [m for m, v in field.get("metrics", {}).items() if m in ("LCP", "INP", "CLS") and v["rating"] != "good"]
        if run["strategy"] == "mobile" and poor and not any(f["id"] == "cwv_field" for f in findings):
            findings.append({
                "id": "cwv_field", "origin": "rule", "category": "performance",
                "severity": "high" if any(field["metrics"][m]["rating"] == "poor" for m in poor) else "medium",
                "title": "Core Web Vitals not in the good range for real mobile users",
                "fix": "Work through the PageSpeed opportunities for " + ", ".join(poor) + ", starting with the largest savings.",
                "source": checks.SRC["cwv"], "effort": 3, "heuristic": False, "urls": [run["url"]], "count": 1,
                "evidence": "; ".join(f"{m} p75 {field['metrics'][m]['p75']}{field['metrics'][m]['unit']} ({field['metrics'][m]['rating']})" for m in poor) + (" (origin-level field data)" if not run.get("field_url") else ""),
                "detail": {},
            })
        lab = run.get("scores", {}).get("performance")
        if run["strategy"] == "mobile" and lab is not None and lab < 50 and not any(f["id"] == "lab_performance" for f in findings):
            findings.append({
                "id": "lab_performance", "origin": "rule", "category": "performance", "severity": "medium",
                "title": "Low Lighthouse mobile performance score", "fix": "Reduce render-blocking resources, image weight and JavaScript; see the PageSpeed opportunities.",
                "source": checks.SRC["cwv"], "effort": 3, "heuristic": False, "urls": [run["url"]], "count": 1,
                "evidence": f"Lighthouse mobile performance {lab}/100 (one synthetic load)", "detail": {},
            })
    return findings


def digest(d: dict) -> str:
    """Compact, evidence-only brief for the lead agent writing the narrative."""
    s, j = d["scores"], d["jev"]
    pages = [p for p in d["pages"] if p.get("kind") == "page" and p.get("status") == 200]
    lines = [
        f"# Digest: {d['site']['domain']}",
        f"Audited {d['run']['finished_at']}. Pages fetched: {len(d['pages'])}; HTML pages: {len(pages)}.",
        f"Overall {s['overall']} ({s['grade']}). " + ", ".join(f"{s['category_names'][c]} {v if v is not None else 'n/a'}" for c, v in s["categories"].items()),
        f"Caps: {'; '.join(s['caps']) or 'none'}. Completeness: {s['completeness']}",
    ]
    if j.get("site"):
        site = j["site"]
        lines.append("Jev site view (copy these numbers exactly):")
        for key, a in site.items():
            conf = f", confidence {a['confidence']:.2f}" if "confidence" in a else ""
            val = a["value"] if isinstance(a["value"], str) else f"{a['value']:.2f}"
            lines.append(f"- {key}: {val}{conf}, band {a['band']}")
    home = next((p for p in pages if p["url"] == d["site"]["final_url"]), None)
    if home:
        lines.append(f"Homepage: title={home.get('title')!r}; h1={home.get('h1')[:2]!r}; meta={home.get('meta_description')!r}")
    lines.append("\n## Actions (id, priority, impact, effort, count, title, evidence, review flags)")
    for a in d["actions"]:
        lines.append(f"- {a['action_id']} {a['priority']} impact {a['impact']} effort {a['effort']} [{a['origin']}/{a['category']}/{a['severity']}] {a['title']} x{a['count']}: {a['evidence']}" + (f" (needs review: {a['needs_review']})" if a["needs_review"] else ""))
        site_host = urlparse(d["site"]["final_url"]).netloc
        rel = lambda u: (urlparse(u).path or "/") if urlparse(u).netloc == site_host else urlparse(u).netloc + (urlparse(u).path or "/")  # noqa: E731
        lines.append("  URLs: " + ", ".join(rel(u) for u in a["urls"][:8]) + (f" +{a['count'] - 8} more" if a["count"] > 8 else ""))
    robots = d["site"]["robots"]
    lines.append(f"\nRobots: search bots {robots['search_bots']}; AI bots checked ({len(robots['ai_bots'])}): {robots['ai_bots']}")
    lines.append("\n## No issue detected by rule")
    lines.append(", ".join(d["passed_rules"]))
    perf = d.get("performance") or {}
    for r in perf.get("runs", []):
        if "error" in r:
            lines.append(f"- PSI {r['strategy']} {r['url']}: {r['error']}")
        else:
            f = r.get("field_url") or r.get("field_origin") or {}
            level = "URL-level" if r.get("field_url") else "origin-level" if r.get("field_origin") else "no field data"
            metrics = "; ".join(f"{m} {v['p75']}{v['unit']} {v['rating']}" for m, v in f.get("metrics", {}).items()) or "none"
            lines.append(f"- PSI {r['strategy']} {r['url']}: scores {r['scores']}; field ({level}) {metrics}")
    x = d.get("dataforseo")
    if x and x.get("available"):
        ov = x.get("overview") or {}
        kj = j.get("keywords") or {}
        rel = lambda kw: f"{kj[kw]['relevance']['value']:.2f}" if kj.get(kw) else "n/a"  # noqa: E731
        lines.append(f"\n## DataForSEO (location {x['location_code']}, language {x['language_code']}; DataForSEO estimates, not measured traffic)")
        lines.append(f"Ranking keywords: {ov.get('count')}; estimated monthly organic traffic (ETV): {round(ov['etv']) if ov.get('etv') is not None else 'n/a'}; positions: 1: {ov.get('pos_1')}, 2-3: {ov.get('pos_2_3')}, 4-10: {ov.get('pos_4_10')}, 11-20: {ov.get('pos_11_20')}, 21-100: {sum((ov.get(k) or 0) for k in ('pos_21_30','pos_31_40','pos_41_50','pos_51_60','pos_61_70','pos_71_80','pos_81_90','pos_91_100'))}")
        for k in (x.get("ranked") or [])[:15]:
            lines.append(f"- ranks: {k['keyword']} | position {k.get('position')} | {k.get('volume')}/mo | {urlparse(k.get('url') or '').path or '/'} | Jev relevance {rel(k['keyword'])}")
        bl = x.get("backlinks") or {}
        lines.append(f"Backlinks: {bl.get('backlinks')} from {bl.get('referring_domains')} referring domains; broken backlinks {bl.get('broken_backlinks')}; DataForSEO rank {bl.get('rank')}")
        lines.append("Referring domains, site and search competitors: " + ", ".join(f"{r['domain']} {r['referring_domains']}" for r in x.get("referring_domains") or []))
        lines.append("Search competitors (platforms excluded): " + ", ".join(f"{c['domain']} ({c['shared_keywords']} shared)" for c in x.get("competitors") or []))
        for sp in x.get("serps") or []:
            lines.append(f"- SERP {sp['keyword']}: own position {sp['own_position']}; AI Overview {'yes' if sp['ai_overview'] else 'no'}{' (cites site)' if sp['ai_overview_cites_site'] else ''}; top 3: {', '.join(t['domain'] for t in sp['top'][:3])}")
        m = x.get("mentions") or {}
        lines.append(f"AI answer mentions of the domain (LLM Mentions): {m.get('total')} total")
        lines.append(f"DataForSEO ledger: {x['ledger']['requests']} requests, ${x['ledger']['cost_usd']:.4f}, failed {x['ledger']['failed']}, skipped {x['ledger']['skipped_budget']}")
    if j.get("not_judged"):
        lines.append(f"\nNot judged by Jev (failed or budget cap): {len(j['not_judged'])} pages. Their absence of Jev findings is not a pass.")
    if j.get("ledger"):
        lines.append(f"\nJev ledger: {j['ledger']}")
    return "\n".join(lines) + "\n"


def rescore(args) -> None:
    """Rebuild findings, scores, actions and digest from a saved audit, without network or spend."""
    from jevseo import checks, score

    folder = Path(args.dir)
    d = json.loads((folder / "audit.json").read_text())
    site = dict(d["site"], pages=d["pages"])
    findings = checks.run_checks(site) + score.jev_findings(site, d["jev"]) + score.dfs_findings(site, d["jev"], d.get("dataforseo")) + perf_findings(d.get("performance"))
    d["findings"] = findings
    d["passed_rules"] = checks.passed_rules(findings)
    d["scores"] = score.score(site, findings, d["jev"], d.get("performance"), d.get("dataforseo"))
    d["actions"] = score.actions(findings, d["jev"], len(checks.html_pages(site)))
    d["run"]["rescored_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (folder / "audit.json").write_text(json.dumps(d, indent=1, default=str))
    (folder / "digest.md").write_text(digest(d))
    log(f"rescored: {d['scores']['overall']} ({d['scores']['grade']}), {len(d['actions'])} actions. Action IDs may have changed; re-check narrative.json.")


def render(args) -> None:
    from jevseo.report import build

    stage(7, args.formats)
    build(Path(args.dir), formats=args.formats.split(","), log=log)


def run(args) -> None:
    args.out = audit(args)
    args.dir = str(args.out)
    render(args)


def doctor(_args) -> None:
    from jevseo.env import secret

    report = {"version": VERSION, "python": sys.version.split()[0]}
    for mod in ["requests", "bs4", "lxml", "matplotlib", "jinja2", "weasyprint", "openpyxl", "playwright"]:
        try:
            __import__(mod)
            report[mod] = "ok"
        except ImportError as err:
            report[mod] = f"missing ({err.name})"
    report["TYPESAFE_API_KEY"] = "present" if secret("TYPESAFE_API_KEY") else "missing: Jev judgments will be skipped"
    report["PAGESPEED_API_KEY"] = "present" if secret("PAGESPEED_API_KEY") else "missing: PageSpeed runs unkeyed and may be rate limited"
    report["DATAFORSEO"] = "present (needed only for --full)" if secret("DATAFORSEO_USERNAME") and secret("DATAFORSEO_PASSWORD") else "missing: --full mode unavailable"
    print(json.dumps(report, indent=1))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jevseo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)

    def audit_opts(p):
        p.add_argument("url")
        p.add_argument("--out", help="output directory (default ./jev-seo-reports/<domain>-<stamp>)")
        p.add_argument("--max-pages", type=int, default=60)
        p.add_argument("--max-depth", type=int, default=5)
        p.add_argument("--time-budget", type=int, default=600, help="crawl time budget in seconds")
        p.add_argument("--render", choices=["auto", "always", "never"], default="auto")
        p.add_argument("--jev-pages", type=int, default=60, help="maximum pages sent to Jev")
        p.add_argument("--jev-budget", type=float, default=0.25, help="hard Jev spend cap in USD")
        p.add_argument("--no-jev", action="store_true")
        p.add_argument("--psi-pages", type=int, default=3, help="pages measured with PageSpeed Insights")
        p.add_argument("--no-psi", action="store_true")
        p.add_argument("--full", action="store_true", help="add DataForSEO rankings, keywords, competitors, backlinks, SERPs and AI mentions (paid per call)")
        p.add_argument("--location-code", type=int, default=2840, help="DataForSEO location code (2840 = United States)")
        p.add_argument("--language", default="en", help="DataForSEO language code")
        p.add_argument("--dfs-budget", type=float, default=1.0, help="hard DataForSEO spend cap in USD")
        p.add_argument("--reuse-dfs", metavar="DIR", help="with --full: reuse DataForSEO data from an earlier audit folder of the same site (no new spend)")

    p = sub.add_parser("audit")
    audit_opts(p)
    p.set_defaults(func=audit)
    p = sub.add_parser("render")
    p.add_argument("dir")
    p.add_argument("--formats", default="pdf,xlsx,md")
    p.set_defaults(func=render)
    p = sub.add_parser("run")
    audit_opts(p)
    p.add_argument("--formats", default="pdf,xlsx,md")
    p.set_defaults(func=run)
    p = sub.add_parser("rescore")
    p.add_argument("dir")
    p.set_defaults(func=rescore)
    p = sub.add_parser("doctor")
    p.set_defaults(func=doctor)
    args = ap.parse_args(argv)
    args.func(args)

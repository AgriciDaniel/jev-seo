"""PageSpeed Insights v5: Chrome UX Report field data plus Lighthouse lab scores.

Field data describes real Chrome users over the trailing 28 days and exists
only for URLs or origins with enough traffic. Lab scores are one synthetic
load. The report keeps the two apart.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from jevseo.env import secret

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]
# web.dev/articles/vitals: good and poor boundaries at the 75th percentile
THRESHOLDS = {
    "LARGEST_CONTENTFUL_PAINT_MS": ("LCP", "ms", 2500, 4000),
    "INTERACTION_TO_NEXT_PAINT": ("INP", "ms", 200, 500),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": ("CLS", "", 0.1, 0.25),
    "FIRST_CONTENTFUL_PAINT_MS": ("FCP", "ms", 1800, 3000),
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": ("TTFB", "ms", 800, 1800),
}
LAB = {"largest-contentful-paint": "LCP", "cumulative-layout-shift": "CLS", "total-blocking-time": "TBT", "first-contentful-paint": "FCP", "speed-index": "Speed Index"}


def _field(block: dict | None) -> dict | None:
    if not block or not block.get("metrics"):
        return None
    out = {}
    for key, (name, unit, good, poor) in THRESHOLDS.items():
        m = block["metrics"].get(key)
        if not m:
            continue
        value = m["percentile"] / 100 if key == "CUMULATIVE_LAYOUT_SHIFT_SCORE" else m["percentile"]
        rating = "good" if value <= good else "needs improvement" if value <= poor else "poor"
        out[name] = {"p75": value, "unit": unit, "rating": rating, "good_max": good, "poor_min": poor}
    return {"overall": block.get("overall_category"), "metrics": out}


def run_one(url: str, strategy: str, key: str | None) -> dict:
    params = [("url", url), ("strategy", strategy)] + [("category", c) for c in CATEGORIES]
    if key:
        params.append(("key", key))
    try:
        r = requests.get(API, params=params, timeout=120)
    except requests.RequestException as err:
        return {"url": url, "strategy": strategy, "error": type(err).__name__}
    if r.status_code != 200:
        return {"url": url, "strategy": strategy, "error": f"HTTP {r.status_code}"}
    data = r.json()
    lh = data.get("lighthouseResult", {})
    audits = lh.get("audits", {})
    opportunities = sorted(
        (
            {"id": k, "title": a.get("title"), "savings_ms": round(a.get("details", {}).get("overallSavingsMs") or 0)}
            for k, a in audits.items()
            if a.get("details", {}).get("type") == "opportunity" and (a.get("details", {}).get("overallSavingsMs") or 0) > 100
        ),
        key=lambda o: -o["savings_ms"],
    )[:8]
    return {
        "url": url,
        "strategy": strategy,
        "fetched_at": lh.get("fetchTime"),
        "lighthouse_version": lh.get("lighthouseVersion"),
        "scores": {c: round(lh["categories"][c]["score"] * 100) for c in CATEGORIES if lh.get("categories", {}).get(c, {}).get("score") is not None},
        "lab": {name: {"value": audits[k].get("numericValue"), "display": audits[k].get("displayValue")} for k, name in LAB.items() if k in audits},
        "field_url": _field(None if data.get("loadingExperience", {}).get("origin_fallback") else data.get("loadingExperience")),
        "field_origin": _field(data.get("originLoadingExperience")),
        "opportunities": opportunities,
    }


def run(urls: list[str], log=print) -> dict:
    key = secret("PAGESPEED_API_KEY")
    jobs = [(u, s) for u in urls for s in ("mobile", "desktop")]
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(run_one, u, s, key): (u, s) for u, s in jobs}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            note = r.get("error") or f"performance {r['scores'].get('performance', 'n/a')}"
            log(f"PageSpeed {len(results)}/{len(jobs)}: {r['strategy']} {r['url']} ({note})")
    results.sort(key=lambda r: (jobs.index((r["url"], r["strategy"]))))
    ok = sum(1 for r in results if "error" not in r)
    log(f"PageSpeed Insights: {ok}/{len(results)} runs succeeded")
    return {"source": "https://developers.google.com/speed/docs/insights/v5/get-started", "keyed": bool(key), "runs": results}

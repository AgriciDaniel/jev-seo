# Method

## Data flow

```
homepage URL
  -> crawl.py     robots.txt, sitemaps, BFS over internal links, redirects recorded
                  separately, JavaScript rendering for shell pages, host/HTTPS/404/llms.txt probes,
                  HEAD checks on uncrawled internal targets and a sample of outbound links
  -> checks.py    50 deterministic rules, each with severity, fix, source URL, effort, heuristic flag
  -> jev.py       site request, one request per page, batched pair requests; ledger and budget cap
  -> dfs.py       (--full) DataForSEO: overview, ranked keywords, competitors, backlinks, bulk referring
                  domains, keyword suggestions and ideas, domain gaps, live SERPs, LLM mentions; budget cap
  -> jev.py       (--full) keyword relevance, other-brand check and best page, 8 keywords per request
  -> psi.py       PageSpeed Insights mobile and desktop: CrUX field data and Lighthouse lab scores
  -> score.py     Jev findings, area scores, overall score with caps, ranked actions
  -> audit.json   the single source for every export
  -> narrative.json (lead agent)
  -> report/      one view model -> report.pdf (WeasyPrint, inline SVG charts), report.xlsx, report.md
```

## Formulas

- Area score: 100 minus, per finding, severity amount (critical 25, high
  12, medium 6, low 2, info 0) times (0.5 + 0.5 x reach). Reach is the
  share of HTML pages affected, or 1 for site-wide findings.
- Content quality and AI readiness: 70% Jev judgment, 30% rules.
  Performance: 50% Lighthouse mobile performance, 50% crawl observations.
- Overall: weighted mean of scored areas (crawl 20, on-page 15, content
  20, links 10, structured data 8, AI 12, performance 10, security 5).
  Unscored areas are excluded, never zero. Blocked site caps at 20; no
  reliable HTTPS caps at 60.
- Impact: severity weight (10, 6, 3, 1) x (0.6 + 0.4 x reach) x (0.6 + 0.8
  x highest Jev importance of the affected pages), scaled so the top
  action is 100.
- Priority: P1 critical, or high with impact 40 or more. P2 impact 30 or
  more, or any high. P3 otherwise. Quick win: impact 35 or more with
  effort of hours.

## Known limits

- Page cap and time budget mean large sites are sampled. Orphan and depth
  findings only see links on crawled pages.
- No Search Console, analytics, backlink, keyword volume or SERP data.
  Nothing measures rankings, traffic or revenue.
- Jev answers are uncalibrated model judgments for this task family; no
  labelled evaluation set exists yet. Treat "to verify" answers as signals.
- Lighthouse lab scores vary run to run; field data exists only for sites
  with enough Chrome traffic.
- No spreadsheet engine was available when building, so workbook formulas
  (COUNTIF, COUNTIFS) were verified structurally, not recalculated.

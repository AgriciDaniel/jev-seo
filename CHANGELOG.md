# Changelog

## 0.1.0 (2026-09-22)

First release.

- Live crawl from a homepage: robots.txt and Crawl-delay, sitemaps, internal links, redirects kept separate from pages, JavaScript rendering for script-only pages, a private-network guard on every hop, charset-safe decoding.
- 52 deterministic rules tied to Google Search Central and web standards, including structured-data properties Google requires for rich results. Heuristics are labelled.
- Jev (TypeSafe System One) judgments batched per page and per site, plus competing page pairs. Question wording and the decisiveness measure were chosen by A/B tests against blind labels; see `references/evaluation.md`.
- PageSpeed Insights: Chrome UX Report field data and Lighthouse lab scores.
- Optional `--full` mode with DataForSEO: rankings, keywords, competitors, referring domains, live SERPs, AI answer mentions, filtered by Jev relevance and mapped to pages. Hard budget caps and per-call cost ledgers for Jev and DataForSEO. `--reuse-dfs` avoids paying twice.
- Reports: designed PDF, Excel action tracker, Markdown with charts, all from one `audit.json`. The narrative is checked for unknown action IDs, numbers the audit does not contain and mismatched effort bands.
- `rescore` rebuilds findings offline. 37 offline tests.

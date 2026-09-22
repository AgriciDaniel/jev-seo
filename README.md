<a name="jev-seo"></a>

# ![jev-seo](docs/assets/banner.png)

[![version](https://img.shields.io/badge/version-0.1.1-d45bb6?style=flat-square&labelColor=0b0b0b)](CHANGELOG.md)
[![checks](https://github.com/AgriciDaniel/jev-seo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/AgriciDaniel/jev-seo/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-666666?style=flat-square&labelColor=0b0b0b)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-666666?style=flat-square&labelColor=0b0b0b)](pyproject.toml)
[![jev](https://img.shields.io/badge/judged%20by-jev--1.13.0-d45bb6?style=flat-square&labelColor=0b0b0b)](https://docs.typesafe.ai/primitives)

jev-seo is a **live SEO audit for any website, from one homepage URL**. It crawls the site, checks it against 52 rules tied to Google Search Central, measures Core Web Vitals, and asks [Jev](https://docs.typesafe.ai/primitives), TypeSafe's System One model, typed questions about every page. Code scores and ranks every fix, and you get a designed PDF, an Excel action tracker and a Markdown report, all built from the same data.

It runs as a Claude Code skill (`/jev-seo https://example.com`) or from the command line. The standard mode needs no SEO data subscription and costs about a cent in Jev per site. An optional `--full` mode adds rankings, keywords and backlinks from DataForSEO for about 0.30 USD.

<p align="left"><img src="docs/assets/preview-summary.jpg" alt="Cover, executive summary and plan of a jev-seo PDF report" width="880"></p>

## Why it is useful

| What you get | Why it matters |
| --- | --- |
| A live crawl, not a template | robots.txt, sitemaps, redirects, broken links, canonicals, structured data and JavaScript-only pages, checked on the real site in about a minute. |
| Meaning, judged by Jev | Page type, search intent, importance, helpfulness, specificity, trust, citability, title and meta fit, and pages competing for the same searches, each a typed answer with its probabilities kept. |
| Ranked, explained fixes | Every action has an ID, priority, impact, effort, evidence, a fix and an official source. Heuristics are labelled as heuristics. |
| Honest numbers | Missing data stays missing. Scores rank work; they never predict rankings or traffic. The written summary is checked against the audit before it renders. |
| Three formats, one source | PDF for the client, XLSX to track the work, Markdown for GitHub and Obsidian, all from one `audit.json`. |

**Start here:** [Example report](examples/claude-seo.md/) · [Skill workflow](SKILL.md) · [How Jev is asked](references/judgments.md) · [How far to trust it](references/evaluation.md) · [Method and formulas](references/method.md)

## See the output

A full audit of [claude-seo.md](https://claude-seo.md), run with `--full` on 2026-09-22. Every file is in [`examples/claude-seo.md/`](examples/claude-seo.md/): [report.pdf](examples/claude-seo.md/report.pdf) · [report.xlsx](examples/claude-seo.md/report.xlsx) · [report.md](examples/claude-seo.md/report.md) · [digest.md](examples/claude-seo.md/digest.md) · [narrative.json](examples/claude-seo.md/narrative.json).

**PDF: how the audit was made, the scorecard and the priorities**

<p align="left"><img src="docs/assets/preview-method.jpg" alt="Pipeline, scorecard and priority pages" width="880"></p>

**PDF: search visibility from DataForSEO, filtered by Jev**

<p align="left"><img src="docs/assets/preview-visibility.jpg" alt="Rankings, keyword opportunities and site structure pages" width="880"></p>

**PDF: how Jev reads the site**

<p align="left"><img src="docs/assets/preview-jev.jpg" alt="Jev judgment cards, quality heatmap and where to invest" width="880"></p>

**XLSX: the Actions sheet is the editable status tracker** (rendered preview of the real workbook cells)

<p align="left"><img src="docs/assets/preview-xlsx.png" alt="Actions sheet of the jev-seo workbook" width="880"></p>

**Markdown: renders on GitHub and in Obsidian, with charts**

<p align="left"><img src="docs/assets/preview-md.png" alt="Markdown report rendered" width="560"></p>

**Live progress while it runs** (lines from a real run)

<p align="left"><img src="docs/assets/preview-terminal.png" alt="jevseo progress output" width="720"></p>

| Impact versus effort | Keywords worth winning | Where to invest |
| --- | --- | --- |
| ![Impact versus effort](docs/assets/impact_effort.png) | ![Keyword opportunities](docs/assets/opportunities.png) | ![Where to invest](docs/assets/invest.png) |

## Try it

Python 3.10+. WeasyPrint needs the Pango text library: on Debian or Ubuntu `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`, on macOS `brew install pango`, on Fedora it is usually present ([WeasyPrint install notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)).

```sh
git clone https://github.com/AgriciDaniel/jev-seo.git
cd jev-seo
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                           # add TYPESAFE_API_KEY (optional keys are listed inside)
bin/jevseo doctor                              # dependencies and keys, never prints values
bin/jevseo run https://example.com             # audit and render with an automatic summary
```

Optional: `pip install playwright && playwright install chromium` renders pages whose content only appears after JavaScript runs; without it those pages are audited from their raw HTML. `pdftoppm` (poppler) is only used by the Claude Code skill to look at rendered pages.

Reports land in `jev-seo-reports/<domain>-<stamp>/`. The offline tests need no keys and spend nothing:

```sh
python -m unittest discover -s tests -v
```

In Claude Code, link the folder as a skill (`ln -s "$PWD" ~/.claude/skills/jev-seo`) and run `/jev-seo https://example.com`. The skill runs the audit in the background, relays progress, reads the digest, checks surprising findings, writes the narrative and renders the three reports.

```sh
bin/jevseo audit https://example.com                            # crawl, rules, Jev, PageSpeed -> audit.json + digest.md
bin/jevseo render jev-seo-reports/<dir>                         # -> report.pdf, report.xlsx, report.md
bin/jevseo audit https://example.com --full                     # add DataForSEO (paid per call)
bin/jevseo audit https://example.com --full --reuse-dfs <dir>   # reuse DataForSEO data already collected
bin/jevseo rescore jev-seo-reports/<dir>                        # rebuild findings and scores offline, no spend
```

## What runs where, and what it costs

<p align="left"><img src="docs/assets/pipeline.svg" alt="How a jev-seo audit runs" width="880"></p>

| Part | Where it runs | Cost |
| --- | --- | --- |
| Crawl, rules, scoring, charts, PDF, XLSX, MD | Your machine | Free |
| JavaScript rendering for script-only pages | Local headless Chromium (Playwright, optional) | Free |
| Core Web Vitals and Lighthouse | Google PageSpeed Insights API | Free |
| Page, site and keyword judgments | TypeSafe Jev API | 0.042 USD per million input tokens; about 0.00015 USD per page |
| Rankings, keywords, competitors, backlinks, live SERPs, AI mentions (`--full`) | DataForSEO API | Reported per call; about 0.30 USD per site |

Both paid APIs sit behind hard caps (`--jev-budget`, default 0.25 USD; `--dfs-budget`, default 1.00 USD) checked before every request, and every call is in the report's cost ledger. Keys come from the environment or a `.env` file (see [.env.example](.env.example)): `TYPESAFE_API_KEY`, optionally `PAGESPEED_API_KEY` (without it PageSpeed is often rate limited), and for `--full` `DATAFORSEO_USERNAME` and `DATAFORSEO_PASSWORD`. Without the TypeSafe key the audit still runs, marks the Jev sections as not assessed, and labels the score a partial audit.

## How far to trust it

Measured on 2026-09-22 and recorded in [references/evaluation.md](references/evaluation.md):

| Check | Result |
| --- | --- |
| Rule and crawl facts, re-fetched independently from the live site | All verified; word counts within 5% |
| DataForSEO internal consistency (keyword counts, position buckets, traffic sum, referring domains) | Exact |
| PageSpeed, fresh independent run | Identical scores and field values |
| Jev repeatability, same 59 pages twice | Scores moved 0.03 or less on average; confident page types agreed 44/44 |
| Jev against a blind second judge, answers Jev marks decisive | Helpfulness and specificity 28/29, opens with the point 23/23, next step 16/16, keyword relevance 27/30 |

The blind judge is a separate model, not a human, so this shows Jev is consistent and reasonable, not that it is right. Answers outside the decisive band are flagged "to verify" in every format. Question wording and the decisiveness measure were chosen by A/B tests; the results are in [references/judgments.md](references/judgments.md).

## What works

- Polite crawl: robots.txt and Crawl-delay, sitemap indexes, redirects recorded separately, host and HTTPS probes, soft 404 check, llms.txt, a private-network guard on every redirect hop.
- 52 rules across crawl and indexing, on-page, content, links, structured data (including properties Google requires for rich results), AI crawler access, performance and security.
- Jev: 13 page questions, 5 site questions, competing page pairs, and in `--full` mode keyword relevance, other-brand checks and the best page for each keyword. The homepage type is set by code, never asked.
- DataForSEO in `--full` mode: ranked keywords, estimated traffic, competitors, referring domains compared, keyword suggestions, ideas and gaps, live Google results with AI Overview citations, LLM mentions.
- PDF: cover, summary, plan, pipeline, scorecard, impact versus effort, site map, rankings, keyword opportunities, Jev cards, quality heatmap, where to invest, findings by area, page inventory, method, sources.
- XLSX: Actions tracker with dropdowns, Summary counting from it, Pages, raw Jev judgments with probabilities, Technical, Performance, Rankings, Opportunities, Competitors, SERPs, AI mentions, Charts, Method.
- Markdown with charts, Mermaid pies and a contents line.
- Narrative checks: unknown action IDs are refused; numbers not in the audit and mismatched effort bands are flagged.

This is an evidence tool, not a rank tracker or a replacement for Search Console. It does not measure traffic, revenue or rankings over time.

## Layout

```
SKILL.md              Claude Code skill: workflow, options, rules
bin/jevseo            runs the package from any directory
jevseo/               crawl, parse, checks, jev, dfs, psi, score, cli
jevseo/report/        view model, charts, pdf, xlsx, md
jevseo/templates/     report HTML and CSS
references/           narrative contract, Jev question registry, evaluation, method
examples/             a complete example audit
docs/assets/          README images
tests/                offline tests, no network and no spend
```

## Limits

Large sites are sampled at the page cap (60 by default) and the report says so. Jev thresholds are not yet tuned against human labels. PageSpeed lab scores vary between runs, and field data exists only for sites with enough Chrome traffic. DataForSEO volumes, difficulty and traffic are estimates. Rules marked heuristic are editorial conventions, not search engine requirements.

## License

[MIT](LICENSE). The bundled fonts in `jevseo/fonts/` are Inter and JetBrains Mono under the SIL Open Font License (license texts alongside). Jev is a product of TypeSafe AI; DataForSEO and PageSpeed Insights are third-party services with their own terms.

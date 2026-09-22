# Jev judgment registry

All questions go to `POST https://api.typesafe.ai/v1/systemone` with
`model: jev-latest` (resolved to `jev-1.13.0` on 2026-09-21). Question
definitions live in `jevseo/jev.py`; this file explains them.

## Design rules applied

- One request per page carries every page question over the same state
  (independent questions batch; docs.typesafe.ai/primitives).
- Code never asks what it can see. No meta description means no
  `meta_fit` question; no H1 means no `h1_fit`.
- Every Choice has a no-match option (`other`, `unclear`).
- Score levels describe situations, low to high, and are normalised to
  0 to 1 as `score / (levels - 1)`. They are never stretched to 1 to 10.
- Page text in state is capped at 6,000 characters and the truncation is
  flagged in state.
- Bands: a Choice is decisive at confidence 0.80 or above. A Score is
  decisive when 0.80 or more of its probability sits on one side of the
  midpoint (the side every finding threshold uses); spread between two
  neighbouring levels on the same side is not doubt. Noul has no
  confidence field, so it is decisive at P(yes) 0.80 or above, or 0.20 or
  below. Everything else is "to verify".

## Site questions (state: homepage text, navigation, up to 80 page titles)

| id | primitive | asks |
|---|---|---|
| business_model | Choice (9) | what kind of organisation runs the site |
| value_prop | Score (4) | how clearly the homepage says what, for whom, why |
| entity_clarity | Noul | homepage states name, activity and market plainly |
| topical_focus | Score (4) | how coherent the set of page titles is |
| serves_local_area | Noul | the organisation serves a physical area (gates the LocalBusiness schema recommendation) |

## Page questions (state: site context plus the page)

| id | primitive | asks | becomes a finding when |
|---|---|---|---|
| page_type | Choice (11, product and support options structured) | homepage, product or service, listing, article, about, contact, pricing, proof, support, legal, other | used for filtering and charts |
| intent | Choice (6) | informational, commercial, transactional, navigational, local, unclear | commercial pages get the next-step check |
| importance | Score (4) | role in winning customers | weights impact of every action on that page |
| action | Choice (3) | keep or improve, rewrite, merge or remove | rewrite, or merge or remove (never on pages of 600 words or more) |
| helpfulness | Score (4) | satisfies a visitor on its topic | below 0.45 on pages with importance 0.5 or more |
| specificity | Score (4) | generic versus first-hand specifics | below 0.45 |
| trust | Score (4) | evidence of expertise and accountability | below 0.45 on important pages |
| citable | Score (4) | self-contained quotable facts for AI answers | below 0.45 |
| answer_first | Noul (over `page.opening`) | the text after the H1 states the point in two sentences | P(yes) below 0.5 |
| clear_next_step | Noul | the text invites a concrete next action | P(yes) below 0.5 on commercial pages |
| title_fit | Score (4) | title describes the page and invites the click | below 0.45 |
| meta_fit | Score (4) | description summarises what the page delivers | below 0.45 |
| h1_fit | Noul | H1 states the topic | P(yes) below 0.5 |

Policy and contact pages (decisively classified) are excluded from the
content and AI findings other than title and H1 fit.

## Page pairs

Code shortlists pairs whose title and H1 word sets overlap (Jaccard 0.4 or
more, identical text excluded, at most 40 pairs). Ten pairs share one
request as named state fields. Noul: would a searcher treat the two pages
as substitutes? P(yes) 0.6 or more becomes a cannibalization finding.

## Scoring use

Content quality = 70% importance-weighted mean of helpfulness, specificity
and trust, plus 30% rules. AI readiness = 70% of citability, answer-first
and entity clarity, plus 30% rules.

## Cost reference

Observed on typesafe.ai, 2026-09-21: 14 requests, 47,181 input tokens,
0.0020 USD at 0.042 USD per million input tokens (output free). About
3,400 input tokens per page.

## Wording tests

2026-09-22, 30 pages and 40 keywords with blind labels (see evaluation.md).
Adopted: structured product and support options (page type agreement 20/30
to 27/30), a three-option action (decisive 1/30 to 27/30), a name-based
other-brand question (decisive 22/40 to 29/40, agreement 28/40 to 30/40),
and side-of-threshold decisiveness for Scores (side-decisive answers agreed
90 to 97%, the rest about 50%). Kept: helpfulness, specificity, trust and
relevance wording, where structured levels showed no clear gain.

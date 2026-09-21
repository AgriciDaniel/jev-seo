# Evaluation so far (2026-09-22)

What has been measured about the pipeline's trustworthiness, and what has
not. Update this file whenever a new check runs.

## Independent fact check of the rule layer (claude-seo.md)

A fresh reviewer re-fetched the live site without Jev or paid APIs and
checked every rule-based claim in the report: robots.txt, sitemap count,
llms.txt, HTTP to HTTPS, 404 handling, 15 random sitemap URLs, homepage
title, meta, H1, lang, viewport, JSON-LD types, the broken Skool link, the
generic anchors, the 20 images without dimensions, word counts and the
overall score arithmetic. All verified; word counts within 5%. It found
one missed issue (a temporary 307 www redirect, now a rule) and several
wording and citation problems in the narrative and fix texts (now fixed).

## DataForSEO consistency

Ranked keyword rows, the overview count, the position buckets and the
estimated traffic sum all agree exactly; referring domains agree between
the summary and bulk endpoints. The keyword database and the live SERP
agreed on which keywords were outside the top 10. Accuracy of DataForSEO's
own estimates was not checked.

## PageSpeed

An independent fresh run returned the same Lighthouse scores and the same
field (CrUX) values as the report.

## Jev: repeatability (same site, two runs)

59 pages judged twice. Page type 58/59 identical, intent 59/59, suggested
action 54/59. Score answers moved by 0.001 to 0.023 on average; only
answer-first crossed its finding threshold (3/59). When both runs were
decisive on page type they agreed 44/44. Site-level business type flipped
between two review-band answers.

## Jev: agreement with a blind second judge

30 pages and 40 keywords from three sites, labelled blind by a separate
model instance that never saw Jev's answers. This is agreement with a
second judge, not accuracy: there is no human-labelled answer key yet.

| Judgment | Agreement |
|---|---|
| Helpfulness, same side of the 0.45 finding threshold | 29/30 |
| Specificity, same side of the threshold | 28/30 |
| Keyword kept or dropped (relevance 0.66) | 35/40 |
| Other-brand search | 31/40 |
| Page type | 20/30 (all 10 differences: skill or command pages, Jev "support or docs", judge "product or service") |
| Remove verdicts | Jev 1, judge 2, overlap 1 |

## Conclusions

- Rule, crawl and PageSpeed layers: reliable on everything checked.
- Jev: very repeatable; agrees with an independent judge on the decisions
  that create findings. Weakest on the other-brand check and on the
  docs-versus-product page type boundary. The page action question twice
  suggested removing substantial posts; removal is now blocked by code
  for pages of 600 words or more.
- Not yet established: accuracy against human labels, and threshold
  tuning. Label about 100 items per judgment family before treating Jev
  findings as more than prioritised signals for review.

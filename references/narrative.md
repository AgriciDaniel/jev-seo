# narrative.json contract

The lead agent writes this file into the audit output folder after reading
`digest.md`. The renderer places it in the executive summary of the PDF and
Markdown. If the file is absent, an automatic evidence-only summary is used
and labelled as automatic.

```json
{
  "executive_summary": [
    "Paragraph one: the overall verdict in plain language, with the score and what drives it.",
    "Paragraph two: the one or two issues that matter most for this business, citing action IDs such as JEV-001."
  ],
  "strengths": ["Three to five things the site does well, each tied to evidence."],
  "risks": ["Three to five things holding the site back, each citing an action ID."],
  "plan": [
    {"horizon": "This week", "items": ["JEV-001 Load the Bitter Lesson link over HTTPS (hours)"]},
    {"horizon": "This month", "items": ["..."]},
    {"horizon": "This quarter", "items": ["..."]}
  ],
  "closing": "Optional one or two sentences: what to measure after the fixes, or what the audit could not see.",
  "author": "Claude, from the audit evidence"
}
```

Required keys: `executive_summary`, `strengths`, `risks`, `plan`. Every
`JEV-###` you cite must exist in the audit; the renderer refuses the file
otherwise.

## Writing rules

- Write for the site owner, not an SEO specialist. Name the business
  consequence ("visitors land on a page that does not say what you sell"),
  then the fix.
- Every claim comes from the digest or a fact you checked yourself. No new
  metrics, no traffic or revenue estimates, no ranking predictions.
- Separate what rules measured from what Jev judged. Say "Jev judged" for
  semantic findings and mention when an action is flagged to verify.
- Name false positives you found during review, briefly.
- Plan items start with the action ID and include the effort band.
- Keep it short: two or three summary paragraphs, three to five bullets per
  list, three to five items per plan horizon.
- Plain words. No em dashes. No hype.
- No spin: do not write "owns", "dominates", "one push away" or "healthy"
  without a stated comparison; say the position or number instead. Do not
  state causes ("this caps", "because of") the audit did not measure.
- Absolute words ("every", "all", "none") only when the digest shows the
  whole set was checked; say "every crawled page" when it was a sample.
- AI search items (answer-first, citability, entity clarity, llms.txt) are
  editorial heuristics: Google says no special optimization is needed for
  its AI features. Never present them as ranking factors or strengths.
- Plan effort bands must match the action table; the renderer warns on a
  mismatch.

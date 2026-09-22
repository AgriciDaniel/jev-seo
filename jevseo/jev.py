"""Jev judgments: narrow semantic questions over crawled evidence.

POST https://api.typesafe.ai/v1/systemone with state, model and questions
(docs.typesafe.ai/primitives). Independent questions over one state share a
request. Code never asks Jev something it can see itself: a page without a
meta description gets no meta-quality question. Answers are typed and keep
their probabilities; code turns them into findings only in the decisive band.
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from jevseo.env import secret

API = "https://api.typesafe.ai/v1/systemone"
MODELS_API = "https://api.typesafe.ai/v1/models"
MODEL = "jev-latest"
USD_PER_MTOK = 0.042  # docs.typesafe.ai/models, retrieved 2026-09-20; re-check with the Jev brain staleness rule
PAGE_TEXT_CHARS = 6000
ACT = 0.80  # Choice and Score confidence at or above this is decisive
YES, NO = 0.80, 0.20  # Noul decisive bands (Noul has no confidence field)


def choice(instructions: str, options: dict) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": options}


def noul(instructions: str, true: str, false: str) -> dict:
    return {"type": "noul", "instructions": instructions, "criteria": {"true": true, "false": false}}


def score(instructions: str, levels: list[str]) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": levels}


# ---------------------------------------------------------------- per page
PAGE_TYPES = {
    "homepage": "The site's front page introducing the whole organisation",
    # Structured descriptions won an A/B test on blind labels (page type agreement 20/30 to 27/30).
    "product_or_service": {
        "what": "Presents one product, service, feature, tool or module the organisation offers, explaining what it does and why to use it",
        "examples": "a feature page, a service page, a tool or skill overview page, a plugin page",
    },
    "category_or_listing": "Lists or links many products, posts or items, with little content of its own",
    "article_or_guide": "An editorial article, guide, tutorial, news item or opinion piece",
    "about_or_team": "About the organisation, its story, mission or people",
    "contact_or_location": "Contact details, a form, opening hours or a physical location",
    "pricing": "Plans, prices or a quote request for the offer",
    "case_study_or_proof": "Customer stories, testimonials, results or portfolio work",
    "support_or_docs": {
        "what": "Helps people who already use the product get something done: troubleshooting, account help, API or configuration reference, FAQ",
        "not_for": "pages that introduce or sell a feature or tool, even when they include usage steps",
    },
    "legal_or_policy": "Terms, privacy, cookies, imprint or other policy text",
    "other": "None of the above fits",
}
INTENTS = {
    "informational": "Someone wanting to learn or understand something would land here",
    "commercial": "Someone comparing options before choosing a provider or product would land here",
    "transactional": "Someone ready to buy, book, sign up or request a quote would land here",
    "navigational": "Someone looking for this specific organisation, account or page would land here",
    "local": "Someone looking for a place or provider in a specific area would land here",
    "unclear": "The page serves no clear search need or mixes several evenly",
}
# Three options instead of five: "keep" and "improve" were a matter of degree, so Jev split between
# them (decisive 1/30). This set was decisive 27/30 in the A/B test.
ACTIONS = {
    "keep_or_improve": "The page serves a real purpose; at most it needs additions, polish or updates",
    "rewrite": "The page's purpose is valid but the current text fails it and needs a new draft",
    "merge_or_remove": "The page duplicates another page or has no reason to exist for searchers",
}


def page_questions(p: dict) -> dict:
    q = {
        "page_type": choice("Which kind of page is `page`?", PAGE_TYPES),
        "intent": choice("Which search need does `page` best serve?", INTENTS),
        "importance": score(
            "How important is `page` to the business described in `site`?",
            [
                "Utility or legal page with no role in winning customers",
                "Supporting page that helps a little, such as an old post or a minor listing",
                "Useful page that informs or reassures prospective customers",
                "Core page that presents a main offer, earns leads or drives sales",
            ],
        ),
        "action": choice("Given its content, what should the site owner do with `page`?", ACTIONS),
        "helpfulness": score(
            "How well does the main text of `page` satisfy a visitor who came for its topic?",
            [
                "Almost no usable content: placeholder, boilerplate or a few generic lines",
                "Covers the topic superficially; a visitor would need to look elsewhere",
                "Answers the main question adequately with some useful detail",
                "Answers thoroughly, anticipates follow-up questions and leaves little to look up elsewhere",
            ],
        ),
        "specificity": score(
            "How specific and original is the content of `page`?",
            [
                "Generic statements that could appear on any competitor's site",
                "Mostly generic, with a few concrete details",
                "Concrete details such as named features, numbers, places or examples throughout",
                "Distinctive first-hand detail: own data, results, processes or experience no one else could copy",
            ],
        ),
        # Won A/B on blind labels: decisive 6/30 to 23/30, agreement 15/30 to 28/30 (23/23 when decisive).
        "answer_first": noul(
            "Does `page.opening`, the text right after the main heading, state plainly what the page offers or answers within its first two sentences?",
            "The first two sentences say concretely what the reader gets: the answer, the offer, or what the page covers",
            "The opening is a slogan, a tease, a date or author line, a story, or general preamble before the point",
        ),
        "citable": score(
            "How easily could an AI answer engine quote self-contained facts from `page`?",
            [
                "No quotable facts: mostly slogans, navigation or vague claims",
                "A few facts, but they depend on surrounding context to make sense",
                "Several clear, self-contained statements of fact, definitions or figures",
                "Many precise, self-contained statements with names, numbers and definitions ready to cite",
            ],
        ),
        "trust": score(
            "How much evidence of real expertise and trustworthiness does `page` show?",
            [
                "None: anonymous, unsupported claims",
                "Some signals, such as a company name, but no proof",
                "Clear signals such as named people, credentials, reviews, sources or contact details",
                "Strong proof: named experts, cited sources or data, verifiable results and clear accountability",
            ],
        ),
        # Won A/B on blind labels: decisive 9/30 to 16/30, agreement 25/30 to 26/30 (16/16 when decisive).
        "clear_next_step": noul(
            "Does `page.text` give a visitor an obvious next step that fits this page?",
            "The text invites a concrete action on this topic: install, sign up, contact, buy, download, try it, or read the natural next guide",
            "The text ends without inviting any action, or only generic navigation remains",
        ),
    }
    if p.get("title"):
        q["title_fit"] = score(
            "How accurately and attractively does `page.title` describe what `page` actually contains?",
            [
                "It is misleading, empty of meaning or unrelated to the content",
                "It names the site or a vague topic but not what this page offers",
                "It describes the page's topic accurately",
                "It describes the topic in a searcher's own words and gives a concrete reason to click",
            ],
        )
    if p.get("meta_description"):
        q["meta_fit"] = score(
            "How well does `page.meta_description` summarise `page` for someone scanning search results?",
            [
                "Unrelated, boilerplate or keyword stuffing",
                "Related but vague about what the page delivers",
                "An accurate summary of what the page delivers",
                "An accurate, specific summary that gives a clear reason to visit",
            ],
        )
    if p.get("h1"):
        q["h1_fit"] = noul(
            "Does `page.h1` state the main topic of `page`?",
            "The main heading names what the page is about",
            "The main heading is a slogan, a generic word, or about something else",
        )
    return q


def opening(p: dict) -> str:
    """The first words after the main heading, so breadcrumbs and navigation are not read as the opening."""
    text = p.get("text_excerpt") or ""
    h1 = (p.get("h1") or [""])[0]
    i = text.find(h1) if h1 else -1
    return (text[i + len(h1):] if i >= 0 else text).strip()[:500]


def page_state(p: dict, site_ctx: dict) -> dict:
    text = p.get("text_excerpt") or ""
    return {
        "site": site_ctx,
        "page": {
            "url": p["url"],
            "title": p.get("title"),
            "meta_description": p.get("meta_description"),
            "h1": (p.get("h1") or [None])[0],
            "outline": p.get("outline", [])[:25],
            "word_count": p.get("word_count"),
            "opening": opening(p),
            "calls_to_action": p.get("calls_to_action", []),
            "text": text[:PAGE_TEXT_CHARS],
            "text_truncated": len(text) > PAGE_TEXT_CHARS,
        },
    }


# ---------------------------------------------------------------- site level
BUSINESS_MODELS = {
    "local_service": "Serves customers in a specific town or region, such as a trade, clinic or restaurant",
    "ecommerce": "Sells physical or digital products through an online store",
    "saas_or_software": "Sells software, an app or an API",
    "agency_or_b2b_services": "Sells professional services to businesses",
    "publisher_or_media": "Earns from content, news, reviews or advertising",
    "education_or_course": "Sells or offers courses, training or a community",
    "nonprofit_or_public": "Charity, public body or community organisation",
    "personal_or_portfolio": "A person's portfolio, CV or personal brand",
    "other": "None of the above fits",
}


def site_questions() -> dict:
    return {
        "business_model": choice("Which kind of organisation runs the website in `homepage`?", BUSINESS_MODELS),
        "value_prop": score(
            "How clearly does `homepage` tell a first-time visitor what is offered, to whom, and why choose it?",
            [
                "A visitor cannot tell what is offered",
                "The offer is guessable but vague or buried",
                "The offer and audience are clear; the reason to choose it is weak",
                "Offer, audience and a specific reason to choose it are clear within the first screen",
            ],
        ),
        "entity_clarity": noul(
            "Does `homepage` state plainly who the organisation is, what it does and where or for whom it operates?",
            "Name, activity and market or location are all stated plainly",
            "At least one of name, activity, or market or location is missing or unclear",
        ),
        "topical_focus": score(
            "Looking at `page_titles`, how focused is the site on a coherent set of topics?",
            [
                "Scattered topics with no visible connection",
                "A loose theme with many unrelated pages",
                "A clear theme with a few off-topic pages",
                "Tightly organised around a clear set of related topics",
            ],
        ),
        "serves_local_area": noul(
            "Does `homepage` show that the organisation serves customers in a specific physical area?",
            "It names a service area, address or local customers",
            "It serves customers regardless of location or does not say",
        ),
    }


def site_state(home: dict, pages: list[dict]) -> dict:
    return {
        "homepage": {
            "url": home["url"],
            "title": home.get("title"),
            "meta_description": home.get("meta_description"),
            "h1": (home.get("h1") or [None])[0],
            "navigation": home.get("nav_labels", [])[:30],
            "text": (home.get("text_excerpt") or "")[:PAGE_TEXT_CHARS],
        },
        "page_titles": [p.get("title") or p["url"] for p in pages[:80]],
    }


# ---------------------------------------------------------------- page pairs
def overlap_candidates(pages: list[dict], limit: int = 40) -> list[tuple[dict, dict, float]]:
    """Deterministic shortlist: pages whose title and H1 words overlap. Code picks, Jev judges."""
    stop = set("the a an and or of for to in on with your our you we is are at by from how what why this that best".split())

    def words(p):
        text = f"{p.get('title') or ''} {' '.join(p.get('h1') or [])}".lower()
        text = re.sub(r"[|\-\u2013\u2014:\u00b7].*$", "", text) if len(text.split()) > 6 else text
        return {w for w in re.findall(r"[a-z0-9]{3,}", text) if w not in stop}

    ws = {p["url"]: words(p) for p in pages}
    pairs = []
    for i, a in enumerate(pages):
        for b in pages[i + 1 :]:
            A, B = ws[a["url"]], ws[b["url"]]
            if len(A) < 2 or len(B) < 2 or a.get("text_hash") == b.get("text_hash"):
                continue
            j = len(A & B) / len(A | B)
            if j >= 0.4:
                pairs.append((a, b, round(j, 2)))
    pairs.sort(key=lambda t: -t[2])
    return pairs[:limit]


def pair_question(key: str) -> dict:
    return noul(
        f"Would the two pages in `{key}` compete for the same searches, so that one searcher would be equally well served by either?",
        "They target the same need; a searcher would treat them as substitutes",
        "They serve different needs, audiences or stages, even if their topics are related",
    )


def pair_summary(p: dict) -> dict:
    return {"url": p["url"], "title": p.get("title"), "h1": (p.get("h1") or [None])[0], "text": (p.get("text_excerpt") or "")[:1200]}


# ---------------------------------------------------------------- keywords (full mode)
RELEVANCE = [
    "Unrelated to what the site offers; traffic from it would not become customers",
    "Loosely related: same broad field, but a different need or audience",
    "Related: the searcher could plausibly want what the site offers",
    "Core: the searcher is looking for exactly what the site offers",
]


def keyword_batches(keywords: list[dict], pages: list[dict], site_ctx: dict, size: int = 8):
    """Yield (state, questions, keys) with every candidate page named once in state."""
    catalogue = {f"p{i}": {"url": p["url"], "title": p.get("title"), "h1": (p.get("h1") or [None])[0]} for i, p in enumerate(pages[:30])}
    options = {pid: f"{v['title'] or v['url']} ({v['url']})" for pid, v in catalogue.items()}
    options["none_fit"] = "No existing page serves this search; a new page would be needed"
    for start in range(0, len(keywords), size):
        chunk = keywords[start : start + size]
        state = {"site": site_ctx, "pages": catalogue, "keywords": {}}
        questions, keys = {}, []
        for i, k in enumerate(chunk):
            kid = f"k{i}"
            state["keywords"][kid] = {"keyword": k["keyword"], "monthly_searches": k.get("volume"), "intent": k.get("intent"), "currently_ranking_url": k.get("url")}
            questions[f"{kid}_rel"] = score(f"How relevant is the search in `keywords.{kid}` to what `site` offers?", RELEVANCE)
            questions[f"{kid}_page"] = choice(f"Which page in `pages` best serves the search in `keywords.{kid}`?", options)
            questions[f"{kid}_other_brand"] = noul(
                f"Does `keywords.{kid}` name a specific company, product or website that is not the one in `site`, so the searcher wants that named thing?",
                "The search contains another organisation's or product's name and the searcher is after that name (for example a competitor's brand or a platform's own product)",
                "The search is a generic need or category, or names this site itself; any matching provider could serve it",
            )
            keys.append((kid, k["keyword"]))
        yield state, questions, keys, catalogue


# ---------------------------------------------------------------- client
class Jev:
    def __init__(self, budget_usd: float = 0.25, log=print):
        self.key = secret("TYPESAFE_API_KEY")
        self.budget = budget_usd
        self.log = log
        self.lock = threading.Lock()
        self.ledger = {"model_requested": MODEL, "model_returned": None, "requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "est_reserved_tokens": 0, "skipped_budget": 0, "errors": []}

    @property
    def available(self) -> bool:
        return bool(self.key)

    def cost(self) -> float:
        return round(self.ledger["input_tokens"] / 1e6 * USD_PER_MTOK, 6)

    def ask(self, state: dict, questions: dict) -> dict | None:
        body = json.dumps({"state": state, "model": MODEL, "questions": questions})
        est = len(body) // 3  # conservative token estimate for the budget reservation
        with self.lock:
            spent = (self.ledger["input_tokens"] + self.ledger["est_reserved_tokens"]) / 1e6 * USD_PER_MTOK
            if spent + est / 1e6 * USD_PER_MTOK > self.budget:
                self.ledger["skipped_budget"] += 1
                return None
            self.ledger["est_reserved_tokens"] += est
        try:
            for attempt in range(5):
                try:
                    r = requests.post(API, data=body, headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}, timeout=90)
                except requests.RequestException as err:
                    if attempt < 4:
                        time.sleep(2**attempt)
                        continue
                    raise RuntimeError(type(err).__name__) from None
                if r.status_code in (429, 529, 502, 503) and attempt < 4:
                    time.sleep(retry_after(r.headers.get("retry-after"), attempt))
                    continue
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                data = r.json()
                usage = data.get("usage") or {}
                with self.lock:
                    self.ledger["requests"] += 1
                    if isinstance(usage.get("input_tokens"), int):
                        self.ledger["input_tokens"] += usage["input_tokens"]
                    else:
                        # Keep the budget cap honest when usage is missing: count the estimate.
                        self.ledger["input_tokens"] += est
                        self.ledger["usage_estimated"] = self.ledger.get("usage_estimated", 0) + 1
                    self.ledger["output_tokens"] += usage.get("output_tokens") or 0
                    self.ledger["model_returned"] = data.get("model")
                answers = data.get("answers") or {}
                missing = set(questions) - set(answers)
                if missing:
                    raise RuntimeError(f"answers missing for {sorted(missing)}")
                return {k: validate(questions[k], answers[k]) for k in questions}
        except Exception as err:  # noqa: BLE001  any malformed response is a recorded failure, never a crash
            with self.lock:
                self.ledger["failed"] += 1
                self.ledger["errors"].append(f"{type(err).__name__}: {str(err)[:180]}")
            return None
        finally:
            with self.lock:
                self.ledger["est_reserved_tokens"] -= est


def retry_after(header: str | None, attempt: int) -> float:
    try:
        return min(float(header), 30.0)
    except (TypeError, ValueError):
        return float(2**attempt)


def validate(question: dict, answer: dict) -> dict:
    """Keep the raw typed answer, add a normalised value and a decision band."""
    t = question["type"]
    if t == "noul":
        v = float(answer["noul"])
        if not 0 <= v <= 1:
            raise RuntimeError("noul out of range")
        band = "yes" if v >= YES else "no" if v <= NO else "review"
        return {"type": t, "value": v, "band": band}
    conf = float(answer.get("confidence", 0))
    if t == "choice":
        if answer["choice"] not in question["criteria"]:
            raise RuntimeError("choice outside options")
        return {"type": t, "value": answer["choice"], "probabilities": answer.get("probabilities", {}), "confidence": conf, "band": "act" if conf >= ACT else "review"}
    top = len(question["criteria"]) - 1
    s = float(answer["score"])
    if not 0 <= s <= top:
        raise RuntimeError("score out of range")
    probs = answer.get("probabilities", {}) or {}
    # Decisive means the probability sits on one side of the midpoint, the side every finding
    # threshold uses; spread between two neighbouring levels on the same side is not doubt.
    # On blind labels, side-decisive answers agreed 90 to 97% of the time, the rest about 50%.
    upper = sum(float(v) for k, v in probs.items() if int(k) / top >= 0.5)
    side = max(upper, 1 - upper) if probs else conf
    return {"type": t, "value": round(s / top, 4), "raw": s, "levels": top + 1, "probabilities": probs, "confidence": conf,
            "side_probability": round(side, 4), "band": "act" if side >= ACT else "review"}


def judge(crawl: dict, pages: list[dict], budget_usd: float, log=print, dfs: dict | None = None) -> dict:
    jev = Jev(budget_usd, log)
    out = {"available": jev.available, "site": None, "pages": {}, "pairs": [], "ledger": jev.ledger, "questions": {}}
    if not jev.available:
        log("TYPESAFE_API_KEY not found: Jev judgments skipped; semantic sections will be marked not assessed.")
        return out
    home = next((p for p in pages if p["url"] == crawl["final_url"]), pages[0] if pages else None)
    if home is None:
        return out
    site_q = site_questions()
    out["site"] = jev.ask(site_state(home, pages), site_q)
    site_ctx = {
        "name": home.get("title"),
        "homepage_summary": (home.get("meta_description") or "") + " " + (home.get("text_excerpt") or "")[:600],
    }
    out["questions"] = {"site": site_q, "page_example": page_questions(home)}

    def one(p):
        qs = page_questions(p)
        is_home = p["url"] == home["url"]
        if is_home:
            qs.pop("page_type")  # code knows which page is the homepage; Jev is never asked what code can see
        ans = jev.ask(page_state(p, site_ctx), qs)
        if ans is not None and is_home:
            ans["page_type"] = {"type": "choice", "value": "homepage", "probabilities": {"homepage": 1.0}, "confidence": 1.0, "band": "act", "source": "code"}
        return p["url"], ans

    step = max(1, -(-len(pages) // 5))  # about five progress lines per run
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (url, ans) in enumerate(pool.map(one, pages), 1):
            out["pages"][url] = ans
            if i % step == 0 or i == len(pages):
                log(f"Jev: {i}/{len(pages)} pages judged, ${jev.cost():.4f} so far")
    out["not_judged"] = [u for u, a in out["pages"].items() if a is None]

    pairs = overlap_candidates(pages)
    if pairs:
        log(f"Jev: checking {len(pairs)} page pairs for competing content")
    for start in range(0, len(pairs), 10):
        chunk = pairs[start : start + 10]
        state = {f"pair_{i}": {"page_a": pair_summary(a), "page_b": pair_summary(b)} for i, (a, b, _) in enumerate(chunk)}
        ans = jev.ask(state, {f"pair_{i}": pair_question(f"pair_{i}") for i in range(len(chunk))})
        for i, (a, b, jac) in enumerate(chunk):
            out["pairs"].append({"a": a["url"], "b": b["url"], "title_overlap": jac, "judgment": ans[f"pair_{i}"] if ans else None})
    if dfs and dfs.get("available"):
        # A balanced mix, not the biggest volumes: niche suggestions are where small sites win,
        # and high-volume gap terms borrowed from large competitors are mostly unrelated.
        by_vol = lambda rows: sorted(rows, key=lambda k: -(k.get("volume") or 0))  # noqa: E731
        opps = dfs.get("opportunities") or []
        picks = (by_vol(dfs.get("ranked") or [])[:30]
                 + by_vol([k for k in opps if k.get("source") == "suggestion"])[:40]
                 + by_vol([k for k in opps if k.get("source") == "idea"])[:15]
                 + by_vol([k for k in opps if str(k.get("source", "")).startswith("gap")])[:15])
        kws = list({k["keyword"]: k for k in picks if k.get("keyword")}.values())
        log(f"Jev: judging relevance and best page for {len(kws)} keywords")
        batches = list(keyword_batches(kws, pages, site_ctx))
        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for (state, questions, keys, catalogue), ans in zip(batches, pool.map(lambda b: jev.ask(b[0], b[1]), batches)):
                for kid, kw in keys:
                    if not ans:
                        results[kw] = None
                        continue
                    page = ans[f"{kid}_page"]
                    results[kw] = {"relevance": ans[f"{kid}_rel"], "page": page, "page_url": catalogue.get(page["value"], {}).get("url"), "other_brand": ans[f"{kid}_other_brand"]}
        out["keywords"] = results
    jev.ledger["cost_usd"] = jev.cost()
    jev.ledger["usd_per_mtok"] = USD_PER_MTOK
    log(f"Jev: {jev.ledger['requests']} requests, {jev.ledger['input_tokens']} input tokens, ${jev.cost():.4f}, {jev.ledger['failed']} failed")
    return out

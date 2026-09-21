"""Excel workbook. The Actions sheet is the single editable status authority; Summary counts from it by formula."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.drawing.image import Image as XLImage
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from jevseo.report import JEV_COLUMNS

INK = "0B0B0B"
JEV = "D45BB6"
SOFT = "FBEAF5"
PANEL = "F4F3EF"
LINE = "E1E0D9"
INPUT = "FFF7D6"
SEV_FILL = {"critical": "F8DCDC", "high": "FBE3D8", "medium": "FDF0D0", "low": "E3ECF6"}
STATUSES = ["to_do", "in_progress", "done", "deferred", "not_applicable"]
HEAD = Font(name="Inter", bold=True, color="FFFFFF", size=10)
BODY = Font(name="Inter", size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Border(bottom=Side(style="thin", color=LINE))


def table(ws, headers: list[str], rows: list[list], widths: list[int], start_row: int = 1) -> None:
    for j, h in enumerate(headers, 1):
        c = ws.cell(start_row, j, h)
        c.font = HEAD
        c.fill = PatternFill("solid", fgColor=INK)
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(rows, start_row + 1):
        for j, v in enumerate(row, 1):
            c = ws.cell(i, j, v)
            c.font = BODY
            c.alignment = WRAP
            c.border = THIN
    for j, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(start_row + 1, 2)
    if rows:
        ws.auto_filter.ref = f"A{start_row}:{get_column_letter(len(headers))}{start_row + len(rows)}"
    ws.row_dimensions[start_row].height = 30


def link(cell, url: str) -> None:
    if url and url.startswith("http"):
        cell.hyperlink = url
        cell.font = Font(name="Inter", size=10, color="A83A8C", underline="single")


def write_xlsx(vm: dict, path: Path) -> Path:
    d = vm["d"]
    s = vm["scores"]
    wb = Workbook()

    # ---------------- Summary
    ws = wb.active
    ws.title = "Summary"
    ws.sheet_view.showGridLines = False
    ws["A1"] = f"Jev SEO audit: {vm['domain']}"
    ws["A1"].font = Font(name="Inter Display", bold=True, size=20)
    ws["A2"] = f"Audited {d['run']['finished_at']} · {vm['n_fetched']} URLs crawled · {vm['n_pages']} HTML pages · Jev {vm['ledger'].get('model_returned') or 'not used'}"
    ws["A2"].font = Font(name="Inter", size=10, color="52514E")
    ws["A4"], ws["B4"] = "Overall score", s["overall"]
    ws["A5"], ws["B5"] = "Grade", s["grade"]
    ws["A6"], ws["B6"] = "Jev cost (USD)", vm["ledger"].get("cost_usd") or 0
    ws["B6"].number_format = "$0.0000"
    for r in (4, 5, 6):
        ws[f"A{r}"].font = Font(name="Inter", bold=True)
        ws[f"B{r}"].font = Font(name="Inter Display", bold=True, size=14, color="A83A8C")
    ws["A8"] = "Area"
    ws["B8"] = "Score"
    ws["C8"] = "Weight"
    ws["D8"] = "How it is scored"
    for c in "ABCD":
        ws[f"{c}8"].font = HEAD
        ws[f"{c}8"].fill = PatternFill("solid", fgColor=INK)
    r = 9
    for cat, name in s["category_names"].items():
        ws.cell(r, 1, name).font = BODY
        ws.cell(r, 2, s["categories"][cat]).font = BODY
        ws.cell(r, 3, s["weights"][cat]).font = BODY
        ws.cell(r, 4, s["notes"][cat]).font = BODY
        r += 1
    ws.conditional_formatting.add(f"B9:B{r - 1}", ColorScaleRule(start_type="num", start_value=0, start_color="FBEAF5", end_type="num", end_value=100, end_color="A83A8C"))
    chart = BarChart()
    chart.type = "bar"
    chart.title = "Score by area"
    chart.style = 10
    chart.y_axis.scaling.min = 0
    chart.y_axis.scaling.max = 100
    chart.add_data(Reference(ws, min_col=2, min_row=8, max_row=r - 1), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=9, max_row=r - 1))
    chart.series[0].graphicalProperties.solidFill = JEV
    chart.legend = None
    chart.height, chart.width = 7.5, 14
    ws.add_chart(chart, "F3")

    r += 1
    ws.cell(r, 1, "Live status counts (from the Actions sheet)").font = Font(name="Inter", bold=True, size=12)
    r += 1
    status_start = r
    for st in STATUSES:
        ws.cell(r, 1, st).font = BODY
        ws.cell(r, 2, f'=COUNTIF(Actions!$E:$E,"{st}")').font = BODY
        r += 1
    r += 1
    ws.cell(r, 1, "Open actions by priority").font = Font(name="Inter", bold=True, size=12)
    r += 1

    for p in ("P1", "P2", "P3"):
        ws.cell(r, 1, p).font = BODY
        ws.cell(r, 2, f'=COUNTIFS(Actions!$C:$C,"{p}",Actions!$E:$E,"<>done",Actions!$E:$E,"<>not_applicable")').font = BODY
        r += 1
    ws.cell(r, 1, "Total actions").font = Font(name="Inter", bold=True)
    ws.cell(r, 2, f"=COUNTA(Actions!$A:$A)-1").font = Font(name="Inter", bold=True)
    donut = DoughnutChart()
    donut.title = "Action status"
    donut.add_data(Reference(ws, min_col=2, min_row=status_start, max_row=status_start + len(STATUSES) - 1))
    donut.set_categories(Reference(ws, min_col=1, min_row=status_start, max_row=status_start + len(STATUSES) - 1))
    donut.height, donut.width = 7, 9
    ws.add_chart(donut, "F19")
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 9
    ws.column_dimensions["D"].width = 52
    if "gauge" in vm["charts"].png:
        img = XLImage(str(vm["charts"].png["gauge"]))
        img.width, img.height = 150, 150
        ws.add_image(img, "N3")

    # ---------------- Actions (editable authority)
    wa = wb.create_sheet("Actions")
    headers = ["ID", "Action", "Priority", "Severity", "Status", "Owner", "Due", "Notes", "Impact", "Effort", "Quick win", "Area", "Judged by", "Pages", "Evidence", "Fix", "Needs human check", "Heuristic", "Source", "Affected URLs"]
    rows = []
    for a in vm["actions"]:
        rows.append([
            a["action_id"], a["title"], a["priority"], a["severity"], a["status"], None, None, None, a["impact"], a["effort_text"],
            "yes" if a["quick_win"] else "", s["category_names"][a["category"]], a["by"], a["count"],
            a["evidence"], a["fix"], a["needs_review"] or "", "yes" if a["heuristic"] else "", a["source"], "\n".join(a["urls"][:25]) + (f"\n+{a['count'] - 25} more" if a["count"] > 25 else ""),
        ])
    table(wa, headers, rows, [10, 38, 9, 10, 13, 16, 12, 28, 8, 12, 9, 20, 9, 7, 46, 52, 10, 9, 36, 60])
    n = len(rows) + 1
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=False)
    wa.add_data_validation(dv)
    dv.add(f"E2:E{max(n, 2)}")
    dvp = DataValidation(type="list", formula1='"P1,P2,P3"')
    wa.add_data_validation(dvp)
    dvp.add(f"C2:C{max(n, 2)}")
    for i in range(2, n + 1):
        for col in "EFGH":
            wa[f"{col}{i}"].fill = PatternFill("solid", fgColor=INPUT)
        sev = wa[f"D{i}"].value
        if sev in SEV_FILL:
            wa[f"D{i}"].fill = PatternFill("solid", fgColor=SEV_FILL[sev])
        wa[f"G{i}"].number_format = "yyyy-mm-dd"
        link(wa[f"S{i}"], wa[f"S{i}"].value)
    wa.conditional_formatting.add(f"E2:E{n}", CellIsRule(operator="equal", formula=['"done"'], fill=PatternFill("solid", fgColor="DFF3DF")))
    wa.conditional_formatting.add(f"I2:I{n}", ColorScaleRule(start_type="num", start_value=0, start_color="FFFFFF", end_type="num", end_value=100, end_color="E691CF"))

    # ---------------- Pages
    wp = wb.create_sheet("Pages")
    cols = [("URL", "url", 50), ("Status", "status", 8), ("Depth", "depth", 7), ("Title", "title", 40), ("Title chars", "title_len", 8), ("Meta chars", "meta_len", 8), ("H1", "h1", 34), ("H1 count", "h1_count", 7), ("Words", "words", 8), ("Inlinks", "inlinks", 8), ("Outlinks", "outlinks", 8), ("Images", "images", 8), ("No alt", "missing_alt", 7), ("Indexable", "indexable", 9), ("In sitemap", "in_sitemap", 9), ("Canonical", "canonical", 40), ("Schema", "schema", 26), ("TTFB ms", "ttfb", 8), ("HTML KB", "kb", 8), ("Rendered", "rendered", 9), ("Type (Jev)", "page_type", 18), ("Intent (Jev)", "intent", 14), ("Importance (Jev)", "importance", 10), ("Action (Jev)", "action", 14)] + [(f"{label} (Jev)", key, 10) for key, label in JEV_COLUMNS]
    prow = []
    for p in vm["pages"]:
        row = []
        for _, key, _ in cols:
            v = p.get(key)
            if key == "depth" and v == 99:
                v = None
            if isinstance(v, bool):
                v = "yes" if v else "no"
            if key in ("page_type", "intent", "action") and isinstance(v, str):
                v = v.replace("_", " ")
            row.append(v)
        prow.append(row)
    table(wp, [c[0] for c in cols], prow, [c[2] for c in cols])
    for i in range(2, len(prow) + 2):
        link(wp[f"A{i}"], wp[f"A{i}"].value)
        for j in range(len(cols) - len(JEV_COLUMNS) - 1, len(cols) + 1):
            if isinstance(wp.cell(i, j).value, float):
                wp.cell(i, j).number_format = "0.00"
    first_jev = get_column_letter(len(cols) - len(JEV_COLUMNS) + 1)
    last = get_column_letter(len(cols))
    if prow:
        wp.conditional_formatting.add(f"{first_jev}2:{last}{len(prow) + 1}", ColorScaleRule(start_type="num", start_value=0, start_color="FBEAF5", end_type="num", end_value=1, end_color="A83A8C"))

    # ---------------- Jev judgments (raw, with probabilities)
    wj = wb.create_sheet("Jev judgments")
    jrows = []
    for url, ans in (d["jev"].get("pages") or {}).items():
        for key, a in (ans or {}).items():
            probs = a.get("probabilities") or {}
            top = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1])[:3]) if probs else ""
            jrows.append([url, key, a["type"], a["value"] if not isinstance(a["value"], float) else round(a["value"], 3), a.get("confidence"), a["band"], top])
    if d["jev"].get("site"):
        for key, a in d["jev"]["site"].items():
            probs = a.get("probabilities") or {}
            top = ", ".join(f"{k}: {v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1])[:3]) if probs else ""
            jrows.append(["(site)", key, a["type"], a["value"] if not isinstance(a["value"], float) else round(a["value"], 3), a.get("confidence"), a["band"], top])
    for p in d["jev"].get("pairs", []):
        if p.get("judgment"):
            jrows.append([f"{p['a']} vs {p['b']}", "compete", "noul", round(p["judgment"]["value"], 3), None, p["judgment"]["band"], f"title overlap {p['title_overlap']}"])
    table(wj, ["Page", "Question", "Primitive", "Answer (0 to 1 or option)", "Confidence", "Band", "Top probabilities"], jrows, [50, 18, 9, 18, 11, 10, 50])
    for i in range(2, len(jrows) + 2):
        wj[f"E{i}"].number_format = "0.00"
    wj.conditional_formatting.add(f"F2:F{len(jrows) + 1}", CellIsRule(operator="equal", formula=['"review"'], fill=PatternFill("solid", fgColor="FDF0D0")))

    # ---------------- Technical
    wt = wb.create_sheet("Technical")
    site = d["site"]
    facts = [
        ["Final homepage URL", site["final_url"]],
        ["HTTPS", "yes" if site["https"] else "no"],
        ["HTTP redirects to HTTPS", "yes" if site["probes"]["http_to_https"] else "no"],
        ["Alternate host", f"{site['probes']['host_variant']['host']} -> status {site['probes']['host_variant']['status']}, redirects to preferred: {site['probes']['host_variant']['redirects_to_canonical_host']}"],
        ["Nonexistent URL status", site["probes"]["not_found_status"]],
        ["robots.txt", "present" if site["robots"]["present"] else "missing"],
        ["Sitemaps declared", ", ".join(site["robots"]["sitemaps"]) or "none"],
        ["Sitemap URLs", site["sitemaps"]["total_urls"]],
        ["llms.txt", "present" if site["probes"]["llms_txt"] else "not found"],
        ["Render mode", site["render"]["mode"]],
        ["Requests made", site["requests"]],
        ["Page cap reached", "yes" if site["limits"]["hit_page_cap"] else "no"],
    ] + [[f"Search bot: {b}", "allowed" if ok else "blocked"] for b, ok in site["robots"]["search_bots"].items()] + [[f"AI bot: {b}", "allowed" if ok else "blocked"] for b, ok in site["robots"]["ai_bots"].items()]
    table(wt, ["Check", "Value"], facts, [34, 90])

    # ---------------- Performance
    wf = wb.create_sheet("Performance")
    prow = []
    for r in vm["perf_runs"]:
        f = r.get("field_url") or r.get("field_origin") or {}
        m = f.get("metrics", {})
        prow.append([r["url"], r["strategy"], *(r["scores"].get(c) for c in ("performance", "accessibility", "best-practices", "seo")),
                     *(m.get(k, {}).get("p75") for k in ("LCP", "INP", "CLS")), *(m.get(k, {}).get("rating") for k in ("LCP", "INP", "CLS")), "page" if r.get("field_url") else "origin" if r.get("field_origin") else "none"])
    table(wf, ["URL", "Device", "Performance", "Accessibility", "Best practices", "SEO", "LCP p75 ms", "INP p75 ms", "CLS p75", "LCP rating", "INP rating", "CLS rating", "Field data level"], prow, [44, 9, 12, 12, 12, 8, 11, 11, 9, 16, 16, 16, 12])
    if prow:
        bc = BarChart()
        bc.title = "Lighthouse scores"
        bc.add_data(Reference(wf, min_col=3, max_col=6, min_row=1, max_row=len(prow) + 1), titles_from_data=True)
        bc.set_categories(Reference(wf, min_col=2, min_row=2, max_row=len(prow) + 1))
        bc.height, bc.width = 7.5, 16
        wf.add_chart(bc, f"A{len(prow) + 4}")

    # ---------------- DataForSEO (full mode)
    x = d.get("dataforseo") if (d.get("dataforseo") or {}).get("available") else None
    if x:
        kj = d["jev"].get("keywords") or {}

        def jv(kw, key):
            a = kj.get(kw) or {}
            v = (a.get(key) or {}).get("value")
            return round(v, 2) if isinstance(v, float) else v

        wk = wb.create_sheet("Rankings")
        rows = [[k["keyword"], k.get("position"), k.get("volume"), k.get("difficulty"), k.get("intent"), k.get("cpc"), round(k["etv"], 1) if k.get("etv") is not None else None, k.get("url"), jv(k["keyword"], "relevance")] for k in x.get("ranked") or []]
        table(wk, ["Keyword", "Position", "Searches/mo", "Difficulty", "Intent", "CPC (USD)", "Est. visits (ETV)", "Ranking URL", "Jev relevance"], rows, [34, 9, 12, 10, 14, 10, 12, 50, 12])
        for i in range(2, len(rows) + 2):
            link(wk[f"H{i}"], wk[f"H{i}"].value)
        wo = wb.create_sheet("Opportunities")
        opp_ids = {f["id"]: f for f in d["findings"] if f["id"] in ("dfs_existing_page", "dfs_new_page")}
        judged_set = {k for k in kj}
        rows = []
        for k in x.get("opportunities") or []:
            a = kj.get(k["keyword"]) or {}
            verdict = "kept" if any(k["keyword"] == r["keyword"] for f in opp_ids.values() for r in f["detail"].get("keywords", [])) else ("dropped" if k["keyword"] in judged_set else "not judged")
            page = (a.get("page") or {}).get("value")
            rows.append([k["keyword"], k.get("volume"), k.get("difficulty"), k.get("intent"), k.get("source"), jv(k["keyword"], "relevance"), jv(k["keyword"], "other_brand"),
                         "new page" if page == "none_fit" else a.get("page_url"), verdict])
        rows.sort(key=lambda r: (r[8] != "kept", -(r[1] or 0)))
        table(wo, ["Keyword", "Searches/mo", "Difficulty", "Intent", "Source", "Jev relevance", "Jev P(other brand)", "Page to own it (Jev)", "Kept by Jev filter"], rows, [34, 12, 10, 14, 22, 12, 14, 46, 14])
        wo.conditional_formatting.add(f"I2:I{len(rows) + 1}", CellIsRule(operator="equal", formula=['"kept"'], fill=PatternFill("solid", fgColor="DFF3DF")))
        wcm = wb.create_sheet("Competitors")
        rd = {r["domain"]: r.get("referring_domains") for r in x.get("referring_domains") or []}
        rows = [[c["domain"], c.get("shared_keywords"), round(c["avg_position"], 1) if c.get("avg_position") is not None else None, c.get("keywords"), round(c["etv"]) if c.get("etv") is not None else None, rd.get(c["domain"])] for c in x.get("competitors_all") or []]
        rows.insert(0, [d["site"]["domain"] + " (this site)", None, None, (x.get("overview") or {}).get("count"), round((x.get("overview") or {}).get("etv") or 0), rd.get(d["site"]["domain"])])
        table(wcm, ["Domain", "Shared keywords", "Avg position", "Ranking keywords", "Est. visits (ETV)", "Referring domains"], rows, [34, 14, 12, 16, 16, 16])
        ws2 = wb.create_sheet("SERPs")
        rows = [[s2["keyword"], s2["own_position"], "yes" if s2["ai_overview"] else "no", "yes" if s2["ai_overview_cites_site"] else "no", ", ".join(s2["ai_overview_domains"]), ", ".join(s2["features"]), "\n".join(f"{t['position']}. {t['domain']}" for t in s2["top"])] for s2 in x.get("serps") or []]
        table(ws2, ["Keyword", "Site position", "AI Overview", "Cites site", "AI Overview sources", "SERP features", "Top 10"], rows, [30, 12, 11, 10, 46, 40, 34])
        m = x.get("mentions") or {}
        wm2 = wb.create_sheet("AI mentions")
        rows = [[i.get("platform"), i.get("model"), i.get("question"), i.get("ai_search_volume"), ", ".join(i.get("sources") or [])] for i in m.get("items") or []]
        table(wm2, ["Platform", "Model", "Question", "AI search volume", "Sources cited"], rows, [14, 20, 60, 14, 50])
        wm2.cell(len(rows) + 3, 1, f"Total mentions reported by DataForSEO LLM Mentions: {m.get('total')}. Showing a sample of {len(rows)}.").font = Font(name="Inter", italic=True, size=9)

    # ---------------- Charts (images from the report)
    wc = wb.create_sheet("Charts")
    wc.sheet_view.showGridLines = False
    row = 1
    for name in ("categories", "impact_effort", "positions", "referring_domains", "opportunities", "funnel", "site_map", "invest", "severity_by_category", "jev_heatmap", "page_types", "intents", "jev_confidence", "lighthouse"):
        if name in vm["charts"].png:
            img = XLImage(str(vm["charts"].png[name]))
            scale = 620 / img.width
            img.width, img.height = int(img.width * scale), int(img.height * scale)
            wc.add_image(img, f"A{row}")
            row += int(img.height / 20) + 2

    # ---------------- Method
    wm = wb.create_sheet("Method")
    notes = [
        ["Pipeline", "Crawl (code) -> rules (code) -> Jev typed judgments -> PageSpeed Insights -> scoring and ranking (code) -> narrative (lead agent)."],
        ["Area score", "100 minus, per finding, severity amount (critical 25, high 12, medium 6, low 2) x (0.5 + 0.5 x share of pages affected). Content and AI readiness blend 70% Jev judgment and 30% rules; performance blends 50% Lighthouse mobile and 50% crawl observations."],
        ["Overall", "Weighted mean of scored areas; unscored areas excluded, never zero. Blocked site capped at 20; no reliable HTTPS capped at 60."],
        ["Impact", "Severity weight (10/6/3/1) x (0.6 + 0.4 x reach) x (0.6 + 0.8 x max Jev importance of affected pages), scaled to 100."],
        ["Jev bands", "Choice and Score decisive at confidence >= 0.80; Noul decisive at P(yes) >= 0.80 or <= 0.20; everything else needs a human check."],
        ["Jev ledger", str(vm["ledger"])],
        ["DataForSEO", f"{vm['dfs']['ledger']['requests']} requests, ${vm['dfs']['ledger']['cost_usd']:.4f} as reported per call; volumes, difficulty and ETV are DataForSEO estimates" if vm.get("dfs") else "Not used (run with --full)"],
        ["Status authority", "The Actions sheet Status column is the only editable status. Summary counts update from it. PDF and Markdown are dated snapshots."],
        ["Limits", "No Search Console, analytics, backlink or keyword volume data. Scores are an internal rubric, not ranking or traffic predictions. Jev answers are model judgments, not measurements."],
    ]
    table(wm, ["Topic", "Detail"], notes, [20, 120])

    for sheet in wb.worksheets:
        sheet.sheet_properties.tabColor = JEV if sheet.title in ("Summary", "Actions", "Jev judgments") else "C3C2B7"
    wb.save(path)
    return path

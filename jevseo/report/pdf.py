"""HTML report rendered to PDF with WeasyPrint. Charts are inline SVG, so the PDF stays vector."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from jevseo import jev
from jevseo.checks import RULES

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def context(vm: dict) -> dict:
    d = vm["d"]
    return vm | {
        "css": (TEMPLATES / "report.css").read_text(),
        "date": datetime.fromisoformat(d["run"]["finished_at"]).strftime("%d %B %Y"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rule_count": len(RULES),
        "rule_findings": sum(1 for f in d["findings"] if f["origin"] == "rule"),
        "act": jev.ACT,
        "yes": jev.YES,
        "no": jev.NO,
        "sources": sorted({a["source"] for a in vm["actions"]} | {"https://docs.typesafe.ai/primitives", "https://docs.typesafe.ai/confidence", "https://developers.google.com/speed/docs/insights/v5/about"}),
    }


def render_html(vm: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    return env.get_template("report.html.j2").render(**context(vm))


def write_pdf(vm: dict, path: Path) -> Path:
    from weasyprint import HTML

    html = render_html(vm)
    path.with_suffix(".html").write_text(html)
    HTML(string=html, base_url=str(path.parent)).write_pdf(path)
    return path

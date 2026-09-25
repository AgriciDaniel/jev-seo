r"""Report translation applied at render time, so audit.json stays English and any old audit re-renders in any language.

    audit.json --view_model--> charts (matplotlib Text) --\
                           \-> HTML text nodes -----------+--> Translator(lang) --> PDF / XLSX / MD
                           \-> XLSX cells, MD cells -----/

A catalogue jevseo/i18n/<lang>.json holds exact strings ("text") and regex templates ("patterns").
Pattern groups named t_* are translated recursively. Unknown strings pass through unchanged.
Example: "Pages excluded from search with noindex" -> "Strony wykluczone z wyszukiwania przez noindex".
"""
from __future__ import annotations

import json
import re
from html import escape, unescape
from contextlib import contextmanager
from pathlib import Path

CATALOGUES = Path(__file__).resolve().parent / "i18n"
SOURCE_LANG = "en"
TRANSLATED_GROUP_PREFIX = "t_"
# Captured blocks sit at odd indices after split and are never translated.
PROTECTED_BLOCKS = re.compile(r"(<(?:svg|style|script|code)\b.*?</(?:svg|style|script|code)>)", re.S | re.I)
TEXT_NODE = re.compile(r">([^<>]*[A-Za-z][^<>]*)<")
FORMULA_LITERAL = re.compile(r'"(<>)?([^"]+)"')
CSS_CONTENT = re.compile(r"content:[^;{}]*")
CSS_STRING = re.compile(r'"([^"\n]*)"')
TEXT_ATTR = re.compile(r'\b(title|alt)="([^"]*)"')


class Translator:
    def __init__(self, lang: str = SOURCE_LANG):
        self.lang = lang
        self.text: dict[str, str] = {}
        self.translated: set[str] = set()
        self.patterns: list[tuple[re.Pattern, str]] = []
        self.misses: set[str] = set()

        if lang == SOURCE_LANG:
            return

        path = CATALOGUES / f"{lang}.json"
        if not path.is_file():
            raise SystemExit(f"No report translation for '{lang}': {path} is missing.")

        cat = json.loads(path.read_text())
        self.text = cat.get("text", {})
        self.patterns = [(re.compile(rx, re.S), rep) for rx, rep in cat.get("patterns", [])]
        self.translated = set(self.text.values())

    @property
    def active(self) -> bool:
        return self.lang != SOURCE_LANG

    def __call__(self, s):
        if not self.active or not isinstance(s, str) or not s.strip():
            return s

        # Keep surrounding whitespace: HTML text nodes carry the spacing between inline elements.
        lead = s[: len(s) - len(s.lstrip())]
        trail = s[len(s.rstrip()):]
        core = s.strip()
        return lead + self.core(core) + trail

    def core(self, s: str) -> str:
        if s in self.text:
            return self.text[s]

        for rx, rep in self.patterns:
            m = rx.fullmatch(s)
            if not m:
                continue
            groups = {k: (self(v) if k.startswith(TRANSLATED_GROUP_PREFIX) else v) or "" for k, v in m.groupdict().items()}
            return rep.format(**groups)

        # Matplotlib may set an already translated label again; that is not a miss.
        if s not in self.translated:
            self.misses.add(s)
        return s

    @contextmanager
    def charts(self):
        """Translate every matplotlib label while charts are drawn: titles, ticks, legends and annotations."""
        if not self.active:
            yield
            return

        from matplotlib.text import Text

        original = Text.set_text

        def set_text(text_obj, s):
            original(text_obj, self(s) if isinstance(s, str) else s)

        Text.set_text = set_text
        try:
            yield
        finally:
            Text.set_text = original

    def html(self, html: str) -> str:
        """Translate text between tags and title/alt attributes. SVG, style and script blocks pass through untouched."""
        if not self.active:
            return html

        parts = PROTECTED_BLOCKS.split(html)
        for i in range(1, len(parts), 2):
            # Page footers live in CSS: @bottom-left { content: string(domain) "  ·  Jev SEO audit"; }
            if parts[i].lower().startswith("<style"):
                parts[i] = CSS_CONTENT.sub(lambda m: CSS_STRING.sub(lambda q: '"' + self(q.group(1)) + '"', m.group(0)), parts[i])
        for i in range(0, len(parts), 2):
            parts[i] = TEXT_NODE.sub(lambda m: ">" + self.escaped(m.group(1)) + "<", parts[i])
            parts[i] = TEXT_ATTR.sub(lambda m: f'{m.group(1)}="{self.escaped(m.group(2))}"', parts[i])
        return "".join(parts).replace('<html lang="en"', f'<html lang="{self.lang}"', 1)

    def escaped(self, s: str) -> str:
        return escape(self(unescape(s)), quote=False)

    def workbook(self, wb) -> None:
        """Translate an in-memory openpyxl workbook before save (reloading a saved file would drop its charts).

        Sheet names, text cells, formula string literals, list validations, conditional formats and
        chart titles go through the same catalogue, so COUNTIF("to_do") keeps matching the Status column.
        """
        if not self.active:
            return

        renames = {ws.title: self(ws.title) for ws in wb.worksheets}
        for ws in wb.worksheets:
            ws.title = renames[ws.title]

        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str):
                        c.value = self.formula(c.value, renames) if c.value.startswith("=") else self(c.value)

            for dv in ws.data_validations.dataValidation:
                if dv.formula1 and dv.formula1.startswith('"'):
                    dv.formula1 = '"' + ",".join(self(x) for x in dv.formula1.strip('"').split(",")) + '"'

            for cf in ws.conditional_formatting:
                for rule in cf.rules:
                    rule.formula = [self.formula(f, renames) for f in rule.formula or []]

            for chart in ws._charts:
                self.chart_title(chart)

    def formula(self, f: str, renames: dict) -> str:
        for old, new in renames.items():
            if old != new:
                f = f.replace(f"{old}!", f"'{new}'!")
        return FORMULA_LITERAL.sub(lambda m: f'"{m.group(1) or ""}{self(m.group(2))}"', f)

    def chart_title(self, chart) -> None:
        rich = getattr(getattr(getattr(chart, "title", None), "tx", None), "rich", None)
        for p in getattr(rich, "p", None) or []:
            for r in p.r or []:
                r.t = self(r.t)

    def md(self, path: Path) -> None:
        """Translate Markdown line by line: headings, list items, table cells and plain lines."""
        if not self.active:
            return

        out = []
        fence = False
        for line in path.read_text().splitlines():
            if line.startswith("```"):
                fence = not fence
                out.append(line)
                continue
            if fence:
                out.append(self.mermaid(line))
                continue
            if line.lstrip().startswith("<img"):
                out.append(TEXT_ATTR.sub(lambda m: f'{m.group(1)}="{self.escaped(m.group(2))}"', line))
                continue
            out.append(self.md_line(line))
        path.write_text("\n".join(out) + "\n")

    def md_line(self, line: str) -> str:
        if line.startswith("|") and line.rstrip().endswith("|"):
            cells = line.strip()[1:-1].split(" | ")
            return "| " + " | ".join(self(c.strip()) for c in cells) + " |"

        m = re.match(r"^(\s*(?:#{1,6} |[-*] |\d+\. |> )?)(\*\*)?(.*?)(\*\*)?$", line)
        if not m:
            return self(line)
        prefix, b1, body, b2 = m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""
        if b1 and not b2:
            return prefix + self(b1 + body)
        return prefix + b1 + self(body) + b2

    def mermaid(self, line: str) -> str:
        m = re.match(r'^(\s*)"(.*)"(\s*:.*)$', line)
        if m:
            return f'{m.group(1)}"{self(m.group(2))}"{m.group(3)}'
        m = re.match(r"^(pie showData title )(.*)$", line)
        return m.group(1) + self(m.group(2)) if m else line

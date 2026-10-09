import html
import math
import asyncio
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright
from .config import ROOT, DATA
from .knowledge import topics, top_topics, SCORE_LEVELS,POSITION_NOTE

env = Environment(loader=FileSystemLoader(ROOT / "backend/templates"), autoescape=select_autoescape(["html"]))
PDF_LOCK = asyncio.Lock()

def chart(scores):
    chosen = top_topics(scores)
    names = {t["id"]: t.get("display", t["name"]) for t in topics()["items"]}
    if not chosen:
        return '<div class="chart-empty">本期材料尚不足以形成知识评分</div>'
    parts = ['<svg viewBox="0 0 360 270" role="img" aria-label="本期知识掌握评分">']
    if len(chosen) < 3:
        for i, score in enumerate(chosen):
            y = 70 + i * 85
            label = html.escape(names[score["id"]])
            parts += [f'<text x="18" y="{y - 12}" font-size="14" fill="#263b4c">{label}</text>',
                f'<rect x="18" y="{y}" width="285" height="14" rx="7" fill="#e7efef"/>',
                f'<rect x="18" y="{y}" width="{285 * score["score"] / 100}" height="14" rx="7" fill="#238b80"/>',
                f'<text x="315" y="{y + 13}" font-size="15" fill="#238b80">{score["score"]}</text>']
    else:
        n, cx, cy, radius = len(chosen), 180, 130, 82
        def point(i, r):
            angle = -math.pi / 2 + 2 * math.pi * i / n
            return cx + r * math.cos(angle), cy + r * math.sin(angle)
        def polygon(points):
            return " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        for value in (20, 40, 60, 80, 100):
            pts = [point(i, radius * value / 100) for i in range(n)]
            parts.append(f'<polygon points="{polygon(pts)}" fill="none" stroke="#d7e4e4" stroke-width="1"/>')
            parts.append(f'<text x="184" y="{cy - radius * value / 100 + 10}" font-size="8" fill="#849599">{value}</text>')
        for i in range(n):
            x, y = point(i, radius)
            parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x}" y2="{y}" stroke="#d7e4e4"/>')
        points = [point(i, radius * s["score"] / 100) for i, s in enumerate(chosen)]
        parts.append(f'<polygon points="{polygon(points)}" fill="#238b80" fill-opacity=".18" stroke="#238b80" stroke-width="2"/>')
        for i, score in enumerate(chosen):
            x, y = points[i]
            lx, ly = point(i, 112)
            anchor = "middle" if abs(lx - cx) < 10 else "start" if lx > cx else "end"
            label = html.escape(names[score["id"]])
            parts += [f'<circle cx="{x}" cy="{y}" r="3" fill="#238b80"/>',
                f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="12" fill="#263b4c">{label}</text>',
                f'<text x="{lx}" y="{ly + 16}" text-anchor="{anchor}" font-size="12" font-weight="600" fill="#238b80">{score["score"]}</text>']
    parts.append("</svg>")
    return "".join(parts)

def render(entry, report, revision=None):
    name = entry["student_snapshot"]["name"]
    def text(value):
        return value.replace("{{student}}", name)
    display = {**report, "title":text(report.get('title','').strip()) or name, "summary": text(report["summary"]), "highlights": [text(t) for t in report["highlights"]],
        "next_steps": [text(t) for t in report["next_steps"]], "admissions_text": text(report["admissions_text"]),
        "positions":report["positions"]}
    return env.get_template("report.html").render(report=display, name=name, period=entry["input"],
        demo=entry["input"]["mode"] == "demo", revision=revision, chart=chart(report["topic_scores"]),
        long_copy=sum(len(t) for t in report["highlights"]) > 550,
        score_levels=SCORE_LEVELS, position_note=POSITION_NOTE)

async def pdf_bytes(content, demo=False):
    async with PDF_LOCK:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                # No report can load remote images, fonts or other resources.
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(content, wait_until="load")
                await page.evaluate("document.fonts.ready")
                note = (await page.locator(".footer").text_content()) if await page.locator(".footer").count() else ""
                footer = '<div style="width:100%;padding:0 15mm;font-family: Noto Sans CJK SC, Microsoft YaHei, sans-serif;font-size:8px;line-height:1.6;color:#748790;">'
                footer += '<div style="border-top:1px solid #e0e9e9;padding-top:4px;text-align:left;">' + html.escape(note.strip()) + '</div>'
                footer += '<div style="text-align:center;margin-top:3px;">' + ("DEMO · " if demo else "") + '<span class="pageNumber"></span> / <span class="totalPages"></span></div></div>'
                return await page.pdf(format="A4", print_background=True, prefer_css_page_size=True,
                    display_header_footer=True, header_template='<span></span>',
                    footer_template=footer)
            finally:
                await browser.close()

async def save_version(entry, version):
    path = DATA / "pdf" / f"{version['id']}.pdf"
    if path.exists():
        return path
    snapshot = DATA / "html" / f"{version['id']}.html"
    content = snapshot.read_text(encoding="utf-8") if snapshot.exists() else render(entry, version["content"], version["revision"])
    data = await pdf_bytes(content, entry["input"]["mode"] == "demo")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(data)
    temporary.chmod(0o600)
    temporary.replace(path)
    return path

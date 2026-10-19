"""소개서 md → 인쇄용 HTML → PDF (headless Chrome). 최소 변환기(제목·목록·굵게·인용·코드만).

글꼴은 데모와 같은 부분 글꼴(mvp/fonts/AlfredoSans-subset.woff)을 파일로 읽는다(바깥 호출 없음).
PDF는 mvp/tools/check_demo.mjs의 pdf 모드(크롬 개발자 도구 printToPDF)로 만든다. `--print-to-pdf`는 멈춘 적이 있다(Top3 10-13).

실행(저장소 루트에서, build_demo.py 다음에): python3 -I mvp/make_pdf.py
결과: mvp/dist/알프레도_소개서_v2.html, mvp/dist/알프레도_소개서_v2.pdf (A4 1쪽인지 확인해 알려 준다)
"""
from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "mvp", "소개서_v2.md")
FONT = os.path.join(ROOT, "mvp", "fonts", "AlfredoSans-subset.woff")
TOOL = os.path.join(ROOT, "mvp", "tools", "check_demo.mjs")
DIST = os.path.join(ROOT, "mvp", "dist")

CSS = """
@font-face { font-family: "AlfredoSans"; src: url("../fonts/AlfredoSans-subset.woff") format("woff"); font-weight: 45 920; }
@page { size: A4; margin: 10mm 13mm; }
body { font: 8.9pt/1.42 "AlfredoSans", -apple-system, "Apple SD Gothic Neo", sans-serif; color: #111; word-break: keep-all; letter-spacing: -0.1px; }
h1 { font-size: 14pt; margin: 0 0 3px; }
h2 { font-size: 10pt; margin: 7px 0 2px; padding-bottom: 2px; border-bottom: 1px solid #ddd; }
p, ul, ol { margin: 3px 0; }
ul, ol { padding-left: 18px; }
li { margin: 1px 0; }
blockquote { margin: 4px 0 6px; padding: 5px 9px; background: #fff4d6; border-left: 3px solid #eda100; font-size: 8.6pt; }
blockquote p { margin: 0; }
code { font-size: 8.4pt; }
"""


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def md_to_html(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out, lst = [], None
    for line in md.splitlines():
        m_ul, m_ol = re.match(r"^- (.*)", line), re.match(r"^\d+\. (.*)", line)
        kind = "ul" if m_ul else "ol" if m_ol else None
        if lst and kind != lst:
            out.append(f"</{lst}>")
            lst = None
        if kind:
            if not lst:
                out.append(f"<{kind}>")
                lst = kind
            out.append(f"<li>{inline((m_ul or m_ol).group(1))}</li>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("> "):
            out.append(f"<blockquote><p>{inline(line[2:])}</p></blockquote>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if lst:
        out.append(f"</{lst}>")
    body = "\n".join(out).replace("</blockquote>\n<blockquote>", "")
    return f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>알프레도 소개서</title><style>{CSS}</style></head><body>{body}</body></html>'


def main() -> int:
    sys.path.insert(0, os.path.join(ROOT, "mvp"))
    from build_demo import missing_glyphs  # 불러오면 개인 경로·바깥 호출 지킴이도 켜진다

    with open(SRC, encoding="utf-8") as f:
        md = f.read()
    with open(FONT, "rb") as f:
        miss = missing_glyphs(md, f.read())
    if miss:
        print(f"부분 글꼴에 없는 글자: {''.join(miss)} → python3 -I mvp/build_demo.py 먼저", file=sys.stderr)
        return 1
    doc = md_to_html(md)
    os.makedirs(DIST, exist_ok=True)
    h, pdf = os.path.join(DIST, "알프레도_소개서_v2.html"), os.path.join(DIST, "알프레도_소개서_v2.pdf")
    with open(h, "w", encoding="utf-8") as f:
        f.write(doc)
    if os.path.exists(pdf):
        os.remove(pdf)
    sp = tempfile.mkdtemp(prefix="alfredo_pdf_")
    r = subprocess.run(["node", TOOL, "pdf", h, pdf], env=dict(os.environ, SP=sp), capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not os.path.exists(pdf):
        print("PDF를 만들지 못했다: " + (r.stdout + r.stderr)[-500:], file=sys.stderr)
        return 1
    pages = re.search(rb"/Type\s*/Page[^s]", open(pdf, "rb").read())
    n = len(re.findall(rb"/Type\s*/Page[^s]", open(pdf, "rb").read()))
    print(f"{pdf} ({os.path.getsize(pdf):,} bytes, {n}쪽{'' if n == 1 else ' ← A4 1쪽을 넘음'})")
    return 0 if n == 1 and pages else 1


if __name__ == "__main__":
    sys.exit(main())

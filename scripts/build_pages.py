"""Build the Keyway GitHub Pages site from tutorial/*.md.

Output: _site/  (gitignored; uploaded by .github/workflows/pages.yml)

Usage:
  pip install markdown
  python scripts/build_pages.py
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "tutorial"
ASSETS_SRC = ROOT / "src" / "keyway" / "web" / "assets"
OUT = ROOT / "_site"

PAGES_BASE = "/keyway"  # project Pages URL path
REPO_URL = "https://github.com/DeconBear/keyway"

# (stem, title_en, title_zh, blurb_en, blurb_zh)
CATALOG: list[tuple[str, str, str, str, str]] = [
    (
        "getting-started",
        "Getting Started",
        "快速开始",
        "Install, configure providers/routes/keys, and make your first request.",
        "安装配置、添加 Provider / 路由 / Key，并发出第一次请求。",
    ),
    (
        "multi-provider-setup",
        "Multi-Provider Setup",
        "多供应商配置",
        "Wire several upstreams and switch models from Claude Code.",
        "配置多个上游，并在 Claude Code 中切换模型。",
    ),
    (
        "multi-mode-processing",
        "Multi-Mode Processing",
        "多模式处理",
        "Direct, auto-select, adapter, and fusion routing modes.",
        "直连、自动选择、适配器与融合路由模式。",
    ),
    (
        "key-pool",
        "Upstream Key Pool",
        "上游 Key 池",
        "Pool upstream credentials and issue quota-limited user keys.",
        "聚合上游凭证，并向用户分发带配额的 Key。",
    ),
    (
        "api-reference",
        "API Reference",
        "API 参考",
        "Admin and OpenAI/Anthropic-compatible endpoint reference.",
        "管理端与 OpenAI/Anthropic 兼容接口说明。",
    ),
    (
        "architecture",
        "Architecture",
        "架构说明",
        "Internal layout, storage, and development notes.",
        "内部结构、存储与开发说明。",
    ),
]

MD_EXT = [
    "markdown.extensions.fenced_code",
    "markdown.extensions.tables",
    "markdown.extensions.toc",
    "markdown.extensions.nl2br",
    "markdown.extensions.sane_lists",
]

CSS = """\
:root {
  --bg: #f4f5f7; --surface: #fff; --border: #e1e4ea; --text: #1c2024;
  --muted: #667080; --primary: #3b5bfd; --code-bg: #f0f2f6;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue",
    Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
  --mono: ui-monospace, "Cascadia Code", Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e1014; --surface: #161a21; --border: #272d3a; --text: #dfe3ea;
    --muted: #98a1b0; --primary: #7d94ff; --code-bg: #1b202a;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: var(--font); background: var(--bg); color: var(--text);
  line-height: 1.65; font-size: 16px;
}
a { color: var(--primary); text-decoration: none; }
a:hover { text-decoration: underline; }
header {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; padding: 0.75rem 1.5rem;
  background: var(--surface); border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 0.6rem; font-weight: 700; }
.brand img { width: 28px; height: 28px; border-radius: 7px; }
.brand span.muted { font-weight: 500; font-size: 0.8rem; color: var(--muted); }
nav { display: flex; gap: 0.85rem; align-items: center; flex-wrap: wrap; font-size: 0.9rem; }
main { max-width: 880px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
.hero h1 { font-size: 2rem; margin: 0 0 0.5rem; letter-spacing: -0.02em; }
.hero p { color: var(--muted); margin: 0 0 1.75rem; max-width: 42rem; }
.grid { display: grid; gap: 0.85rem; }
@media (min-width: 640px) { .grid { grid-template-columns: 1fr 1fr; } }
.card {
  display: block; padding: 1.1rem 1.2rem; border: 1px solid var(--border);
  border-radius: 12px; background: var(--surface); color: inherit;
  transition: border-color .15s;
}
.card:hover { border-color: var(--primary); text-decoration: none; }
.card h2 { margin: 0 0 0.35rem; font-size: 1.05rem; }
.card p { margin: 0; color: var(--muted); font-size: 0.9rem; }
.card .lang { margin-top: 0.7rem; font-size: 0.8rem; }
.section-title { margin: 2rem 0 0.85rem; font-size: 0.75rem; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); }
article h1 { font-size: 1.85rem; margin: 0 0 1rem; }
article h2 { font-size: 1.3rem; margin: 1.8rem 0 0.7rem; }
article h3 { font-size: 1.1rem; margin: 1.4rem 0 0.5rem; }
article p, article li { color: var(--text); }
article hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
article code, article pre {
  font-family: var(--mono); font-size: 0.88em; background: var(--code-bg);
}
article code { padding: 0.1em 0.35em; border-radius: 4px; }
article pre {
  padding: 0.9rem 1rem; border-radius: 10px; overflow-x: auto;
  border: 1px solid var(--border);
}
article pre code { padding: 0; background: none; }
article table { width: 100%; border-collapse: collapse; font-size: 0.92rem; margin: 1rem 0; }
article th, article td {
  border: 1px solid var(--border); padding: 0.45rem 0.65rem; text-align: left;
  vertical-align: top;
}
article th { background: var(--code-bg); }
.meta { color: var(--muted); font-size: 0.85rem; margin-bottom: 1.25rem; }
footer {
  max-width: 880px; margin: 0 auto; padding: 0 1.25rem 2.5rem;
  color: var(--muted); font-size: 0.85rem;
}
"""


def _md_to_html(text: str) -> str:
    # Rewrite sibling .md links to .html for the static site.
    text = re.sub(r"\]\(([^)#]+)\.md(#[^)]*)?\)", r"](\1.html\2)", text)
    return markdown.markdown(text, extensions=MD_EXT)


def _page(title: str, body: str, *, lang: str = "en") -> str:
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title} — Keyway</title>
  <base href="{PAGES_BASE}/" />
  <link rel="icon" href="favicon.ico" sizes="any" />
  <link rel="icon" href="logo.svg" type="image/svg+xml" />
  <link rel="stylesheet" href="site.css" />
</head>
<body>
  <header>
    <a class="brand" href="index.html">
      <img src="logo.svg" alt="Keyway" />
      <span>Keyway</span>
      <span class="muted">Docs</span>
    </a>
    <nav>
      <a href="index.html">Home</a>
      <a href="{REPO_URL}" rel="noreferrer">GitHub</a>
      <a href="https://pypi.org/project/keyway-router/" rel="noreferrer">PyPI</a>
    </nav>
  </header>
  <main>
{body}
  </main>
  <footer>
    Keyway — MIT License ·
    <a href="{REPO_URL}">github.com/DeconBear/keyway</a>
  </footer>
</body>
</html>
"""


def _index_body() -> str:
    cards = []
    for stem, title_en, title_zh, blurb_en, blurb_zh in CATALOG:
        en = TUTORIAL / f"{stem}.md"
        zh = TUTORIAL / f"{stem}-zh.md"
        if not en.exists() and not zh.exists():
            continue
        langs = []
        if en.exists():
            langs.append(f'<a href="{stem}.html">English</a>')
        if zh.exists():
            langs.append(f'<a href="{stem}-zh.html">中文</a>')
        cards.append(
            f"""<div class="card">
  <h2>{title_en} / {title_zh}</h2>
  <p>{blurb_en}</p>
  <p style="margin-top:0.35rem">{blurb_zh}</p>
  <div class="lang">{" · ".join(langs)}</div>
</div>"""
        )
    grid = "\n".join(cards)
    return f"""<section class="hero">
  <h1>Keyway Documentation</h1>
  <p>Self-hosted LLM routing gateway with OpenAI &amp; Anthropic dual-protocol support.
     Tutorials below cover setup, multi-provider routing, key pools, and the API.</p>
</section>
<p class="section-title">Tutorials</p>
<div class="grid">
{grid}
</div>
"""


def build() -> Path:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    (OUT / "site.css").write_text(CSS, encoding="utf-8")
    for name in ("logo.svg", "favicon.ico", "logo-192.png"):
        src = ASSETS_SRC / name
        if src.exists():
            shutil.copy2(src, OUT / name)

    (OUT / "index.html").write_text(
        _page("Documentation", _index_body()), encoding="utf-8"
    )

    for path in sorted(TUTORIAL.glob("*.md")):
        html_body = _md_to_html(path.read_text(encoding="utf-8"))
        lang = "zh" if path.stem.endswith("-zh") else "en"
        title = path.stem.replace("-zh", "").replace("-", " ").title()
        # Prefer first markdown H1 if present
        m = re.search(r"^#\s+(.+)$", path.read_text(encoding="utf-8"), re.M)
        if m:
            title = m.group(1).strip()
        page = _page(
            title,
            f'<p class="meta"><a href="index.html">← Docs</a></p>\n'
            f"<article>\n{html_body}\n</article>",
            lang=lang,
        )
        (OUT / f"{path.stem}.html").write_text(page, encoding="utf-8")

    # GitHub Pages: avoid Jekyll processing
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"built {out} ({sum(1 for _ in out.rglob('*') if _.is_file())} files)")

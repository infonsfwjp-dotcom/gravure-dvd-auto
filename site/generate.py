from __future__ import annotations
import html, json, os, re, shutil
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
DIST = ROOT / "dist"
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")


def esc(x):
    return html.escape(str(x or ""), quote=True)


def load():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []


def slug(x):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(x or "unknown")).strip("-") or "unknown"


def product_path(p):
    return f"/products/{slug(p.get('maker_id'))}-{slug(p.get('product_code') or p.get('jan') or p.get('title'))}.html"


def url(path):
    return f"{SITE_URL}/{path.lstrip('/')}" if SITE_URL else "/" + path.lstrip("/")


def page(title, body, canonical_path="/", description="グラビアDVDの新発売情報を月別・メーカー別に自動更新"):
    canonical = url(canonical_path)
    ld = ''
    if canonical_path.startswith('/products/'):
        ld = '<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": canonical}, ensure_ascii=False) + '</script>'
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(canonical)}">{ld}<style>*{{box-sizing:border-box}}body{{margin:0;background:#f6f6f6;color:#181818;font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif}}header{{background:#111;color:#fff;padding:24px 16px}}header .in,main{{max-width:1100px;margin:auto}}nav a{{color:#fff;margin-right:16px}}main{{padding:24px 16px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}.card,.box{{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 12px #0001}}a{{color:inherit}}.btn{{display:inline-block;background:#111;color:#fff;padding:9px 13px;border-radius:8px;text-decoration:none}}.buy{{background:#d22;color:#fff;padding:13px 18px;border-radius:9px;text-decoration:none;display:inline-block}}.muted{{color:#777;font-size:13px}}.meta{{width:100%;border-collapse:collapse}}.meta th,.meta td{{padding:10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}.meta th{{width:130px;color:#666}}.back{{margin-top:20px}}</style></head><body><header><div class="in"><h1>グラビアDVD新発売情報</h1><nav><a href="/">トップ</a><a href="/makers/">メーカー別</a><a href="/months/">月別</a></nav></div></header><main>{body}</main></body></html>'''


def write(rel, title, body, description="グラビアDVDの新発売情報を月別・メーカー別に自動更新"):
    path = DIST / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(title, body, "/" + rel, description), encoding="utf-8")


def card(p):
    href = product_path(p)
    talent = "、".join(p.get("talent") or [])
    return f'<article class="card"><div class="date">{esc(p.get("release_date"))}</div><h2><a href="{href}">{esc(p.get("title"))}</a></h2><p>{esc(p.get("maker"))}</p>{f"<p>{esc(talent)}</p>" if talent else ""}<a class="btn" href="{href}">詳細を見る</a></article>'


def product_page(p):
    title = str(p.get("title") or "グラビアDVD")
    maker = str(p.get("maker") or "")
    talent = "、".join(p.get("talent") or [])
    release = str(p.get("release_date") or "")
    jan = str(p.get("jan") or "")
    code = str(p.get("product_code") or "")
    status = str(p.get("status") or "")
    source = str(p.get("source_url") or "")
    buy = str(p.get("affiliate_url") or "")
    rows = []
    for label, value in (("メーカー", maker), ("出演", talent), ("発売日", release), ("JAN", jan), ("品番", code), ("発売状況", status)):
        if value:
            rows.append(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>")
    actions = []
    if buy:
        actions.append(f'<a class="buy" href="{esc(buy)}" rel="sponsored nofollow">FANZAで購入する</a>')
    if source:
        actions.append(f'<a class="btn" href="{esc(source)}" rel="nofollow">メーカー公式情報</a>')
    body = f'<div class="box"><p class="muted">{esc(maker)} / {esc(release)}</p><h2>{esc(title)}</h2><table class="meta">{"".join(rows)}</table><p>{"　".join(actions) if actions else "FANZA商品情報を確認中です。"}</p><p class="back"><a href="/">← 新作一覧へ戻る</a></p></div>'
    return body


def main():
    ps = load()
    bym = defaultdict(list)
    bymaker = defaultdict(list)
    for p in ps:
        if p.get("release_date"):
            bym[p["release_date"][:7]].append(p)
        bymaker[p.get("maker_id", "unknown")].append(p)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True, exist_ok=True)

    for p in ps:
        rel = product_path(p).lstrip("/")
        write(rel, str(p.get("title") or "グラビアDVD"), product_page(p), f"{p.get('title','グラビアDVD')}｜発売日 {p.get('release_date','')}｜{p.get('maker','')} のグラビアDVD情報")

    latest = sorted(ps, key=lambda x: x.get("release_date") or "", reverse=True)[:50]
    write("index.html", "グラビアDVD新発売情報", '<h2>最新発売情報</h2><div class="grid">' + ''.join(card(p) for p in latest) + f'</div><p class="muted">登録商品数：{len(ps)}</p>')

    links = ''.join(f'<li><a href="/months/{m}.html">{m}</a>（{len(v)}件）</li>' for m, v in sorted(bym.items(), reverse=True))
    write("months/index.html", "月別一覧", f'<h2>月別</h2><ul>{links}</ul>')
    for m, v in bym.items():
        write(f"months/{m}.html", f"{m} 発売", '<h2>' + esc(m) + ' 発売</h2><div class="grid">' + ''.join(card(p) for p in sorted(v, key=lambda x: x.get("release_date") or "", reverse=True)) + '</div>')

    links = ''.join(f'<li><a href="/makers/{k}.html">{esc(v[0].get("maker", k))}</a>（{len(v)}件）</li>' for k, v in sorted(bymaker.items()))
    write("makers/index.html", "メーカー別一覧", f'<h2>メーカー別</h2><ul>{links}</ul>')
    for k, v in bymaker.items():
        write(f"makers/{k}.html", f"{v[0].get('maker', k)} DVD", '<h2>' + esc(v[0].get('maker', k)) + '</h2><div class="grid">' + ''.join(card(p) for p in sorted(v, key=lambda x: x.get("release_date") or "", reverse=True)) + '</div>')

    sitemap_paths = ["/", "/months/", "/makers/"] + [product_path(p) for p in ps] + [f"/months/{m}.html" for m in bym] + [f"/makers/{k}.html" for k in bymaker]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{esc(url(p))}</loc></url>' for p in sitemap_paths) + '</urlset>'
    (DIST / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    robots_sitemap = f"{SITE_URL}/sitemap.xml" if SITE_URL else "/sitemap.xml"
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {robots_sitemap}\n", encoding="utf-8")


if __name__ == "__main__":
    main()

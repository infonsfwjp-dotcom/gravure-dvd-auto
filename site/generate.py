from __future__ import annotations
import html, json, os, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
DIST = ROOT / "dist"
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")

def esc(x):
    return html.escape(str(x or ""))

def load():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []

def slug(x):
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(x or "unknown")).strip("-") or "unknown"

def url(path):
    return f"{SITE_URL}/{path.lstrip('/')}" if SITE_URL else "/" + path.lstrip("/")

def card(p):
    href = f"/products/{slug(p.get('maker_id'))}-{slug(p.get('product_code') or p.get('title'))}.html"
    return f'<article class="card"><div class="date">{esc(p.get("release_date"))}</div><h2><a href="{href}">{esc(p.get("title"))}</a></h2><p>{esc(p.get("maker"))}</p><p>{esc("、".join(p.get("talent") or []))}</p><a class="btn" href="{href}">詳細を見る</a></article>'

def page(title, body, canonical_path="/"):
    canonical = url(canonical_path)
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="グラビアDVDの新発売情報を月別・メーカー別に自動更新"><link rel="canonical" href="{esc(canonical)}"><style>*{{box-sizing:border-box}}body{{margin:0;background:#f6f6f6;color:#181818;font-family:system-ui,-apple-system,"Noto Sans JP",sans-serif}}header{{background:#111;color:#fff;padding:24px 16px}}header .in,main{{max-width:1100px;margin:auto}}nav a{{color:#fff;margin-right:16px}}main{{padding:24px 16px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}.card,.box{{background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 12px #0001}}a{{color:inherit}}.btn{{display:inline-block;background:#111;color:#fff;padding:9px 13px;border-radius:8px;text-decoration:none}}.buy{{background:#d22;color:#fff;padding:13px 18px;border-radius:9px;text-decoration:none;display:inline-block}}.muted{{color:#777;font-size:13px}}</style></head><body><header><div class="in"><h1>グラビアDVD新発売情報</h1><nav><a href="/">トップ</a><a href="/makers/">メーカー別</a><a href="/months/">月別</a></nav></div></header><main>{body}</main></body></html>'''

def write(rel, title, body):
    path = DIST / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(title, body, "/" + rel), encoding="utf-8")

def main():
    ps = load()
    bym = defaultdict(list)
    bymaker = defaultdict(list)
    for p in ps:
        if p.get("release_date"):
            bym[p["release_date"][:7]].append(p)
        bymaker[p.get("maker_id", "unknown")].append(p)
    write("index.html", "グラビアDVD新発売情報", '<h2>最新発売情報</h2><div class="grid">' + ''.join(card(p) for p in sorted(ps, key=lambda x: x.get("release_date") or "", reverse=True)[:50]) + f'</div><p class="muted">登録商品数：{len(ps)}</p>')
    links = ''.join(f'<li><a href="/months/{m}.html">{m}</a>（{len(v)}件）</li>' for m, v in sorted(bym.items(), reverse=True))
    write("months/index.html", "月別一覧", f'<h2>月別</h2><ul>{links}</ul>')
    for m, v in bym.items():
        write(f"months/{m}.html", f"{m} 発売", '<h2>' + esc(m) + ' 発売</h2><div class="grid">' + ''.join(card(p) for p in v) + '</div>')
    links = ''.join(f'<li><a href="/makers/{k}.html">{esc(v[0].get("maker", k))}</a>（{len(v)}件）</li>' for k, v in sorted(bymaker.items()))
    write("makers/index.html", "メーカー別一覧", f'<h2>メーカー別</h2><ul>{links}</ul>')
    for k, v in bymaker.items():
        write(f"makers/{k}.html", f"{v[0].get('maker', k)} DVD", '<h2>' + esc(v[0].get('maker', k)) + '</h2><div class="grid">' + ''.join(card(p) for p in v) + '</div>')
    sitemap_paths = ["/", "/months/", "/makers/"] + [f"/months/{m}.html" for m in bym] + [f"/makers/{k}.html" for k in bymaker]
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{esc(url(p))}</loc></url>' for p in sitemap_paths) + '</urlset>'
    (DIST / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    robots_sitemap = f"{SITE_URL}/sitemap.xml" if SITE_URL else "/sitemap.xml"
    (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {robots_sitemap}\n", encoding="utf-8")

if __name__ == "__main__":
    main()

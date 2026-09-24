from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

API_BASE = os.getenv("DMM_API_URL", "https://api.dmm.com/affiliate/v3/ItemList").rsplit("/", 1)[0]
ITEM_API_URL = f"{API_BASE}/ItemList"
FLOOR_API_URL = f"{API_BASE}/FloorList"
MAKER_API_URL = f"{API_BASE}/MakerSearch"
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")
SITE = "FANZA"
OUT = Path(__file__).resolve().parents[1] / "data/products.json"

KNOWN_DMM_MAKER_IDS = {"i-one": "60091"}

DMM_MAKER_LIST_URLS = {
    "i-one": [
        "https://www.dmm.com/mono/dvd/-/list/=/article=maker/id=60091/",
        "https://www.dmm.co.jp/mono/dvd/-/list/=/article=maker/id=60091/",
    ],
}
DMM_LIST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}

def _absolute_url(base, href):
    from urllib.parse import urljoin
    return urljoin(base, href)

def crawl_dmm_maker_list(maker_id, start_date):
    """Use the public DMM maker list as the primary catalog source.

    The Affiliate API maker search is only an enrichment layer.  The maker
    list determines which products belong to Line Communications.
    """
    urls = DMM_MAKER_LIST_URLS.get(maker_id) or []
    session = requests.Session()
    session.headers.update(DMM_LIST_HEADERS)
    visited = set()
    product_cids = []
    product_meta = {}
    queue = list(urls)
    pages = 0

    while queue and pages < 100:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
        except Exception as exc:
            print(f"  DMM maker list fetch failed url={url} error={exc}")
            continue
        pages += 1
        soup = BeautifulSoup(r.text, "html.parser")
        page_cids = []
        for a in soup.find_all("a", href=True):
            href = _absolute_url(url, unquote(unquote(a.get("href", ""))))
            m = re.search(r"/(?:mono/dvd)/-/detail/=/cid=([a-zA-Z0-9_-]+)", href, re.I)
            if not m:
                m = re.search(r"(?:^|[?&])cid=([a-zA-Z0-9_-]+)", href, re.I)
            if not m:
                continue
            cid = m.group(1).lower()
            if cid in product_meta:
                continue
            card = a
            for _ in range(5):
                parent = getattr(card, "parent", None)
                if parent is None:
                    break
                text = parent.get_text(" ", strip=True)
                if re.search(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}", text):
                    card = parent
                    break
                card = parent
            text = card.get_text(" ", strip=True)
            dates = re.findall(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", text)
            release = ""
            for y, mo, d in dates:
                candidate = f"{y}-{int(mo):02d}-{int(d):02d}"
                if candidate >= start_date:
                    release = candidate
                    break
            product_meta[cid] = {"cid": cid, "release_date": release, "url": href, "text": text[:1000]}
            page_cids.append(cid)
            if cid not in product_cids:
                product_cids.append(cid)

        # Follow pagination exposed by the page itself.  Do not guess DMM's
        # pagination format; only follow links that actually exist in HTML.
        next_candidates = []
        for a in soup.find_all("a", href=True):
            href = _absolute_url(url, unquote(unquote(a.get("href", ""))))
            label = a.get_text(" ", strip=True)
            if href in visited:
                continue
            if re.search(r"(?:page(?:=|/)|p=|/page/|offset=|/p/)", href, re.I) or re.search(r"次|次へ|next|›|»", label, re.I):
                next_candidates.append(href)
        for nxt in next_candidates:
            if nxt not in visited and nxt not in queue:
                queue.append(nxt)

        print(f"  DMM maker list page={pages} products={len(page_cids)} queue={len(queue)} url={url}")
        if not page_cids and not next_candidates:
            break

    return product_cids, product_meta

def dmm_items_from_maker_list(maker, start_date):
    """Resolve maker-list CIDs into structured FANZA/DMM item records."""
    cids, meta = crawl_dmm_maker_list(maker["id"], start_date)
    out = {}
    for idx, cid in enumerate(cids, 1):
        try:
            items = request_items({
                "api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE,
                "service": "mono", "floor": "dvd", "cid": cid,
                "hits": 20, "offset": 1, "output": "json",
            })
        except Exception as exc:
            print(f"  DMM maker CID failed cid={cid} error={exc}")
            continue
        for item in items:
            if not line_communications_item(item):
                raw = norm(json.dumps(item, ensure_ascii=False))
                if "lcdv" not in raw:
                    continue
            release_date = str(item.get("date") or "")[:10] or meta.get(cid, {}).get("release_date", "")
            if not release_date or release_date < start_date:
                continue
            key = item.get("product_id") or item.get("content_id") or item.get("URL") or cid
            out[key] = item
        if idx % 20 == 0:
            print(f"  DMM maker list resolved {idx}/{len(cids)}")
        time.sleep(0.08)
    print(f"  DMM maker list source={maker['name']} cids={len(cids)} resolved={len(out)}")
    return out

def dedupe_limited_products(products):
    """Drop limited/bonus variants when a normal DVD for the same work exists."""
    def base_title(title):
        s = str(title or "")
        s = re.sub(r"【[^】]*(?:限定|特典|チェキ)[^】]*】", "", s)
        s = re.sub(r"\\[[^\\]]*(?:限定|特典|チェキ)[^\\]]*\\]", "", s)
        s = re.sub(r"(?:I-ONE TV)?限定(?:版|盤)?", "", s, flags=re.I)
        s = re.sub(r"(?:特典|チェキ)(?:映像|付き|付)?", "", s)
        return norm(s)
    groups = {}
    for p in products:
        key = (p.get("maker_id"), p.get("release_date"), base_title(p.get("title")))
        groups.setdefault(key, []).append(p)
    kept = []
    removed = 0
    markers = ("限定", "特典", "チェキ")
    for group in groups.values():
        normal = [p for p in group if not any(m in str(p.get("title") or "") for m in markers)]
        if normal:
            for p in group:
                if any(m in str(p.get("title") or "") for m in markers):
                    removed += 1
                else:
                    kept.append(p)
        else:
            kept.extend(group)
    print(f"  limited duplicate removal={removed}")
    return kept

MAKERS = [
    {"id": "spice_visual", "name": "スパイスビジュアル", "keywords": ["スパイスビジュアル", "Spice Visual"], "strict_idol": False},
    {"id": "i-one", "name": "ラインコミュニケーションズ", "keywords": ["ラインコミュニケーションズ"], "strict_idol": False},
    {"id": "takeshobo", "name": "竹書房", "keywords": ["竹書房"], "strict_idol": True},
]
INCLUDE_GENRE = ("アイドル", "グラビア", "イメージ")
EXCLUDE_TITLE = ("写真集", "コミック", "漫画", "雑誌")


def norm(s: str) -> str:
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(s or "")).lower()


def iteminfo_names(item, key):
    value = (item.get("iteminfo") or {}).get(key)
    values = value if isinstance(value, list) else [value]
    return [str(x.get("name") or x.get("value") or x.get("id") or "") for x in values if x]


def maker_names(item):
    names = []
    for key in ("maker", "manufacturer", "label"):
        names.extend(iteminfo_names(item, key))
    for key in ("maker_name", "manufacturer_name", "maker"):
        if item.get(key): names.append(str(item[key]))
    return names


def genre_names(item):
    names = iteminfo_names(item, "genre")
    for key in ("genre", "genres"):
        value = item.get(key)
        if isinstance(value, list): names.extend(str(x.get("name") if isinstance(x, dict) else x) for x in value)
        elif value: names.append(str(value))
    return names


def line_communications_item(item):
    """Identify Line Communications DVDs from FANZA/DMM catalog data."""
    hay = norm(" ".join(maker_names(item)))
    if "ラインコミュニケーションズ" in hay:
        return True
    codes = " ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid"))
    return bool(re.search(r"\blcdv-\d{4,6}\b", codes, re.I))


def maker_matches(item, maker, search_keyword=None):
    if maker["id"] == "i-one" and line_communications_item(item):
        return True
    hay = " ".join(maker_names(item))
    if any(norm(k) in norm(hay) or norm(hay) in norm(k) for k in maker["keywords"] if hay): return True
    if search_keyword:
        raw = norm(json.dumps(item, ensure_ascii=False))
        return bool(norm(search_keyword)) and norm(search_keyword) in raw
    return not hay and not maker["strict_idol"]


def is_takeshobo_idol(item):
    title = str(item.get("title") or "")
    if any(x in title for x in EXCLUDE_TITLE): return False
    return any(x in " ".join(genre_names(item)) for x in INCLUDE_GENRE)


def request_json(url, params):
    r = requests.get(url, params=params, timeout=30)
    if r.status_code >= 400: raise RuntimeError(f"DMM API HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def request_items(params):
    return request_json(ITEM_API_URL, params).get("result", {}).get("items", []) or []


def talent_names(item):
    out = []
    for key in ("actress", "actor", "author"):
        for name in iteminfo_names(item, key):
            name = re.sub(r"^[ー―–—-]+\s*", "", name).strip()
            if name and name not in out: out.append(name)
    return out


def _urls_from_value(value):
    found = []
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return [value]
    if isinstance(value, list):
        for x in value:
            found.extend(_urls_from_value(x))
    elif isinstance(value, dict):
        for x in value.values():
            found.extend(_urls_from_value(x))
    return found


def sample_media(item):
    """Extract DMM/FANZA sample media without inventing or downloading URLs."""
    images, movies, cover = [], [], []
    for key, value in item.items():
        key_n = re.sub(r"[^a-z0-9]", "", str(key).lower())
        urls = _urls_from_value(value)
        if "sampleimage" in key_n:
            images.extend(urls)
        elif "samplemovie" in key_n or "samplevideo" in key_n:
            movies.extend(urls)
        elif key_n == "imageurl":
            cover.extend(urls)
    def unique(values, limit=None):
        out = []
        for value in values:
            if value and value not in out: out.append(value)
            if limit and len(out) >= limit: break
        return out
    return {
        "cover_image_url": unique(cover, 1)[0] if cover else "",
        "sample_image_urls": unique(images, 15),
        "sample_video_url": unique(movies, 1)[0] if movies else "",
        "sample_available": bool(movies),
    }


def find_dvd_floor_ids():
    data = request_json(FLOOR_API_URL, {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "output": "json"})
    found = []
    def walk(value, parent_text=""):
        if isinstance(value, dict):
            code = str(value.get("code") or value.get("floor_code") or "").lower(); name = str(value.get("name") or value.get("floor_name") or ""); fid = str(value.get("id") or value.get("floor_id") or "")
            context = f"{parent_text} {code} {name}".lower()
            if fid and (code in {"dvd", "mono-dvd", "monodvd"} or ("dvd" in context and ("mono" in context or "通販" in context))):
                if fid not in found: found.append(fid)
            for v in value.values(): walk(v, context)
        elif isinstance(value, list):
            for v in value: walk(v, parent_text)
    walk(data); print(f"  dvd floor ids: {found}"); return found


def find_maker_ids(floor_ids, maker):
    found = {}
    for floor_id in floor_ids:
        offset = 1
        while offset <= 5000:
            try:
                data = request_json(MAKER_API_URL, {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "floor_id": floor_id, "hits": 100, "offset": offset, "output": "json"})
            except RuntimeError as exc:
                if "HTTP 400" in str(exc) and "Invalid Request Error" in str(exc): print(f"  skip invalid MakerSearch floor_id={floor_id}"); break
                raise
            result = data.get("result", {}) or {}; makers = result.get("makers") or result.get("maker") or []
            if isinstance(makers, dict): makers = makers.get("maker") or []
            if not makers: break
            for m in makers:
                mid = str(m.get("id") or m.get("maker_id") or ""); name = str(m.get("name") or "")
                if mid and name and any(norm(k) in norm(name) or norm(name) in norm(k) for k in maker["keywords"]): found[mid] = name
            if len(makers) < 100: break
            offset += 100; time.sleep(0.1)
        time.sleep(0.1)
    if not found and maker["id"] in KNOWN_DMM_MAKER_IDS:
        found[KNOWN_DMM_MAKER_IDS[maker["id"]]] = maker["name"]
        print(f"  using known DMM maker id {maker['id']}: {KNOWN_DMM_MAKER_IDS[maker['id']]}")
    return found


def official_dmm_cids(soup):
    found = []
    for a in soup.find_all("a", href=True):
        href = unquote(unquote(a.get("href", ""))); label = a.get_text(" ", strip=True)
        if "dmm" not in href.lower() and "fanza" not in href.lower() and "DMM" not in label.upper(): continue
        for m in re.finditer(r"/(?:mono/dvd|digital/videoa)/-/detail/=/cid=([a-zA-Z0-9_-]+)", href, re.I):
            if m.group(1).lower() not in found: found.append(m.group(1).lower())
        try:
            for value in parse_qs(urlparse(href).query).values():
                for v in value:
                    for m in re.finditer(r"(?:^|[?&])cid=([a-zA-Z0-9_-]+)", unquote(unquote(v)), re.I):
                        if m.group(1).lower() not in found: found.append(m.group(1).lower())
        except ValueError: pass
    return found[:20]


def dmm_match_for_cids(cids, code, title_hint, model_hint):
    for cid in cids:
        try: dmm_items = request_items({"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "service": "mono", "floor": "dvd", "cid": cid, "hits": 20, "offset": 1, "output": "json"})
        except RuntimeError: continue
        for item in dmm_items:
            raw = norm(json.dumps(item, ensure_ascii=False)); item_makers = norm(" ".join(maker_names(item)))
            item_code = norm(" ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid"))); title_norm = norm(item.get("title") or "")
            if norm(code) in item_code or ("ラインコミュニケーションズ" in item_makers or "i-one" in raw or "アイドルワン" in raw) and (bool(title_hint and norm(title_hint) in title_norm) or bool(model_hint and norm(model_hint) in title_norm)) or cid in item_code: return item
    return None


def discover():
    if not API_ID or not AFFILIATE_ID: raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    today = date.today(); start = date(2026, 6, 1); end = today + timedelta(days=180); all_items = {}
    floor_ids = find_dvd_floor_ids(); maker_ids = {}
    for maker in MAKERS:
        maker_ids[maker["id"]] = find_maker_ids(floor_ids, maker)
        if maker["id"] in KNOWN_DMM_MAKER_IDS:
            maker_ids[maker["id"]][KNOWN_DMM_MAKER_IDS[maker["id"]]] = maker["name"]
        print(f"  maker ids {maker['id']}: {maker_ids[maker['id']]}")
    # Line Communications: use the confirmed FANZA/DMM manufacturer ID directly.
    # Keep only releases from 2026-06-01 onward; copy the returned catalog fields as-is.
    for maker in MAKERS:
        ids = list(maker_ids.get(maker["id"], {}).keys())
        if maker["id"] == "i-one":
            # Primary source: the public DMM maker catalog for maker_id=60091.
            # The Affiliate API is used only to resolve each catalog CID into
            # structured fields and an affiliate URL.
            listed = dmm_items_from_maker_list(maker, start.isoformat())
            for key, item in listed.items():
                all_items[(maker["id"], key)] = (maker, item)

            # Keep an exact CID recovery path for LCDV-41448 in case the maker
            # page exposes the product before the API indexes its maker facet.
            cid_items = request_items({
                "api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE,
                "service": "mono", "floor": "dvd", "cid": "n_691lcdv41448",
                "hits": 20, "offset": 1, "output": "json",
            })
            print(f"  Line Communications exact CID n_691lcdv41448 lookup items={len(cid_items)}")
            for item in cid_items:
                raw = norm(json.dumps(item, ensure_ascii=False))
                code_fields = " ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid"))
                if "lcdv41448" not in norm(code_fields) and "n_691lcdv41448" not in raw:
                    continue
                release_date = str(item.get("date") or "")[:10]
                if release_date and release_date >= start.isoformat():
                    key = item.get("product_id") or item.get("content_id") or item.get("URL")
                    if key:
                        all_items[(maker["id"], key)] = (maker, item)
            continue

        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=30), end)
            queries = [(None, mid) for mid in ids] + [(keyword, None) for keyword in maker["keywords"]]
            for keyword, maker_id in queries:
                offset = 1
                while offset <= 5000:
                    params = {
                        "api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE,
                        "service": "mono", "floor": "dvd",
                        "gte_date": f"{cursor.isoformat()}T00:00:00",
                        "lte_date": f"{window_end.isoformat()}T23:59:59",
                        "sort": "date", "hits": 100, "offset": offset, "output": "json",
                    }
                    if cursor >= today:
                        params["mono_stock"] = "reserve"
                    if maker_id:
                        params["article"] = "maker"; params["article_id"] = maker_id
                    else:
                        params["keyword"] = keyword
                    items = request_items(params)
                    print(f"  query maker={maker['id']} keyword={keyword or '-'} maker_id={maker_id or '-'} offset={offset} items={len(items)}")
                    for item in items:
                        if not maker_matches(item, maker, search_keyword=keyword):
                            continue
                        if maker["strict_idol"] and not is_takeshobo_idol(item):
                            continue
                        key = item.get("product_id") or item.get("content_id") or item.get("URL")
                        if key:
                            all_items[(maker["id"], key)] = (maker, item)
                    if len(items) < 100:
                        break
                    offset += 100
                    time.sleep(0.1)
                time.sleep(0.2)
            cursor = window_end + timedelta(days=1)
    products = []
    for maker, item in all_items.values():
        title = str(item.get("title") or "").strip(); release_date = str(item.get("date") or "")[:10]; code = str(item.get("maker_product") or item.get("product_id") or item.get("content_id") or "").strip(); jan = re.sub(r"\D", "", str(item.get("jancode") or item.get("jan") or ""))
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date): continue
        media = sample_media(item)
        products.append({"maker": maker["name"], "maker_id": maker["id"], "title": title, "release_date": release_date, "product_code": code, "jan": jan, "talent": talent_names(item), "source_url": item.get("URL") or "", "affiliate_url": item.get("affiliateURL") or "", "dmm_url": item.get("URL") or "", "affiliate_match_status": "matched" if item.get("affiliateURL") else "unmatched", "status": "upcoming" if release_date >= today.isoformat() else "released", "cover_image_url": media["cover_image_url"], "sample_image_urls": media["sample_image_urls"], "sample_video_url": media["sample_video_url"], "sample_available": media["sample_available"], "tags": [release_date[:4]+"年", release_date[:7]+"月", release_date[:7]+"発売", maker["name"]]})
    products = dedupe_limited_products(products)\n    products.sort(key=lambda p: (p["release_date"], p["maker"], p["title"]), reverse=True); return products


def main():
    products = discover()
    if not products: raise RuntimeError("DMM discovery returned zero accepted products; refusing to overwrite existing data")
    OUT.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"dmm discovery products={len(products)}")
    for maker in MAKERS: print(f"  {maker['id']}: {sum(1 for p in products if p['maker_id'] == maker['id'])}")


if __name__ == "__main__": main()

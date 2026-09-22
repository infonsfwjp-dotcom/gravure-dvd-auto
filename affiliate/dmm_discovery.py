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

MAKERS = [
    {"id": "spice_visual", "name": "スパイスビジュアル", "keywords": ["スパイスビジュアル", "Spice Visual"], "strict_idol": False},
    {"id": "i-one", "name": "ラインコミュニケーションズ / I-ONE", "keywords": ["ラインコミュニケーションズ", "I-ONE", "I ONE"], "strict_idol": False},
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


def maker_matches(item, maker, search_keyword=None):
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
        "sample_image_urls": unique(images, 12),
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


def discover_i_one_fallback(start, end, all_items):
    maker = next(m for m in MAKERS if m["id"] == "i-one"); base = "https://i-one.tv/content/?maker=line-communications&page={}"
    seen_urls, candidates = set(), []
    for page in range(1, 11):
        try:
            r = requests.get(base.format(page), timeout=30, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status()
        except requests.RequestException as exc: print(f"  i-one fallback page={page} error={exc}"); continue
        soup = BeautifulSoup(r.text, "html.parser"); links = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/content/detail/" not in href: continue
            url = requests.compat.urljoin(r.url, href)
            if url not in seen_urls: seen_urls.add(url); links.append(url)
        print(f"  i-one fallback page={page} detail_links={len(links)}")
        if not links: break
        candidates.extend(links)
        if page >= 3 and len(candidates) >= 90: break

    for url in candidates:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}); r.raise_for_status()
        except requests.RequestException: continue
        soup = BeautifulSoup(r.text, "html.parser"); text = soup.get_text(" ", strip=True)
        code_m = re.search(r"品番\s*[：:]\s*([A-Z0-9-]+)", text, re.I); date_m = re.search(r"発売日\s*[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})", text)
        if not code_m or not date_m: continue
        code = code_m.group(1).upper(); release = date(int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)))
        if not (start <= release <= end): continue
        title_hint = ""; og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"): title_hint = og["content"].strip()
        if not title_hint and soup.title: title_hint = soup.title.get_text(" ", strip=True).split("｜")[0].strip()
        model_m = re.search(r"モデル名\s*[：:]\s*([^\n]{1,80}?)(?:\s+商品詳細|\s+ファイル内容|\s+発売日)", text)
        model_hint = model_m.group(1).strip() if model_m else ""; title_hint = re.sub(r"\s*\[[^\]]*\]", "", title_hint).strip()

        official_cids = official_dmm_cids(soup)
        matched = dmm_match_for_cids(official_cids, code, title_hint, model_hint)
        if matched: print(f"  i-one official DMM link matched code={code}")

        if not matched:
            for keyword in (code, title_hint, model_hint):
                if not keyword: continue
                try:
                    params = {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "service": "mono", "floor": "dvd", "gte_date": f"{(release-timedelta(days=5)).isoformat()}T00:00:00", "lte_date": f"{(release+timedelta(days=5)).isoformat()}T23:59:59", "sort": "date", "mono_stock": "reserve", "keyword": keyword, "hits": 100, "offset": 1, "output": "json"}
                    dmm_items = request_items(params)
                except RuntimeError: continue
                for item in dmm_items:
                    raw = norm(json.dumps(item, ensure_ascii=False)); item_makers = norm(" ".join(maker_names(item)))
                    item_code = norm(" ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid"))); title_norm = norm(item.get("title") or "")
                    code_ok = norm(code) in item_code; maker_ok = "ラインコミュニケーションズ" in item_makers or "i-one" in raw or "アイドルワン" in raw; title_ok = norm(keyword) in title_norm or (model_hint and norm(model_hint) in title_norm)
                    if code_ok or (maker_ok and title_ok): matched = item; break
                if matched: break

        if matched:
            key = matched.get("product_id") or matched.get("content_id") or matched.get("URL")
            if key: all_items[(maker["id"], key)] = (maker, matched); print(f"  i-one fallback matched code={code} title={matched.get('title','')}")
        else: print(f"  i-one fallback no DMM match code={code} title={title_hint}")


def discover():
    if not API_ID or not AFFILIATE_ID: raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    today = date.today(); start = today - timedelta(days=30); end = today + timedelta(days=180); all_items = {}
    existing = {}
    existing_by_norm_code = {}
    existing_by_title = {}
    if OUT.exists():
        try:
            existing = {str(p.get("product_code") or "").strip(): p for p in json.loads(OUT.read_text(encoding="utf-8")) if p.get("product_code")}
            existing_by_norm_code = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in existing.items() if k}
            existing_by_title = {re.sub(r"[^a-z0-9]", "", re.sub(r"【.*?】|4Kあり", "", str(v.get("title") or "")).lower()): v for v in existing.values() if v.get("title")}
        except Exception:
            existing = {}
    floor_ids = find_dvd_floor_ids(); maker_ids = {}
    for maker in MAKERS:
        maker_ids[maker["id"]] = find_maker_ids(floor_ids, maker); print(f"  maker ids {maker['id']}: {maker_ids[maker['id']]}")
    for maker in MAKERS:
        ids = list(maker_ids.get(maker["id"], {}).keys()); cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=30), end); queries = [(None, mid) for mid in ids] + [(keyword, None) for keyword in maker["keywords"]]; seen_query_keys = set()
            for keyword, maker_id in queries:
                if (keyword, maker_id) in seen_query_keys: continue
                seen_query_keys.add((keyword, maker_id)); offset = 1
                while offset <= 5000:
                    params = {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "service": "mono", "floor": "dvd", "gte_date": f"{cursor.isoformat()}T00:00:00", "lte_date": f"{window_end.isoformat()}T23:59:59", "sort": "date", "hits": 100, "offset": offset, "output": "json"}
                    if cursor >= today: params["mono_stock"] = "reserve"
                    if maker_id: params["article"] = "maker"; params["article_id"] = maker_id
                    else: params["keyword"] = keyword
                    items = request_items(params); print(f"  query maker={maker['id']} keyword={keyword or '-'} maker_id={maker_id or '-'} offset={offset} stock={params.get('mono_stock','all')} items={len(items)}")
                    for item in items:
                        if not maker_matches(item, maker, search_keyword=keyword): continue
                        if maker["strict_idol"] and not is_takeshobo_idol(item): continue
                        key = item.get("product_id") or item.get("content_id") or item.get("URL")
                        if key: all_items[(maker["id"], key)] = (maker, item)
                    if len(items) < 100: break
                    offset += 100; time.sleep(0.1)
                time.sleep(0.2)
            cursor = window_end + timedelta(days=1)
    if not any(k[0] == "i-one" for k in all_items):
        print("  i-one DMM discovery returned 0; starting official catalog fallback"); discover_i_one_fallback(start, end, all_items)
    products = []
    for maker, item in all_items.values():
        title = str(item.get("title") or "").strip(); release_date = str(item.get("date") or "")[:10]; code = str(item.get("maker_product") or item.get("product_id") or item.get("content_id") or "").strip(); jan = re.sub(r"\D", "", str(item.get("jancode") or item.get("jan") or ""))
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date): continue
        media = sample_media(item)
        title_key = re.sub(r"[^a-z0-9]", "", re.sub(r"【.*?】|4Kあり", "", title).lower())
        old = existing.get(code, {}) or existing_by_norm_code.get(re.sub(r"[^a-z0-9]", "", code.lower()), {}) or existing_by_title.get(title_key, {})
        images = media["sample_image_urls"] or old.get("sample_image_urls") or []
        video = media["sample_video_url"] or old.get("sample_video_url") or ""
        affiliate_url = item.get("affiliateURL") or old.get("affiliate_url") or ""
        dmm_url = item.get("URL") or old.get("dmm_url") or ""
        products.append({"maker": maker["name"], "maker_id": maker["id"], "title": title, "release_date": release_date, "product_code": code, "jan": jan or old.get("jan", ""), "talent": talent_names(item) or old.get("talent") or [], "source_url": item.get("URL") or old.get("source_url") or "", "affiliate_url": affiliate_url, "dmm_url": dmm_url, "affiliate_match_status": "matched" if affiliate_url else "unmatched", "status": "upcoming" if release_date >= today.isoformat() else "released", "cover_image_url": media["cover_image_url"] or old.get("cover_image_url") or "", "sample_image_urls": images[:15], "sample_video_url": video, "sample_available": bool(video or old.get("sample_available")), "tags": [release_date[:4]+"年", release_date[:7]+"月", release_date[:7]+"発売", maker["name"]]})
    products.sort(key=lambda p: (p["release_date"], p["maker"], p["title"]), reverse=True); return products


def main():
    products = discover()
    if not products: raise RuntimeError("DMM discovery returned zero accepted products; refusing to overwrite existing data")
    OUT.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"dmm discovery products={len(products)}")
    for maker in MAKERS: print(f"  {maker['id']}: {sum(1 for p in products if p['maker_id'] == maker['id'])}")


if __name__ == "__main__": main()

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

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
        if item.get(key):
            names.append(str(item[key]))
    return names


def genre_names(item):
    names = iteminfo_names(item, "genre")
    for key in ("genre", "genres"):
        value = item.get(key)
        if isinstance(value, list):
            names.extend(str(x.get("name") if isinstance(x, dict) else x) for x in value)
        elif value:
            names.append(str(value))
    return names


def maker_matches(item, maker, search_keyword=None):
    hay = " ".join(maker_names(item))
    if any(norm(k) in norm(hay) or norm(hay) in norm(k) for k in maker["keywords"] if hay):
        return True
    # ItemList keyword search can match the manufacturer while iteminfo.maker is
    # represented by a different label/alias. In that case verify the exact search
    # keyword against the complete API item instead of rejecting the item solely
    # because the maker field uses an alias.
    if search_keyword:
        raw = norm(json.dumps(item, ensure_ascii=False))
        return bool(norm(search_keyword)) and norm(search_keyword) in raw
    return not hay and not maker["strict_idol"]


def is_takeshobo_idol(item):
    title = str(item.get("title") or "")
    if any(x in title for x in EXCLUDE_TITLE):
        return False
    return any(x in " ".join(genre_names(item)) for x in INCLUDE_GENRE)


def request_json(url, params):
    r = requests.get(url, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"DMM API HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def request_items(params):
    return request_json(ITEM_API_URL, params).get("result", {}).get("items", []) or []


def talent_names(item):
    out = []
    for key in ("actress", "actor", "author"):
        for name in iteminfo_names(item, key):
            name = re.sub(r"^[ー―–—-]+\s*", "", name).strip()
            if name and name not in out:
                out.append(name)
    return out


def find_dvd_floor_ids():
    data = request_json(FLOOR_API_URL, {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "output": "json"})
    found = []

    def walk(value, parent_text=""):
        if isinstance(value, dict):
            code = str(value.get("code") or value.get("floor_code") or "").lower()
            name = str(value.get("name") or value.get("floor_name") or "")
            fid = str(value.get("id") or value.get("floor_id") or "")
            context = f"{parent_text} {code} {name}".lower()
            if fid and (code in {"dvd", "mono-dvd", "monodvd"} or ("dvd" in context and ("mono" in context or "通販" in context))):
                if fid not in found:
                    found.append(fid)
            for v in value.values():
                walk(v, context)
        elif isinstance(value, list):
            for v in value:
                walk(v, parent_text)

    walk(data)
    print(f"  dvd floor ids: {found}")
    return found


def find_maker_ids(floor_ids, maker):
    found = {}
    for floor_id in floor_ids:
        offset = 1
        while offset <= 5000:
            try:
                data = request_json(MAKER_API_URL, {
                    "api_id": API_ID,
                    "affiliate_id": AFFILIATE_ID,
                    "site": SITE,
                    "floor_id": floor_id,
                    "hits": 100,
                    "offset": offset,
                    "output": "json",
                })
            except RuntimeError as exc:
                if "HTTP 400" in str(exc) and "Invalid Request Error" in str(exc):
                    print(f"  skip invalid MakerSearch floor_id={floor_id}")
                    break
                raise
            result = data.get("result", {}) or {}
            makers = result.get("makers") or result.get("maker") or []
            if isinstance(makers, dict):
                makers = makers.get("maker") or []
            if not makers:
                break
            for m in makers:
                mid = str(m.get("id") or m.get("maker_id") or "")
                name = str(m.get("name") or "")
                if mid and name and any(norm(k) in norm(name) or norm(name) in norm(k) for k in maker["keywords"]):
                    found[mid] = name
            if len(makers) < 100:
                break
            offset += 100
            time.sleep(0.1)
        time.sleep(0.1)
    return found


def discover():
    if not API_ID or not AFFILIATE_ID:
        raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    today = date.today()
    start = today - timedelta(days=30)
    end = today + timedelta(days=180)
    all_items = {}

    floor_ids = find_dvd_floor_ids()
    maker_ids = {}
    for maker in MAKERS:
        maker_ids[maker["id"]] = find_maker_ids(floor_ids, maker)
        print(f"  maker ids {maker['id']}: {maker_ids[maker['id']]}")

    for maker in MAKERS:
        ids = list(maker_ids.get(maker["id"], {}).keys())
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=30), end)
            queries = [(None, mid) for mid in ids]
            queries += [(keyword, None) for keyword in maker["keywords"]]
            seen_query_keys = set()
            for keyword, maker_id in queries:
                query_key = (keyword, maker_id)
                if query_key in seen_query_keys:
                    continue
                seen_query_keys.add(query_key)
                offset = 1
                while offset <= 5000:
                    params = {
                        "api_id": API_ID,
                        "affiliate_id": AFFILIATE_ID,
                        "site": SITE,
                        "service": "mono",
                        "floor": "dvd",
                        "gte_date": f"{cursor.isoformat()}T00:00:00",
                        "lte_date": f"{window_end.isoformat()}T23:59:59",
                        "sort": "date",
                        "hits": 100,
                        "offset": offset,
                        "output": "json",
                    }
                    if maker_id:
                        params["article"] = "maker"
                        params["article_id"] = maker_id
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
        title = str(item.get("title") or "").strip()
        release_date = str(item.get("date") or "")[:10]
        code = str(item.get("maker_product") or item.get("product_id") or item.get("content_id") or "").strip()
        jan = re.sub(r"\D", "", str(item.get("jancode") or item.get("jan") or ""))
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
            continue
        products.append({
            "maker": maker["name"], "maker_id": maker["id"], "title": title,
            "release_date": release_date, "product_code": code, "jan": jan,
            "talent": talent_names(item), "source_url": item.get("URL") or "",
            "affiliate_url": item.get("affiliateURL") or "", "dmm_url": item.get("URL") or "",
            "affiliate_match_status": "matched" if item.get("affiliateURL") else "unmatched",
            "status": "upcoming" if release_date >= today.isoformat() else "released",
            "tags": [release_date[:4] + "年", release_date[:7] + "月", release_date[:7] + "発売", maker["name"]],
        })
    products.sort(key=lambda p: (p["release_date"], p["maker"], p["title"]), reverse=True)
    return products


def main():
    products = discover()
    if not products:
        raise RuntimeError("DMM discovery returned zero accepted products; refusing to overwrite existing data")
    OUT.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"dmm discovery products={len(products)}")
    for maker in MAKERS:
        n = sum(1 for p in products if p["maker_id"] == maker["id"])
        print(f"  {maker['id']}: {n}")


if __name__ == "__main__":
    main()

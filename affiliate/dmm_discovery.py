from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

API_URL = os.getenv("DMM_API_URL", "https://api.dmm.com/affiliate/v3/ItemList")
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")
SITE = "FANZA"
OUT = Path(__file__).resolve().parents[1] / "data/products.json"

MAKERS = [
    {
        "id": "spice_visual",
        "name": "スパイスビジュアル",
        "keywords": ["スパイスビジュアル", "Spice Visual"],
        "strict_idol": False,
    },
    {
        "id": "i-one",
        "name": "ラインコミュニケーションズ / I-ONE",
        "keywords": ["ラインコミュニケーションズ", "I-ONE"],
        "strict_idol": False,
    },
    {
        "id": "takeshobo",
        "name": "竹書房",
        "keywords": ["竹書房"],
        "strict_idol": True,
    },
]

INCLUDE_GENRE = ("アイドル", "グラビア", "イメージ")
EXCLUDE_TITLE = ("写真集", "コミック", "漫画", "雑誌")


def norm(s: str) -> str:
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(s or "")).lower()


def flat_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from flat_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from flat_strings(v)


def iteminfo_names(item, key):
    info = item.get("iteminfo") or {}
    value = info.get(key)
    return [str(x.get("name") or x.get("value") or x.get("id") or "") for x in (value if isinstance(value, list) else [value]) if x]


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


def maker_matches(item, maker):
    hay = " ".join(maker_names(item)).lower()
    if not hay:
        # DMM keyword search is already constrained by the manufacturer keyword.
        # For non-竹書房 makers we allow the API result when maker metadata is absent.
        return not maker["strict_idol"]
    return any(norm(k) in norm(hay) or norm(hay) in norm(k) for k in maker["keywords"])


def is_takeshobo_idol(item):
    title = str(item.get("title") or "")
    if any(x in title for x in EXCLUDE_TITLE):
        return False
    genres = " ".join(genre_names(item))
    #竹書房 is intentionally strict: DVD + idol/gravure/image genre is required.
    return any(x in genres for x in INCLUDE_GENRE)


def request_items(params):
    r = requests.get(API_URL, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"DMM API HTTP {r.status_code}: {r.text[:300]}")
    return r.json().get("result", {}).get("items", []) or []


def talent_names(item):
    out = []
    for key in ("actress", "actor", "author"):
        for name in iteminfo_names(item, key):
            name = re.sub(r"^[ー―–—-]+\s*", "", name).strip()
            if name and name not in out:
                out.append(name)
    return out


def discover():
    if not API_ID or not AFFILIATE_ID:
        raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")

    today = date.today()
    start = today - timedelta(days=30)
    end = today + timedelta(days=180)
    all_items = {}

    for maker in MAKERS:
        # Split the period into monthly-ish windows so a busy manufacturer cannot
        # push upcoming releases out of the 100-item API page.
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=30), end)
            for keyword in maker["keywords"]:
                params = {
                    "api_id": API_ID,
                    "affiliate_id": AFFILIATE_ID,
                    "site": SITE,
                    "service": "mono",
                    "floor": "dvd",
                    "keyword": keyword,
                    "gte_date": f"{cursor.isoformat()}T00:00:00",
                    "lte_date": f"{window_end.isoformat()}T23:59:59",
                    "sort": "date",
                    "hits": 100,
                    "output": "json",
                }
                for item in request_items(params):
                    if not maker_matches(item, maker):
                        continue
                    if maker["strict_idol"] and not is_takeshobo_idol(item):
                        continue
                    key = item.get("product_id") or item.get("content_id") or item.get("URL")
                    if key:
                        all_items[(maker["id"], key)] = (maker, item)
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
            "maker": maker["name"],
            "maker_id": maker["id"],
            "title": title,
            "release_date": release_date,
            "product_code": code,
            "jan": jan,
            "talent": talent_names(item),
            "source_url": item.get("URL") or "",
            "affiliate_url": item.get("affiliateURL") or "",
            "dmm_url": item.get("URL") or "",
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

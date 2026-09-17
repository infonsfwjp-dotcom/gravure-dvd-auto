from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")


def urls(value):
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return [value]
    if isinstance(value, list):
        out = []
        for x in value:
            out.extend(urls(x))
        return out
    if isinstance(value, dict):
        out = []
        for x in value.values():
            out.extend(urls(x))
        return out
    return []


def unique(values, limit=None):
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
        if limit and len(out) >= limit:
            break
    return out


def extract_media(item):
    cover = urls(item.get("imageURL") or {})
    sample_images = urls(item.get("sampleImageURL") or {})

    sample_movies = []
    sample_movie = item.get("sampleMovieURL") or {}
    if isinstance(sample_movie, dict):
        for key in ("size_720_480", "size_644_414", "size_560_360", "size_476_306"):
            sample_movies.extend(urls(sample_movie.get(key)))
    sample_movies.extend(urls(sample_movie))

    return {
        "cover_image_url": unique(cover, 1)[0] if cover else "",
        "sample_image_urls": unique(sample_images, 12),
        "sample_video_url": unique(sample_movies, 1)[0] if sample_movies else "",
        "sample_available": bool(sample_movies),
    }


def item_blob(item):
    keys = ("maker_product", "product_id", "content_id", "cid", "title", "iteminfo")
    return " ".join(str(item.get(k) or "") for k in keys).lower()


def api_search(params, session):
    try:
        response = session.get(API_URL, params=params, timeout=15)
        if response.status_code >= 400:
            return []
        return response.json().get("result", {}).get("items", []) or []
    except Exception:
        return []


def search(product, session):
    code = str(product.get("product_code") or "").strip()
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    dmm_url = str(product.get("dmm_url") or product.get("source_url") or "")
    cid_match = re.search(r"cid=([A-Za-z0-9_-]+)", dmm_url, re.I)
    cid = cid_match.group(1) if cid_match else ""

    base = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "service": "mono",
        "floor": "dvd",
        "hits": 20,
        "offset": 1,
        "output": "json",
    }

    searches = []
    if cid:
        searches.append({**base, "cid": cid})
    if code:
        searches.append({**base, "keyword": code})
    if title and talent:
        searches.append({**base, "keyword": f"{title} {talent}"})
    elif title:
        searches.append({**base, "keyword": title})

    candidates = []
    seen = set()
    for params in searches:
        for item in api_search(params, session):
            key = str(item.get("product_id") or item.get("content_id") or item.get("cid") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            candidates.append(item)

    if not candidates:
        return None

    code_l = code.lower()
    cid_l = cid.lower()
    title_l = title.lower()
    talent_l = talent.lower()

    # Prefer exact product-code/CID matches so broad keyword fallback cannot
    # attach sample media from a different DVD.
    for item in candidates:
        blob = item_blob(item)
        if code_l and code_l in blob:
            return item
        if cid_l and cid_l in blob:
            return item

    # If FANZA does not expose the code/CID in searchable fields, require a
    # strong title match, optionally reinforced by the model name.
    for item in candidates:
        blob = item_blob(item)
        if title_l and title_l in blob and (not talent_l or talent_l in blob):
            return item

    return None


def main():
    if not API_ID or not AFFILIATE_ID or not DATA.exists():
        return

    products = json.loads(DATA.read_text(encoding="utf-8"))
    today = date.today()
    changed = 0
    checked = 0
    session = requests.Session()
    session.headers.update({"User-Agent": "gravure-dvd-auto/1.0"})

    for product in products:
        if product.get("sample_available") and product.get("sample_video_url"):
            continue
        release_raw = str(product.get("release_date") or "")
        try:
            release = date.fromisoformat(release_raw)
        except ValueError:
            continue
        if release < today - timedelta(days=60) or release > today + timedelta(days=120):
            continue

        item = search(product, session)
        checked += 1
        if item:
            media = extract_media(item)
            before = (
                product.get("cover_image_url"),
                tuple(product.get("sample_image_urls") or []),
                product.get("sample_video_url"),
                product.get("sample_available"),
            )
            if media["cover_image_url"]:
                product["cover_image_url"] = media["cover_image_url"]
            product["sample_image_urls"] = media["sample_image_urls"]
            product["sample_video_url"] = media["sample_video_url"]
            product["sample_available"] = media["sample_available"]
            after = (
                product.get("cover_image_url"),
                tuple(product.get("sample_image_urls") or []),
                product.get("sample_video_url"),
                product.get("sample_available"),
            )
            if before != after:
                changed += 1
        time.sleep(0.10)

    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sample enrichment checked={checked} changed={changed}")


if __name__ == "__main__":
    main()

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
    sample_images = []
    sample_movies = []
    cover = []

    image_data = item.get("imageURL") or {}
    cover.extend(urls(image_data))

    sample_image = item.get("sampleImageURL") or {}
    sample_images.extend(urls(sample_image))

    sample_movie = item.get("sampleMovieURL") or {}
    # Prefer the largest standard DMM player URL when available.
    for key in ("size_720_480", "size_644_414", "size_560_360", "size_476_306"):
        value = sample_movie.get(key) if isinstance(sample_movie, dict) else None
        if value:
            sample_movies.extend(urls(value))
    if not sample_movies:
        sample_movies.extend(urls(sample_movie))

    return {
        "cover_image_url": unique(cover, 1)[0] if cover else "",
        "sample_image_urls": unique(sample_images, 12),
        "sample_video_url": unique(sample_movies, 1)[0] if sample_movies else "",
        "sample_available": bool(sample_movies),
    }


def search(product):
    code = str(product.get("product_code") or "").strip()
    dmm_url = str(product.get("dmm_url") or product.get("source_url") or "")
    cid_match = re.search(r"cid=([A-Za-z0-9_-]+)", dmm_url, re.I)
    params = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "service": "mono",
        "floor": "dvd",
        "hits": 20,
        "offset": 1,
        "output": "json",
    }
    if cid_match:
        params["cid"] = cid_match.group(1)
    elif code:
        params["keyword"] = code
    else:
        return None
    try:
        response = requests.get(API_URL, params=params, timeout=15)
        if response.status_code >= 400:
            return None
        items = response.json().get("result", {}).get("items", []) or []
    except Exception:
        return None
    if not items:
        return None
    target = code.lower()
    for item in items:
        blob = " ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid")).lower()
        if target and target in blob:
            return item
    return items[0]


def main():
    if not API_ID or not AFFILIATE_ID or not DATA.exists():
        return
    products = json.loads(DATA.read_text(encoding="utf-8"))
    today = date.today()
    changed = 0
    checked = 0
    for product in products:
        if product.get("sample_available") and product.get("sample_video_url"):
            continue
        release_raw = str(product.get("release_date") or "")
        try:
            release = date.fromisoformat(release_raw)
        except ValueError:
            continue
        # Focus on recent and near-future releases; sample media is often published shortly before release.
        if release < today - timedelta(days=60) or release > today + timedelta(days=120):
            continue
        item = search(product)
        checked += 1
        if item:
            media = extract_media(item)
            before = (product.get("cover_image_url"), tuple(product.get("sample_image_urls") or []), product.get("sample_video_url"), product.get("sample_available"))
            if media["cover_image_url"]:
                product["cover_image_url"] = media["cover_image_url"]
            product["sample_image_urls"] = media["sample_image_urls"]
            product["sample_video_url"] = media["sample_video_url"]
            product["sample_available"] = media["sample_available"]
            after = (product.get("cover_image_url"), tuple(product.get("sample_image_urls") or []), product.get("sample_video_url"), product.get("sample_available"))
            if before != after:
                changed += 1
        time.sleep(0.15)
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sample enrichment checked={checked} changed={changed}")


if __name__ == "__main__":
    main()

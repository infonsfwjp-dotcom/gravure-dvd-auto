from __future__ import annotations

import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
API_ID = os.environ["DMM_API_ID"]
AFFILIATE_ID = os.environ["DMM_AFFILIATE_ID"]
CID = "n_691lcdv41448"


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
    for v in values:
        if v and v not in out:
            out.append(v)
        if limit and len(out) >= limit:
            break
    return out


session = requests.Session()
session.headers["User-Agent"] = "gravure-dvd-auto/1.0"
params = {
    "api_id": API_ID,
    "affiliate_id": AFFILIATE_ID,
    "site": "FANZA",
    "service": "mono",
    "floor": "dvd",
    "cid": CID,
    "hits": 20,
    "offset": 1,
    "output": "json",
}
response = session.get(API_URL, params=params, timeout=20)
response.raise_for_status()
items = response.json().get("result", {}).get("items", []) or []

item = None
for candidate in items:
    blob = json.dumps(candidate, ensure_ascii=False).lower()
    if CID in blob or "lcdv41448" in blob:
        item = candidate
        break
if item is None:
    raise RuntimeError(f"DMM/FANZA exact CID not found: {CID}")

image_data = item.get("imageURL") or {}
sample_data = item.get("sampleImageURL") or {}
movie_data = item.get("sampleMovieURL") or {}

cover = []
for key in ("large", "list", "small"):
    cover.extend(urls(image_data.get(key)))
cover.extend(urls(image_data))

images = []
for key in ("sample_l", "sample_s"):
    value = sample_data.get(key) if isinstance(sample_data, dict) else None
    if isinstance(value, dict):
        images.extend(urls(value.get("image")))
    else:
        images.extend(urls(value))
images.extend(urls(sample_data))

movies = []
for key in ("size_720_480", "size_644_414", "size_560_360", "size_476_306"):
    movies.extend(urls(movie_data.get(key) if isinstance(movie_data, dict) else None))
movies.extend(urls(movie_data))

products = json.loads(DATA.read_text(encoding="utf-8"))
target = next((p for p in products if p.get("product_code") == "LCDV-41448"), None)
if target is None:
    raise RuntimeError("LCDV-41448 is missing from products.json")

if cover:
    target["cover_image_url"] = unique(cover, 1)[0]
if images:
    target["sample_image_urls"] = unique(images, 15)
if movies:
    target["sample_video_url"] = unique(movies, 1)[0]
    target["sample_available"] = True

if item.get("affiliateURL"):
    target["affiliate_url"] = item["affiliateURL"]
if item.get("URL"):
    target["dmm_url"] = item["URL"]
if item.get("title"):
    target["title"] = item["title"]
if item.get("date"):
    target["release_date"] = str(item["date"])[:10]
if item.get("maker_product"):
    target["product_code"] = item["maker_product"]
if item.get("jancode") or item.get("jan"):
    target["jan"] = "".join(ch for ch in str(item.get("jancode") or item.get("jan")) if ch.isdigit())

DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"LCDV-41448 refreshed: images={len(target.get('sample_image_urls') or [])} video={bool(target.get('sample_video_url'))}")

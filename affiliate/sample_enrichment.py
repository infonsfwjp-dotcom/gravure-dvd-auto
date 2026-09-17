from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")
TAKESHobo_SITE = "https://idol-gakuen.jp/"


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
    cid_match = re.search(r"cid=([^/?&#]+)", dmm_url, re.I)
    cid = cid_match.group(1) if cid_match else ""

    common = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "hits": 100,
        "offset": 1,
        "output": "json",
    }

    catalogs = [
        {"service": "mono", "floor": "dvd"},
        {"service": "digital", "floor": "videoa"},
        {},
    ]
    terms = []
    if cid:
        terms.append({"cid": cid})
    if code:
        terms.append({"keyword": code})
    if title and talent:
        terms.append({"keyword": f"{title} {talent}"})
    elif title:
        terms.append({"keyword": title})

    candidates = []
    seen = set()
    for catalog in catalogs:
        for term in terms:
            params = {**common, **catalog, **term}
            for item in api_search(params, session):
                key = str(item.get("product_id") or item.get("content_id") or item.get("cid") or "")
                dedupe = (key, str(item.get("service_code") or catalog.get("service") or ""))
                if key and dedupe in seen:
                    continue
                if key:
                    seen.add(dedupe)
                candidates.append(item)

    if not candidates:
        return None

    code_l = code.lower()
    cid_l = cid.lower()
    title_l = title.lower()
    talent_l = talent.lower()

    exact = []
    for item in candidates:
        blob = item_blob(item)
        if (code_l and code_l in blob) or (cid_l and cid_l in blob):
            exact.append(item)
    for item in exact:
        media = extract_media(item)
        if media["sample_video_url"]:
            return item
    if exact:
        return exact[0]

    strong = []
    for item in candidates:
        blob = item_blob(item)
        if title_l and title_l in blob and (not talent_l or talent_l in blob):
            strong.append(item)
    for item in strong:
        media = extract_media(item)
        if media["sample_video_url"]:
            return item
    return strong[0] if strong else None


def _html_urls(value):
    value = html.unescape(value or "").replace("\\/", "/")
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("http://", "https://")):
        return value
    return ""


def takeshobo_public_sample(product, session):
    """Fallback for 竹書房's official Idol Gakuen site.

    The official site exposes product pages with a native <video> element.
    We only keep the public video/image URLs; media is not downloaded or
    re-hosted by this project.
    """
    if product.get("maker_id") != "takeshobo":
        return {}

    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    code = str(product.get("product_code") or "").strip()
    queries = [q for q in (code, talent, title) if q]
    item_urls = []
    seen = set()

    for query in queries[:3]:
        try:
            search_url = urljoin(TAKESHobo_SITE, "?s=" + quote_plus(query))
            response = session.get(search_url, timeout=15)
            if response.status_code >= 400:
                continue
            links = re.findall(r'href=["\']([^"\']*/item/\d+/[^"\']*)["\']', response.text, re.I)
            for link in links:
                absolute = urljoin(search_url, html.unescape(link))
                if absolute not in seen:
                    seen.add(absolute)
                    item_urls.append(absolute)
        except Exception:
            continue

    title_l = re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龥ー]", "", title).lower()
    talent_l = re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龥ー]", "", talent).lower()

    for item_url in item_urls[:12]:
        try:
            response = session.get(item_url, timeout=15)
            if response.status_code >= 400:
                continue
            source = html.unescape(response.text)
            normalized = re.sub(r"[^0-9a-zA-Zぁ-んァ-ン一-龥ー]", "", source).lower()
            if title_l and title_l not in normalized and talent_l and talent_l not in normalized:
                continue

            videos = []
            for match in re.findall(r"<(?:video|source)[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']", source, re.I):
                u = _html_urls(match)
                if u:
                    videos.append(u)
            posters = []
            for match in re.findall(r"<(?:video|source)[^>]+poster=[\"']([^\"']+)[\"']", source, re.I):
                u = _html_urls(match)
                if u:
                    posters.append(u)
            images = []
            for match in re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', source, re.I):
                u = _html_urls(match)
                if u and "/wp-content/" in u:
                    images.append(u)

            videos = unique(videos, 1)
            if videos:
                return {
                    "sample_video_url": videos[0],
                    "sample_image_urls": unique(posters + images, 12),
                    "sample_available": True,
                    "sample_source_url": item_url,
                }
        except Exception:
            continue
    return {}


def main():
    if not API_ID or not AFFILIATE_ID or not DATA.exists():
        return

    products = json.loads(DATA.read_text(encoding="utf-8"))
    today = date.today()
    changed = 0
    checked = 0
    public_checked = 0
    public_changed = 0
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

        before = (
            product.get("cover_image_url"),
            tuple(product.get("sample_image_urls") or []),
            product.get("sample_video_url"),
            product.get("sample_available"),
        )

        item = search(product, session)
        checked += 1
        if item:
            media = extract_media(item)
            if media["cover_image_url"]:
                product["cover_image_url"] = media["cover_image_url"]
            if media["sample_image_urls"]:
                product["sample_image_urls"] = media["sample_image_urls"]
            if media["sample_video_url"]:
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True

        # FANZA API can expose sample images while omitting sampleMovieURL.
        # For 竹書房, the official Idol Gakuen site is a second public-source
        # fallback and can expose the native sample video directly.
        if not (product.get("sample_available") and product.get("sample_video_url")) and product.get("maker_id") == "takeshobo":
            public_checked += 1
            public = takeshobo_public_sample(product, session)
            if public.get("sample_video_url"):
                product["sample_video_url"] = public["sample_video_url"]
                product["sample_available"] = True
                if public.get("sample_image_urls"):
                    product["sample_image_urls"] = public["sample_image_urls"]
                if public.get("sample_source_url"):
                    product["sample_source_url"] = public["sample_source_url"]
                public_changed += 1

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
    print(f"sample enrichment checked={checked} changed={changed} public_takeshobo_checked={public_checked} public_takeshobo_changed={public_changed}")


if __name__ == "__main__":
    main()

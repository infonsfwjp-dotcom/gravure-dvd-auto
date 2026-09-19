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
IONE_TV = "https://i-one.tv/"


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
    image_data = item.get("imageURL") or {}
    sample_data = item.get("sampleImageURL") or {}

    # Prefer the largest FANZA/DMM image variants. The API can expose both
    # sample_s and sample_l; walking the dict recursively can otherwise put
    # the small thumbnails first and make the mobile gallery look blurry.
    covers = []
    if isinstance(image_data, dict):
        for key in ("large", "list", "small"):
            covers.extend(urls(image_data.get(key)))
    covers.extend(urls(image_data))

    images = []
    if isinstance(sample_data, dict):
        for key in ("sample_l", "sample_s"):
            value = sample_data.get(key)
            if isinstance(value, dict):
                images.extend(urls(value.get("image")))
            else:
                images.extend(urls(value))
    images.extend(urls(sample_data))

    movies = []
    sample_movie = item.get("sampleMovieURL") or {}
    if isinstance(sample_movie, dict):
        for key in ("size_720_480", "size_644_414", "size_560_360", "size_476_306"):
            movies.extend(urls(sample_movie.get(key)))
    movies.extend(urls(sample_movie))

    return {
        "cover_image_url": unique(covers, 1)[0] if covers else "",
        "sample_image_urls": unique(images, 12),
        "sample_video_url": unique(movies, 1)[0] if movies else "",
        "sample_available": bool(movies),
    }

def item_blob(item):
    return " ".join(
        str(item.get(k) or "")
        for k in ("maker_product", "product_id", "content_id", "cid", "title", "iteminfo")
    ).lower()


def api_search(params, session):
    try:
        response = session.get(API_URL, params=params, timeout=15)
        if response.status_code >= 400:
            return []
        return response.json().get("result", {}).get("items", []) or []
    except Exception:
        return []


def fanza_search(product, session):
    code = str(product.get("product_code") or "").strip()
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    source = str(product.get("dmm_url") or product.get("source_url") or "")
    match = re.search(r"cid=([^/?&#]+)", source, re.I)
    cid = match.group(1) if match else ""

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

    candidates, seen = [], set()
    for catalog in catalogs:
        for term in terms:
            for item in api_search({**common, **catalog, **term}, session):
                key = str(item.get("product_id") or item.get("content_id") or item.get("cid") or "")
                dedupe = (key, str(item.get("service_code") or catalog.get("service") or ""))
                if key and dedupe in seen:
                    continue
                if key:
                    seen.add(dedupe)
                candidates.append(item)

    if not candidates:
        return None

    code_l, cid_l = code.lower(), cid.lower()
    title_l, talent_l = title.lower(), talent.lower()
    exact = [
        item for item in candidates
        if (code_l and code_l in item_blob(item)) or (cid_l and cid_l in item_blob(item))
    ]
    for item in exact:
        if extract_media(item)["sample_video_url"]:
            return item
    if exact:
        return exact[0]

    strong = [
        item for item in candidates
        if title_l and title_l in item_blob(item) and (not talent_l or talent_l in item_blob(item))
    ]
    for item in strong:
        if extract_media(item)["sample_video_url"]:
            return item
    return strong[0] if strong else None


def _abs_url(value, base):
    value = html.unescape(value or "").replace("\\/", "/").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    return urljoin(base, value)


def public_page_media(source, base_url):
    source = html.unescape(source).replace("\\/", "/")
    videos = []

    # I-ONE may place the sample MP4 URL in inline JavaScript rather than a
    # literal <video>/<source> element. Capture both forms.
    patterns = (
        r'<(?:video|source)[^>]+(?:src|data-src)=["\']([^"\']+)["\']',
        r'https?://(?:www\.)?(?:youtube\.com/embed/|youtu\.be/)[^"\'<> ]+',
        r'https?://[^"\'<> ]+\.(?:mp4|m3u8)(?:\?[^"\'<> ]*)?',
    )
    for pattern in patterns:
        for match in re.findall(pattern, source, re.I):
            value = match if isinstance(match, str) else match[0]
            value = _abs_url(value, base_url)
            if value:
                videos.append(value)

    images = []
    for match in re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', source, re.I):
        value = _abs_url(match, base_url)
        if value and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", value, re.I):
            images.append(value)

    # Some pages expose image URLs only inside JSON/JS data.
    for match in re.findall(r'https?://[^"\'<> ]+\.(?:jpe?g|png|webp)(?:\?[^"\'<> ]*)?', source, re.I):
        value = _abs_url(match, base_url)
        if value:
            images.append(value)

    return unique(videos, 3), unique(images, 12)

def ione_public_sample(product, session):
    if product.get("maker_id") != "i-one":
        return {}
    code = str(product.get("product_code") or "").strip()
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    candidates = []
    if code:
        candidates.append(f"{IONE_TV}content/detail/?id={quote_plus(code)}")

    # Search only the official catalog as a fallback when the exact code page
    # cannot be reached. A candidate still has to match title/talent.
    for query in (f"{title} {talent}".strip(), title):
        if not query:
            continue
        try:
            response = session.get(IONE_TV + "content/", params={"s": query}, timeout=15)
            if response.status_code < 400:
                candidates.extend(
                    urljoin(IONE_TV, html.unescape(x))
                    for x in re.findall(r'href=["\']([^"\']*/content/detail/\?id=[^"\']+)["\']', response.text, re.I)[:10]
                )
        except Exception:
            pass

    title_l = re.sub(r"\s+", "", title).lower()
    talent_l = re.sub(r"\s+", "", talent).lower()
    seen = set()
    for page_url in candidates:
        if page_url in seen:
            continue
        seen.add(page_url)
        try:
            response = session.get(page_url, timeout=15)
            if response.status_code >= 400:
                continue
            source = response.text
            normalized = re.sub(r"\s+", "", html.unescape(source)).lower()
            if code and code.lower() not in normalized:
                # Exact-code pages are preferred; do not accept an unrelated
                # official page merely because the search engine matched it.
                if title_l and title_l not in normalized:
                    continue
                if talent_l and talent_l not in normalized:
                    continue
            if "無料サンプル動画" not in normalized and "サンプル動画" not in normalized:
                continue
            videos, images = public_page_media(source, page_url)
            if videos:
                return {
                    "sample_video_url": videos[0],
                    "sample_image_urls": images,
                    "sample_available": True,
                    "sample_source_url": page_url,
                }
        except Exception:
            continue
    return {}


def smashtv_public_sample(product, session):
    """Find official SmashTV sample media for Spice Visual products."""
    if product.get("maker_id") != "spice_visual":
        return {}
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    if not title:
        return {}
    queries = [title]
    if talent:
        queries.append(f"{title} {talent}")
    candidates = []
    seen = set()
    for query in queries:
        try:
            response = session.get("https://smashtv.jp/", params={"s": query}, timeout=15)
            if response.status_code < 400:
                candidates.extend(urljoin("https://smashtv.jp/", html.unescape(x)) for x in re.findall(r"href=['\"]([^'\"]+)['\"]", response.text, re.I) if "/works/" in x)
        except Exception:
            pass
    if not candidates:
        for base_path, page_count in (("/works/", 36), ("/movie/", 23)):
            for page in range(1, page_count + 1):
                url = f"https://smashtv.jp{base_path}" if page == 1 else f"https://smashtv.jp{base_path}page/{page}/"
                try:
                    response = session.get(url, timeout=15)
                    if response.status_code >= 400:
                        continue
                    source = html.unescape(response.text)
                    normalized_page = re.sub(r"\\s+", "", source)
                    if title.replace(" ", "") not in normalized_page and talent.replace(" ", "") not in normalized_page:
                        continue
                    for link in re.findall(r"href=['\"]([^'\"]+)['\"]", source, re.I):
                        absolute = urljoin(url, link)
                        if base_path in absolute and absolute.rstrip("/") != f"https://smashtv.jp{base_path.rstrip('/')}":
                            candidates.append(absolute)
                except Exception:
                    continue
    title_l = re.sub(r"\s+", "", title).lower()
    talent_l = re.sub(r"\s+", "", talent).lower()
    for page_url in unique(candidates, 20):
        if page_url in seen or page_url.rstrip("/") == "https://smashtv.jp/works":
            continue
        seen.add(page_url)
        try:
            response = session.get(page_url, timeout=15)
            if response.status_code >= 400:
                continue
            source = html.unescape(response.text)
            normalized = re.sub(r"\s+", "", source).lower()
            if title_l and title_l not in normalized:
                continue
            if talent_l and talent_l not in normalized:
                continue
            videos, images = public_page_media(source, page_url)
            if not videos:
                for link in re.findall(r"href=['\"]([^'\"]+)['\"]", source, re.I):
                    absolute = _abs_url(link, page_url)
                    if "smashtv.jp" in absolute and ("sample" in absolute.lower() or "movie" in absolute.lower()):
                        try:
                            sub = session.get(absolute, timeout=15)
                            if sub.status_code < 400:
                                v2, i2 = public_page_media(html.unescape(sub.text), absolute)
                                videos.extend(v2); images.extend(i2)
                                if videos:
                                    break
                        except Exception:
                            continue
            if videos:
                return {"sample_video_url": videos[0], "sample_image_urls": unique(images, 12), "sample_available": True, "sample_source_url": page_url}
        except Exception:
            continue
    return {}

def takeshobo_public_sample(product, session):
    if product.get("maker_id") != "takeshobo":
        return {}
    code = str(product.get("product_code") or "").strip().lower()
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    queries = [q for q in (code, talent, title) if q]
    candidates = []
    seen = set()
    for query in queries[:3]:
        try:
            search_url = urljoin(TAKESHobo_SITE, "?s=" + quote_plus(query))
            response = session.get(search_url, timeout=15)
            if response.status_code >= 400:
                continue
            for link in re.findall(r'href=["\']([^"\']*/item/\d+/[^"\']*)["\']', response.text, re.I):
                absolute = urljoin(search_url, html.unescape(link))
                if absolute not in seen:
                    seen.add(absolute)
                    candidates.append(absolute)
        except Exception:
            continue

    title_l = re.sub(r"\s+", "", title).lower()
    talent_l = re.sub(r"\s+", "", talent).lower()
    for page_url in candidates[:12]:
        try:
            response = session.get(page_url, timeout=15)
            if response.status_code >= 400:
                continue
            source = html.unescape(response.text)
            normalized = re.sub(r"\s+", "", source).lower()
            # The previous implementation accepted a page when only one of
            # title/talent matched, which caused unrelated videos to attach.
            # Require the exact product code, or both title and talent.
            if code:
                if code not in normalized:
                    continue
            else:
                if not title_l or title_l not in normalized:
                    continue
                if talent_l and talent_l not in normalized:
                    continue
            videos, images = public_page_media(source, page_url)
            if videos:
                return {
                    "sample_video_url": videos[0],
                    "sample_image_urls": images,
                    "sample_available": True,
                    "sample_source_url": page_url,
                }
        except Exception:
            continue
    return {}


def clear_stale_takeshobo_sample(product):
    """Remove media written by the old unsafe official-site matcher."""
    if product.get("maker_id") != "takeshobo":
        return
    source = str(product.get("sample_source_url") or "")
    if source.startswith(TAKESHobo_SITE):
        product["sample_image_urls"] = []
        product["sample_video_url"] = ""
        product["sample_available"] = False
        product.pop("sample_source_url", None)


def main():
    if not API_ID or not AFFILIATE_ID or not DATA.exists():
        return

    products = json.loads(DATA.read_text(encoding="utf-8"))
    today = date.today()
    changed = checked = 0
    ione_checked = ione_changed = 0
    takeshobo_checked = takeshobo_changed = 0
    session = requests.Session()
    session.headers.update({"User-Agent": "gravure-dvd-auto/1.0"})

    for product in products:
        clear_stale_takeshobo_sample(product)
        if product.get("sample_available") and product.get("sample_video_url"):
            continue
        try:
            release = date.fromisoformat(str(product.get("release_date") or ""))
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

        item = fanza_search(product, session)
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

        if not product.get("sample_video_url") and product.get("maker_id") == "i-one":
            ione_checked += 1
            media = ione_public_sample(product, session)
            if media.get("sample_video_url"):
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True
                if media.get("sample_image_urls"):
                    product["sample_image_urls"] = media["sample_image_urls"]
                product["sample_source_url"] = media.get("sample_source_url", "")
                ione_changed += 1

        if not product.get("sample_video_url") and product.get("maker_id") == "spice_visual":
            media = smashtv_public_sample(product, session)
            if media.get("sample_video_url"):
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True
                if media.get("sample_image_urls"):
                    product["sample_image_urls"] = media["sample_image_urls"]
                product["sample_source_url"] = media.get("sample_source_url", "")

        if not product.get("sample_video_url") and product.get("maker_id") == "takeshobo":
            takeshobo_checked += 1
            media = takeshobo_public_sample(product, session)
            if media.get("sample_video_url"):
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True
                if media.get("sample_image_urls"):
                    product["sample_image_urls"] = media["sample_image_urls"]
                product["sample_source_url"] = media.get("sample_source_url", "")
                takeshobo_changed += 1

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
    print(
        f"sample enrichment checked={checked} changed={changed} "
        f"public_ione_checked={ione_checked} public_ione_changed={ione_changed} "
        f"public_takeshobo_checked={takeshobo_checked} public_takeshobo_changed={takeshobo_changed}"
    )


if __name__ == "__main__":
    main()

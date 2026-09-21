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
        "sample_image_urls": unique(images),
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
        r'<iframe[^>]+(?:src|data-src)=["\']([^"\']+)["\']',
        r'<embed[^>]+(?:src|data-src)=["\']([^"\']+)["\']',
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

    # I-ONE puts full-size sample image URLs on surrounding <a href> links
    # while the <img> tags may expose only one lazy-loaded thumbnail.
    for match in re.findall(r'<a[^>]+href=["\\']([^"\\']+)["\\']', source, re.I):
        value = _abs_url(match, base_url)
        if value and re.search(r"/images/sample/.*\\.(?:jpe?g|png|webp)(?:\\?|$)", value, re.I):
            images.append(value)

    # Some pages expose image URLs only inside JSON/JS data.
    for match in re.findall(r'https?://[^"\'<> ]+\.(?:jpe?g|png|webp)(?:\?[^"\'<> ]*)?', source, re.I):
        value = _abs_url(match, base_url)
        if value:
            images.append(value)

    return unique(videos, 3), unique(images)


def filter_ione_images(images, code):
    """Keep product-page sample/gallery images without accepting site-wide assets.

    The official I-ONE detail page is already opened by exact product code.
    Therefore the image URLs do not always repeat the code in their path.
    """
    code_l = str(code or "").strip().lower()
    if not code_l:
        return []
    blocked = ("logo", "icon", "favicon", "header", "footer", "banner", "bnr", "sns", "social", "arrow", "loading", "dummy", "background", "bg_")
    kept = []
    for image in images or []:
        value = str(image or "").strip()
        low = value.lower()
        if not low:
            continue
        path = low.split("?", 1)[0]
        name = path.rsplit("/", 1)[-1]
        if any(token in name for token in blocked):
            continue
        # I-ONE's key/jacket images are product art, not sample frames.
        # The sample gallery must use only the official /images/sample/ path.
        if "/images/sample/" in path:
            kept.append(value)
            continue
    return unique(kept)
def discover_ione_sample_frames(product, session):
    """Discover every contiguous official I-ONE sample frame, not just the first 12."""
    if product.get("maker_id") != "i-one":
        return []
    code = str(product.get("product_code") or "").strip()
    m = re.match(r"^(LCDV)-(\d+)$", code, re.I)
    if not m:
        return []
    series = f"{m.group(1)}-{m.group(2)[:2]}"
    out = []
    misses = 0
    # I-ONE sample galleries are numbered sequentially. Continue through a
    # short gap so late-numbered frames are still found, while bounding the
    # number of network probes per product.
    for n in range(1, 61):
        found = False
        for ext in ("jpg", "jpeg", "png", "webp"):
            image = f"https://file.i-one.tv/images/sample/{series}/{code}/{n:03d}.{ext}"
            try:
                response = session.get(image, timeout=2)
                if response.status_code == 200 and len(response.content) > 1024:
                    out.append(image)
                    found = True
                    break
            except Exception:
                pass
        if found:
            misses = 0
        else:
            misses += 1
            if misses >= 5:
                break
    return unique(out)


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
            images = filter_ione_images(images, code)

            # Probe the official numbered sample gallery as well. The detail
            # page often exposes only key/jacket/001 in HTML even though more
            # product-specific sample frames are available at the same path.
            numbered = []
            if code:
                prefix = code.upper()
                digits = prefix.split("-", 1)[1] if "-" in prefix else ""
                bucket = f"LCDV-{digits[:2]}" if digits else prefix
                base = f"https://file.i-one.tv/images/sample/{bucket}/{prefix}/"
                for number in range(1, 13):
                    image_url = f"{base}{number:03d}.jpg"
                    try:
                        probe = session.get(image_url, timeout=3)
                        if probe.status_code == 200 and len(probe.content) > 1024:
                            numbered.append(image_url)
                    except Exception:
                        continue
            images = unique(numbered or images, 12)
            if videos or images:
                return {
                    "sample_video_url": videos[0] if videos else "",
                    "sample_image_urls": images,
                    "sample_available": bool(videos),
                    "sample_source_url": page_url,
                }
        except Exception:
            continue
    return {}




def tokyolily_public_sample(product, session):
    """Fallback sample gallery source for I-ONE titles."""
    if product.get("maker_id") != "i-one":
        return {}
    jan = str(product.get("jan") or "").strip()
    code = str(product.get("product_code") or "").strip()
    title = str(product.get("title") or "").strip()
    candidates = []
    if jan:
        candidates.append(f"https://tokyolily.jp/products/{jan}_video")
    # Some I-ONE records have no JAN. Search TokyoLily by exact product code
    # and title, then only accept a page whose content matches this product.
    for query in (code, title.split("/", 1)[0].strip(), title):
        if not query:
            continue
        try:
            response = session.get("https://tokyolily.jp/", params={"s": query}, timeout=20)
            if response.status_code >= 400:
                continue
            for link in re.findall(r'href=[\"\']([^"\']+_video)[\"\']', response.text, re.I):
                absolute = urljoin("https://tokyolily.jp/", html.unescape(link))
                if absolute not in candidates:
                    candidates.append(absolute)
        except Exception:
            pass
    for page_url in candidates[:10]:
        try:
            response = session.get(page_url, timeout=20)
            if response.status_code >= 400:
                continue
            source = html.unescape(response.text).replace("\\/","/")
            normalized = re.sub(r"\s+", "", source).lower()
            code_ok = bool(code and code.lower() in normalized)
            title_key = re.sub(r"\s+", "", title.split("/", 1)[0]).lower()
            title_ok = bool(title_key and title_key in normalized)
            if not code_ok and not title_ok:
                continue
            marker = re.search(r"サンプル動画", source, re.I)
            gallery_source = source[:marker.start()] if marker else source
            images = []
            for match in re.findall(r'<img[^>]+(?:src|data-src|data-original)=[\"\']([^\"\']+)[\"\']', gallery_source, re.I):
                value = _abs_url(match, page_url)
                if value and re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", value, re.I):
                    images.append(value)
            images = unique(images)
            images = [x for x in images if not re.search(r"(?:logo|icon|loading|avatar|banner|button|sprite)", x, re.I)]
            if images:
                return {"sample_image_urls": images[:12], "sample_available": bool(product.get("sample_video_url")), "sample_source_url": page_url}
        except Exception:
            continue
    return {}

def smashtv_public_sample(product, session):
    """Find official SmashTV sample media for Spice Visual products."""
    if product.get("maker_id") != "spice_visual":
        return {}
    title = str(product.get("title") or "").strip()
    talent = " ".join(str(x) for x in (product.get("talent") or []) if x)
    # Some FANZA records encode the performer after a slash in the title
    # (e.g. 「恋色どみねーと！/三好双葉」) while the talent field is empty.
    # SmashTV publishes the same work as separate title/performer text.
    work_title = title.split("/", 1)[0].strip() if "/" in title else title
    title_talent = title.split("/", 1)[1].strip() if "/" in title else ""
    if not talent and title_talent:
        talent = title_talent
    if not work_title:
        return {}
    queries = [work_title]
    if talent:
        queries.append(f"{work_title} {talent}")
    candidates = []
    seen = set()

    # SmashTV is WordPress-backed. Its public REST search endpoint is more
    # reliable than crawling all 36 work pages and can surface newly published
    # work pages before search-engine indexes catch up.
    for query in queries:
        try:
            response = session.get(
                "https://smashtv.jp/wp-json/wp/v2/search",
                params={"search": query, "per_page": 20},
                timeout=15,
            )
            if response.status_code < 400:
                for result in response.json() or []:
                    value = str(result.get("url") or "").strip()
                    if "/works/" in value and value not in seen:
                        seen.add(value)
                        candidates.append(value)
        except Exception:
            pass

    # Also try the site's normal search page as a fallback.
    for query in queries:
        try:
            response = session.get("https://smashtv.jp/", params={"s": query}, timeout=15)
            if response.status_code < 400:
                for value in re.findall(r"href=['\"]([^'\"]+)['\"]", response.text, re.I):
                    absolute = urljoin("https://smashtv.jp/", html.unescape(value))
                    if "/works/" in absolute and absolute not in seen:
                        seen.add(absolute)
                        candidates.append(absolute)
        except Exception:
            pass

    # WordPress search can return stale/unrelated entries. Only keep exact
    # title/talent candidates; otherwise crawl the newest listing pages.
    title_key = re.sub(r"\s+", "", work_title).lower()
    talent_key = re.sub(r"\s+", "", talent).lower()
    exact_candidates = []
    for candidate in candidates:
        try:
            response = session.get(candidate, timeout=15)
            if response.status_code >= 400:
                continue
            normalized = re.sub(r"\s+", "", html.unescape(response.text)).lower()
            if title_key and title_key in normalized and (not talent_key or talent_key in normalized):
                exact_candidates.append(candidate)
        except Exception:
            continue
    candidates = unique(exact_candidates, 20)

    if not candidates:
        # Recent releases are normally on the newest listing pages. Keep this
        # bounded so Actions stays fast even as the archive grows.
        for base_path, page_count in (("/works/", 36), ("/movie/", 23)):
            for page in range(1, page_count + 1):
                url = f"https://smashtv.jp{base_path}" if page == 1 else f"https://smashtv.jp{base_path}page/{page}/"
                try:
                    response = session.get(url, timeout=15)
                    if response.status_code >= 400:
                        continue
                    source = html.unescape(response.text)
                    normalized_page = re.sub(r"\s+", "", source).lower()
                    if title_key not in normalized_page and (not talent_key or talent_key not in normalized_page):
                        continue
                    anchors = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', source, re.I | re.S)
                    for link, label in anchors:
                        label_text = re.sub(r"<[^>]+>", " ", html.unescape(label))
                        label_key = re.sub(r"\s+", "", label_text).lower()
                        if title_key and title_key in label_key and (not talent_key or talent_key in label_key):
                            absolute = urljoin(url, link)
                            if "/works/" in absolute:
                                candidates.append(absolute)
                except Exception:
                    continue

                url = f"https://smashtv.jp{base_path}" if page == 1 else f"https://smashtv.jp{base_path}page/{page}/"
                try:
                    response = session.get(url, timeout=15)
                    if response.status_code >= 400:
                        continue
                    source = html.unescape(response.text)
                    normalized_page = re.sub(r"\s+", "", source)
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
    processed = set()
    for page_url in unique(candidates, 20):
        if page_url in processed or page_url.rstrip("/") == "https://smashtv.jp/works":
            continue
        processed.add(page_url)
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
                return {"sample_video_url": videos[0], "sample_image_urls": unique(images), "sample_available": True, "sample_source_url": page_url}
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

        # FANZA/DMM is the primary source for every maker, including I-ONE.
        # Official maker sites are used only as a fallback when FANZA/DMM has
        # no sample media for an otherwise matched product.
        item = fanza_search(product, session)
        checked += 1
        if item:
            media = extract_media(item)
            if media["cover_image_url"]:
                product["cover_image_url"] = media["cover_image_url"]
            if media["sample_image_urls"]:
                product["sample_image_urls"] = unique(media["sample_image_urls"])
            if media["sample_video_url"]:
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True

        if product.get("maker_id") == "i-one":
            ione_checked += 1
            # Only supplement from official I-ONE when FANZA/DMM did not
            # provide the needed sample media.
            if not product.get("sample_video_url") or not product.get("sample_image_urls"):
                media = ione_public_sample(product, session)
                if not product.get("sample_video_url") and media.get("sample_video_url"):
                    product["sample_video_url"] = media["sample_video_url"]
                if not product.get("sample_image_urls") and media.get("sample_image_urls"):
                    product["sample_image_urls"] = filter_ione_images(
                        media["sample_image_urls"], product.get("product_code")
                    )
                if product.get("sample_video_url") or product.get("sample_image_urls"):
                    product["sample_available"] = bool(product.get("sample_video_url"))
                    product["sample_source_url"] = media.get("sample_source_url", "")
                    ione_changed += 1

            # If the official page exposes only one thumbnail, expand the
            # official numbered gallery as a last-resort supplement.
            if len(product.get("sample_image_urls") or []) < 2:
                discovered = discover_ione_sample_frames(product, session)
                if discovered:
                    product["sample_image_urls"] = discovered

            if not product.get("sample_image_urls"):
                lily = tokyolily_public_sample(product, session)
                if lily.get("sample_image_urls"):
                    product["sample_image_urls"] = lily["sample_image_urls"]
                    product["sample_source_url"] = lily.get("sample_source_url", "")

        if not product.get("sample_video_url") and not product.get("sample_image_urls") and product.get("maker_id") == "spice_visual":
            media = smashtv_public_sample(product, session)
            if media.get("sample_video_url"):
                product["sample_video_url"] = media["sample_video_url"]
                product["sample_available"] = True
                if media.get("sample_image_urls"):
                    product["sample_image_urls"] = media["sample_image_urls"]
                product["sample_source_url"] = media.get("sample_source_url", "")

        if not product.get("sample_video_url") and not product.get("sample_image_urls") and product.get("maker_id") == "takeshobo":
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
        time.sleep(0.05)

    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"sample enrichment checked={checked} changed={changed} "
        f"public_ione_checked={ione_checked} public_ione_changed={ione_changed} "
        f"public_takeshobo_checked={takeshobo_checked} public_takeshobo_changed={takeshobo_changed}"
    )

if __name__ == "__main__":
    main()

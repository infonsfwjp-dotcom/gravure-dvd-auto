from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})
API_CACHE: dict[tuple, list] = {}


def norm(s: str) -> str:
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(s or "")).lower()


def api_items(params):
    key = tuple(sorted(params.items()))
    if key in API_CACHE:
        return API_CACHE[key]
    try:
        r = SESSION.get(API_URL, params=params, timeout=10)
        if r.status_code >= 400:
            API_CACHE[key] = []
            return []
        items = r.json().get("result", {}).get("items", []) or []
        API_CACHE[key] = items
        return items
    except Exception:
        API_CACHE[key] = []
        return []


def item_code_blob(item):
    return norm(" ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid")))


def item_title_norm(item):
    return norm(item.get("title") or "")


def maker_match(item):
    raw = norm(json.dumps(item, ensure_ascii=False))
    return any(x in raw for x in (norm("ラインコミュニケーションズ"), norm("I-ONE"), norm("アイドルワン")))


def match_item(items, code, title, model):
    code_n = norm(code)
    title_n = norm(title)
    model_n = norm(model)
    for item in items:
        item_code = item_code_blob(item)
        item_title = item_title_norm(item)
        if code_n and code_n in item_code:
            return item
    # Only accept title/model matches when the returned item itself identifies
    # the I-ONE/Line Communications maker. This prevents false positives.
    for item in items:
        item_title = item_title_norm(item)
        if maker_match(item):
            if title_n and title_n in item_title:
                return item
            if model_n and model_n in item_title:
                return item
    return None


def dmm_match(code, title, model, release):
    if not API_ID or not AFFILIATE_ID:
        return None

    base = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "service": "mono",
        "floor": "dvd",
        "sort": "date",
        "hits": 100,
        "offset": 1,
        "output": "json",
    }

    # The old implementation made up to 6 API calls per product (strict and
    # non-strict variants for code/title/model). That made the catalog merge
    # unnecessarily slow. Prefer exact product-code searches first, then one
    # title and one model fallback. Date filtering is intentionally omitted from
    # the fallback: FANZA's metadata/search index can lag the official catalog.
    searches = [
        (str(code or "").strip(), True),
        (str(title or "").strip(), False),
        (str(model or "").strip(), False),
    ]
    seen = set()
    for keyword, reserve_only in searches:
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        params = dict(base)
        params["keyword"] = keyword
        if reserve_only:
            params["mono_stock"] = "reserve"
        items = api_items(params)
        matched = match_item(items, code, title, model)
        if matched:
            print(f"i-one FANZA API match code={code} keyword={keyword}")
            return matched

    return None


def parse_detail(url, start, end):
    try:
        r = SESSION.get(url, timeout=12)
        r.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    cm = re.search(r"品番\s*[：:]\s*([A-Z0-9-]+)", text, re.I)
    dm = re.search(r"発売日\s*[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if not cm or not dm:
        return None
    release = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    if not (start <= release <= end):
        return None
    code = cm.group(1).upper()
    og = soup.find("meta", attrs={"property": "og:title"})
    raw_title = (og.get("content") if og else "") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    title = re.sub(r"\s*[|｜].*$", "", raw_title).strip()
    title = re.sub(r"\s*〖[^〗]*〗", "", title).strip()
    model_m = re.search(r"モデル名\s*[：:]\s*([^\n]{1,80}?)(?:\s+商品詳細|\s+ファイル内容|\s+発売日)", text)
    model = model_m.group(1).strip() if model_m else ""
    return code, release, title, model, url


def apply_match(product, matched, fallback_title, code, model):
    item_title = str(matched.get("title") or fallback_title).strip()
    product_code = str(matched.get("maker_product") or matched.get("product_id") or code).strip()
    affiliate_url = str(matched.get("affiliateURL") or "")
    dmm_url = str(matched.get("URL") or "")
    product["title"] = item_title
    product["product_code"] = product_code
    product["affiliate_url"] = affiliate_url
    product["dmm_url"] = dmm_url
    product["affiliate_match_status"] = "matched" if affiliate_url else "unmatched"
    if model:
        product["talent"] = [model]
    return bool(affiliate_url)


def main():
    if not DATA.exists():
        return
    products = json.loads(DATA.read_text(encoding="utf-8"))
    existing_by_code = {
        norm(p.get("product_code")): p
        for p in products
        if p.get("product_code")
    }
    start = date.today() - timedelta(days=30)
    end = date.today() + timedelta(days=180)
    base = "https://i-one.tv/content/?maker=line-communications&page={}"
    seen = set()
    details = []
    # The catalogue is newest-first. Six pages is enough for the configured
    # date window and avoids spending most of the Actions budget on old pages.
    for page in range(1, 7):
        try:
            r = SESSION.get(base.format(page), timeout=12)
            r.raise_for_status()
        except requests.RequestException:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        page_links = 0
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/content/detail/" not in href:
                continue
            url = requests.compat.urljoin(r.url, href)
            if url not in seen:
                seen.add(url)
                details.append(url)
                page_links += 1
        print(f"i-one catalog page={page} detail_links={page_links}")
        if not page_links:
            break

    added = 0
    enriched = 0
    for url in details:
        parsed = parse_detail(url, start, end)
        if not parsed:
            continue
        code, release, title, model, source_url = parsed
        existing = existing_by_code.get(norm(code))

        if existing:
            if existing.get("affiliate_match_status") == "matched" and existing.get("affiliate_url"):
                continue
            matched = dmm_match(code, title, model, release)
            if matched and apply_match(existing, matched, title, code, model):
                existing["source_url"] = source_url
                existing["status"] = "upcoming" if release >= date.today() else "released"
                enriched += 1
                print(f"i-one affiliate enriched code={code}")
            continue

        matched = dmm_match(code, title, model, release)
        if matched:
            item_title = str(matched.get("title") or title).strip()
            product_code = str(matched.get("maker_product") or matched.get("product_id") or code).strip()
            affiliate_url = str(matched.get("affiliateURL") or "")
            dmm_url = str(matched.get("URL") or "")
            talent = [model] if model else []
        else:
            item_title = title or (f"{model} {code}" if model else code)
            product_code = code
            affiliate_url = ""
            dmm_url = ""
            talent = [model] if model else []
        product = {
            "maker": "ラインコミュニケーションズ / I-ONE",
            "maker_id": "i-one",
            "title": item_title,
            "release_date": release.isoformat(),
            "product_code": product_code,
            "jan": "",
            "talent": talent,
            "source_url": source_url,
            "affiliate_url": affiliate_url,
            "dmm_url": dmm_url,
            "affiliate_match_status": "matched" if affiliate_url else "unmatched",
            "status": "upcoming" if release >= date.today() else "released",
            "tags": [f"{release.year}年", release.strftime("%Y-%m"), f"{release.strftime('%Y-%m')}発売", "ラインコミュニケーションズ / I-ONE"],
        }
        products.append(product)
        existing_by_code[norm(code)] = product
        added += 1

    products.sort(key=lambda p: (p.get("release_date") or "", p.get("maker") or "", p.get("title") or ""), reverse=True)
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"i-one official catalog added={added} enriched={enriched}")
    print(f"products total={len(products)}")


if __name__ == "__main__":
    main()

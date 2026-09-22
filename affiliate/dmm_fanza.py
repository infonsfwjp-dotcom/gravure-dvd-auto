from __future__ import annotations
import os
import json
import re
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, parse_qs

API_URL = os.getenv("DMM_API_URL", "https://api.dmm.com/affiliate/v3/ItemList")
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")
SITE = "FANZA"
DATA = Path(__file__).resolve().parents[1] / "data/products.json"


def norm(s):
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(s or "")).lower()


def norm_code(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def performer_candidates(p):
    out = []
    for value in p.get("talent") or []:
        text = str(value or "").strip()
        if not text:
            continue
        tail = re.split(r"(?:系|グラドル|アイドル)\s*", text)[-1].strip(" ・|｜:：-")
        for candidate in (tail, text):
            candidate = re.sub(r"^[ー―–—-]+\s*", "", candidate).strip()
            if candidate and len(candidate) <= 40 and candidate not in out:
                out.append(candidate)
    title = str(p.get("title") or "").strip()
    if title and not re.search(r"[「『]", title) and len(title) <= 30:
        out.append(title)
    return out[:3]


def match_facts(p, i):
    raw_title = str(p.get("title") or "")
    clean_title = re.sub(r"\s*【I-ONE TV限定特典映像付き】", "", raw_title)
    clean_title = re.sub(r"\s*[/／]\s*4Kあり", "", clean_title)
    clean_title = re.sub(r"\s*4Kあり", "", clean_title).strip()
    title_variants = [norm(raw_title), norm(clean_title)]
    it = norm(i.get("title"))
    title_exact = bool(it and any(v and v == it for v in title_variants))
    title_partial = bool(it and any(v and (v in it or it in v) for v in title_variants))
    performers = [norm(x) for x in performer_candidates(p) if norm(x)]
    performer_hit = bool(performers and it and any(x in it for x in performers))

    code = norm_code(p.get("product_code"))
    candidates = [norm_code(i.get("maker_product")), norm_code(i.get("product_id")), norm_code(i.get("content_id"))]
    code_exact = bool(code and any(code == c for c in candidates if c))
    code_partial = bool(code and any(code in c or c in code for c in candidates if c))

    jan = re.sub(r"\D", "", str(p.get("jan") or ""))
    dmm_jan = re.sub(r"\D", "", str(i.get("jancode") or i.get("jan") or ""))
    jan_exact = bool(jan and dmm_jan and jan == dmm_jan)

    date_exact = bool(p.get("release_date") and str(i.get("date") or "")[:10] == str(p["release_date"]))
    return title_exact, title_partial, performer_hit, code_exact, code_partial, jan_exact, date_exact


def score(p, i):
    title_exact, title_partial, performer_hit, code_exact, code_partial, jan_exact, date_exact = match_facts(p, i)
    v = 0
    if title_exact:
        v += 100
    elif title_partial:
        v += 55
    if performer_hit:
        v += 35
    if code_exact:
        v += 140
    elif code_partial:
        v += 20
    if jan_exact:
        v += 180
    if date_exact:
        v += 15
    return v


def search_keywords(p):
    keywords = []

    def add(value):
        value = str(value or "").strip()
        if value and value not in keywords:
            keywords.append(value)

    jan_raw = str(p.get("jan") or "").strip()
    jan_digits = re.sub(r"\D", "", jan_raw)
    code_raw = str(p.get("product_code") or "").strip()
    code_normalized = norm_code(code_raw)
    title_raw = str(p.get("title") or "").strip()

    add(jan_raw)
    add(jan_digits)
    add(code_raw)
    add(code_normalized)
    add(title_raw)
    add(norm(title_raw))
    clean_title = re.sub(r"\s*【I-ONE TV限定特典映像付き】", "", title_raw)
    clean_title = re.sub(r"\s*[/／]\s*4Kあり", "", clean_title)
    clean_title = re.sub(r"\s*4Kあり", "", clean_title).strip()
    add(clean_title)
    add(norm(clean_title))
    for performer in performer_candidates(p):
        add(performer)
        add(norm(performer))

    return keywords


def official_cids(source_url):
    if not source_url:
        return []
    try:
        r = requests.get(source_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        href = unquote(unquote(a.get("href", "")))
        if "dmm" not in href.lower() and "fanza" not in href.lower():
            continue
        for m in re.finditer(r"/(?:mono/dvd|digital/videoa)/-/detail/=/cid=([a-zA-Z0-9_-]+)", href, re.I):
            cid = m.group(1).lower()
            if cid not in found: found.append(cid)
        try:
            for values in parse_qs(urlparse(href).query).values():
                for value in values:
                    for m in re.finditer(r"(?:^|[?&])cid=([a-zA-Z0-9_-]+)", unquote(unquote(value)), re.I):
                        cid = m.group(1).lower()
                        if cid not in found: found.append(cid)
        except ValueError: pass
    return found[:10]

def search_official_cids(p):
    if not API_ID or not AFFILIATE_ID: return []
    items = []
    for cid in official_cids(p.get("source_url")):
        params = {"api_id": API_ID, "affiliate_id": AFFILIATE_ID, "site": SITE, "service": "mono", "floor": "dvd", "cid": cid, "hits": 20, "offset": 1, "output": "json"}
        found, _ = request_items(params)
        items.extend(found)
    return items
def request_items(params):
    r = requests.get(API_URL, params=params, timeout=30)
    if r.status_code >= 400:
        return [], f"DMM API HTTP {r.status_code}: {r.text[:300]}"
    try:
        return r.json().get("result", {}).get("items", []) or [], None
    except Exception as e:
        return [], f"DMM API invalid JSON: {e}"


def search(p):
    if not API_ID or not AFFILIATE_ID:
        raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    if not re.search(r"-(?:99[0-9])$", AFFILIATE_ID):
        raise RuntimeError(
            "DMM_AFFILIATE_ID is not API-enabled. Use the DMM Web Service/API affiliate ID "
            "ending in -990 through -999 (not the normal affiliate link ID)."
        )

    all_items = {}
    last_error = None

    base = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": SITE,
        "service": "mono",
        "floor": "dvd",
        "hits": 100,
        "output": "json",
    }

    # 1) Normal exact/partial keyword searches.
    for keyword in search_keywords(p):
        params = dict(base)
        params.update({"keyword": keyword, "sort": "match"})
        items, error = request_items(params)
        if error:
            last_error = error
            continue
        for item in items:
            key = item.get("product_id") or item.get("content_id") or item.get("URL")
            if key:
                all_items[key] = item
        time.sleep(0.2)

    # 2) Critical fallback: search the entire FANZA DVD catalog for the exact
    #    release date. Upcoming manufacturer pages can precede FANZA indexing,
    #    and product-code keyword searches may return unrelated older products.
    release_date = str(p.get("release_date") or "")[:10]
    if release_date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        date_start = f"{release_date}T00:00:00"
        date_end = f"{release_date}T23:59:59"
        params = dict(base)
        params.update({
            "gte_date": date_start,
            "lte_date": date_end,
            "sort": "date",
        })
        items, error = request_items(params)
        if error:
            last_error = error
        else:
            for item in items:
                key = item.get("product_id") or item.get("content_id") or item.get("URL")
                if key:
                    all_items[key] = item
        time.sleep(0.2)

    if all_items:
        return list(all_items.values())
    if last_error:
        raise RuntimeError(last_error)
    return []


def diagnostic_line(p, ranked):
    if not ranked:
        return f"DIAG title={p.get('title')} code={p.get('product_code')} jan={p.get('jan')} candidates=0"
    s, i = ranked[0]
    facts = match_facts(p, i)
    return (
        f"DIAG title={p.get('title')} code={p.get('product_code')} jan={p.get('jan')} "
        f"score={s} facts={facts} affiliate={'yes' if i.get('affiliateURL') else 'no'} "
        f"dmm_code={i.get('maker_product') or ''} product_id={i.get('product_id') or ''} "
        f"jancode={i.get('jancode') or i.get('jan') or ''} date={str(i.get('date') or '')[:10]} "
        f"dmm_title={str(i.get('title') or '')[:100]}"
    )


def enrich():
    products = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    matched = review = not_found = errors = 0
    diagnostics = 0
    for p in products:
        p.pop("affiliate_error", None)
        try:
            ranked = sorted(((score(p, i), i) for i in (search_official_cids(p) + search(p))), key=lambda x: x[0], reverse=True)
            if diagnostics < 10:
                print(diagnostic_line(p, ranked))
                diagnostics += 1
            if not ranked:
                # Never erase a previously verified FANZA/DMM link because a single
                # API run returned no candidates.
                p["affiliate_match_status"] = "matched" if p.get("affiliate_url") else "not_found"
                not_found += 1
                continue

            s, i = ranked[0]
            title_exact, title_partial, performer_hit, code_exact, code_partial, jan_exact, date_exact = match_facts(p, i)
            p["affiliate_match_score"] = s

            strong_identity = (
                jan_exact
                or code_exact
                or (title_exact and performer_hit)
                or (title_exact and date_exact)
                or (title_partial and performer_hit and date_exact)
            )
            if strong_identity and s >= 80 and i.get("affiliateURL"):
                p["affiliate_url"] = i["affiliateURL"]
                p["dmm_url"] = i.get("URL") or p["affiliate_url"]
                p["affiliate_match_status"] = "matched"
                matched += 1
            elif s >= 45:
                if p.get("affiliate_url"):
                    p["affiliate_match_status"] = "matched"
                else:
                    p["affiliate_match_status"] = "review"
                review += 1
            else:
                if p.get("affiliate_url"):
                    p["affiliate_match_status"] = "matched"
                else:
                    p["affiliate_match_status"] = "unmatched"
                review += 1
        except Exception as e:
            p["affiliate_match_status"] = "error"
            p["affiliate_error"] = str(e)
            errors += 1

    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"affiliate matches={matched} review_or_unmatched={review} not_found={not_found} errors={errors}")


if __name__ == "__main__":
    enrich()

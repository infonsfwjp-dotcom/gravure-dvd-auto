from __future__ import annotations
import os
import json
import re
import time
from pathlib import Path
import requests

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


def inferred_ione_jan(product_code):
    """Infer the standard Line Communications JAN from an LCDV catalog code.
    Only use the value as a DMM/FANZA search key; accept it as product data
    only when the API returns an exact JAN/code match.
    """
    m = re.fullmatch(r"LCDV-(\d{5})", str(product_code or "").strip(), re.I)
    if not m:
        return ""
    base = "4529971" + m.group(1)
    check = (10 - sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base)) % 10) % 10
    return base + str(check)


def search_keywords(p):
    keywords = []

    def add(value):
        value = str(value or "").strip()
        if value and value not in keywords:
            keywords.append(value)

    jan_raw = str(p.get("jan") or "").strip()
    jan_digits = re.sub(r"\D", "", jan_raw)
    inferred_jan = inferred_ione_jan(p.get("product_code")) if p.get("maker_id") == "i-one" else ""
    code_raw = str(p.get("product_code") or "").strip()
    code_normalized = norm_code(code_raw)
    title_raw = str(p.get("title") or "").strip()

    add(jan_raw)
    add(jan_digits)
    add(inferred_jan)
    add(code_raw)
    add(code_normalized)
    add(title_raw)
    add(norm(title_raw))
    clean_title = re.sub(r"\s*【I-ONE TV限定特典映像付き】", "", title_raw)
    clean_title = re.sub(r"\s*[/／]\s*4Kあり", "", clean_title)
    clean_title = re.sub(r"\s*4Kあり", "", clean_title).strip()
    add(clean_title)
    add(norm(clean_title))
    # FANZA/DMM often indexes the work title without the performer and
    # without the I-ONE bonus/4K suffix. Search that human-visible title too.
    title_core = re.split(r"[/／]", clean_title, maxsplit=1)[0].strip()
    add(title_core)
    add(norm(title_core))
    for performer in performer_candidates(p):
        add(performer)
        add(norm(performer))

    return keywords


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
        for reserve in ([False, True] if p.get("maker_id") == "i-one" else [False]):
            params = dict(base)
            params.update({"keyword": keyword, "sort": "match"})
            # For Line Communications, do not constrain the ItemList keyword query
            # by the FANZA maker facet: the DMM API maker facet does not reliably
            # expose all LCDV catalog items even when the public maker page does.
            # Identity is verified below from title/code/JAN/date; the search remains
            # entirely inside FANZA/DMM.
            if reserve:
                params["mono_stock"] = "reserve"
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
        if p.get("maker_id") == "i-one":
            params["mono_stock"] = "reserve"
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
        if p.get("maker_id") == "i-one":
            p["maker"] = "ラインコミュニケーションズ"
            p["tags"] = [
                "ラインコミュニケーションズ" if t == "ラインコミュニケーションズ / I-ONE" else t
                for t in (p.get("tags") or [])
            ]
        try:
            ranked = sorted(((score(p, i), i) for i in (search(p))), key=lambda x: x[0], reverse=True)
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

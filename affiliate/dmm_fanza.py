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
        # Current I-ONE pages sometimes expose descriptive category text
        # followed by the performer name. Keep the tail after the last category.
        tail = re.split(r"(?:系|グラドル|アイドル)\s*", text)[-1].strip(" ・")
        for candidate in (tail, text):
            if candidate and len(candidate) <= 40 and candidate not in out:
                out.append(candidate)
    title = str(p.get("title") or "").strip()
    if title and not re.search(r"[「『]", title) and len(title) <= 30:
        out.append(title)
    return out[:3]


def score(p, i):
    v = 0
    pt, it = norm(p.get("title")), norm(i.get("title"))
    if pt and it:
        v += 100 if pt == it else (55 if pt in it or it in pt else 0)

    performers = [norm(x) for x in performer_candidates(p) if norm(x)]
    if performers and it and any(x in it for x in performers):
        v += 35

    code = norm_code(p.get("product_code"))
    for candidate in (i.get("maker_product"), i.get("product_id"), i.get("content_id")):
        candidate_code = norm_code(candidate)
        if code and candidate_code:
            if code == candidate_code:
                v += 140
                break
            if code in candidate_code or candidate_code in code:
                v += 90
                break

    jan = str(p.get("jan") or "").strip()
    dmm_jan = str(i.get("jancode") or i.get("jan") or "").strip()
    if jan and dmm_jan and jan == dmm_jan:
        v += 180

    if p.get("release_date") and str(i.get("date") or "")[:10] == str(p["release_date"]):
        v += 15
    return v


def search(p):
    if not API_ID or not AFFILIATE_ID:
        raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    if not re.search(r"-(?:99[0-9])$", AFFILIATE_ID):
        raise RuntimeError(
            "DMM_AFFILIATE_ID is not API-enabled. Use the DMM Web Service/API affiliate ID "
            "ending in -990 through -999 (not the normal affiliate link ID)."
        )

    keywords = []
    values = [p.get("jan"), p.get("product_code"), p.get("title")]
    values.extend(performer_candidates(p))
    for value in values:
        value = str(value or "").strip()
        if value and value not in keywords:
            keywords.append(value)

    # Do not stop at the first non-empty query. JAN/product-code searches can
    # return broad or unrelated results; aggregate all candidates and let the
    # scorer choose the best product using title, performer, code, JAN and date.
    all_items = {}
    last_error = None
    for keyword in keywords:
        params = {
            "api_id": API_ID,
            "affiliate_id": AFFILIATE_ID,
            "site": SITE,
            "service": "mono",
            "floor": "dvd",
            "keyword": keyword,
            "hits": 100,
            "sort": "match",
            "output": "json",
        }
        r = requests.get(API_URL, params=params, timeout=30)
        if r.status_code >= 400:
            last_error = f"DMM API HTTP {r.status_code}: {r.text[:300]}"
            continue
        items = r.json().get("result", {}).get("items", []) or []
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


def enrich():
    products = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    matched = review = not_found = errors = 0
    for p in products:
        p.pop("affiliate_error", None)
        try:
            ranked = sorted(
                ((score(p, i), i) for i in search(p)),
                key=lambda x: x[0],
                reverse=True,
            )
            if not ranked:
                p["affiliate_match_status"] = "not_found"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
                not_found += 1
                continue

            s, i = ranked[0]
            p["affiliate_match_score"] = s
            # Exact title alone, exact maker code, JAN, or a strong combination
            # is sufficient. Performer+title is also accepted for DMM titles
            # that prepend the performer name.
            if s >= 80 and i.get("affiliateURL"):
                p["affiliate_url"] = i["affiliateURL"]
                p["dmm_url"] = i.get("URL") or p["affiliate_url"]
                p["affiliate_match_status"] = "matched"
                matched += 1
            elif s >= 45:
                p["affiliate_match_status"] = "review"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
                review += 1
            else:
                p["affiliate_match_status"] = "unmatched"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
                review += 1
        except Exception as e:
            p["affiliate_match_status"] = "error"
            p["affiliate_error"] = str(e)
            errors += 1

    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"affiliate matches={matched} review_or_unmatched={review} not_found={not_found} errors={errors}")


if __name__ == "__main__":
    enrich()

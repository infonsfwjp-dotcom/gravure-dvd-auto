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
# DMM Web API uses DMM.co.jp for FANZA/adult data; "FANZA" is not a valid API site value.
SITE = "DMM.co.jp"
DATA = Path(__file__).resolve().parents[1] / "data/products.json"


def norm(s):
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，]+", "", str(s or "")).lower()


def norm_code(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def score(p, i):
    v = 0
    pt, it = norm(p.get("title")), norm(i.get("title"))
    if pt and it:
        v += 80 if pt == it else (45 if pt in it or it in pt else 0)

    code = norm_code(p.get("product_code"))
    for candidate in (i.get("product_id"), i.get("content_id"), i.get("maker_product")):
        candidate_code = norm_code(candidate)
        if code and candidate_code:
            if code == candidate_code:
                v += 120
                break
            if code in candidate_code or candidate_code in code:
                v += 80
                break

    if p.get("jan") and str(p["jan"]).strip() == str(i.get("jan") or i.get("jancode") or "").strip():
        v += 150
    if p.get("release_date") and str(i.get("date") or "")[:10] == str(p["release_date"]):
        v += 10
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
    for value in (p.get("jan"), p.get("product_code"), p.get("title")):
        if value and value not in keywords:
            keywords.append(value)

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
        r.raise_for_status()
        items = r.json().get("result", {}).get("items", []) or []
        if items:
            return items
        time.sleep(0.15)
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

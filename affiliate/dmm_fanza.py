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
# DMM Web API accepts DMM.com / DMM.co.jp here; FANZA is the affiliate destination,
# not the API `site` value.
SITE = os.getenv("DMM_SITE", "DMM.com")
DATA = Path(__file__).resolve().parents[1] / "data/products.json"


def norm(s):
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，]+", "", str(s or "")).lower()


def score(p, i):
    v = 0
    pt, it = norm(p.get("title")), norm(i.get("title"))
    if pt and it:
        v += 80 if pt == it else (45 if pt in it or it in pt else 0)
    code = str(p.get("product_code") or "").lower()
    content_id = str(i.get("content_id") or "").lower()
    if code and code in content_id:
        v += 35
    if p.get("jan") and str(p["jan"]) == str(i.get("jan") or ""):
        v += 100
    if p.get("release_date") and str(i.get("date") or "")[:10] == str(p["release_date"]):
        v += 10
    return v


def search(p):
    if not API_ID or not AFFILIATE_ID:
        raise RuntimeError("DMM_API_ID / DMM_AFFILIATE_ID are not configured")
    for keyword in (p.get("jan"), p.get("product_code"), p.get("title")):
        if not keyword:
            continue
        params = {
            "api_id": API_ID,
            "affiliate_id": AFFILIATE_ID,
            "site": SITE,
            "service": "mono",
            "floor": "dvd",
            "keyword": keyword,
            "hits": 20,
            "output": "json",
        }
        r = requests.get(API_URL, params=params, timeout=30)
        r.raise_for_status()
        items = r.json().get("result", {}).get("items", []) or []
        if items:
            return items
        time.sleep(0.2)
    return []


def enrich():
    products = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    for p in products:
        p.pop("affiliate_error", None)
        try:
            ranked = sorted(((score(p, i), i) for i in search(p)), key=lambda x: x[0], reverse=True)
            if not ranked:
                p["affiliate_match_status"] = "not_found"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
                continue
            s, i = ranked[0]
            p["affiliate_match_score"] = s
            if s >= 80 and i.get("affiliateURL"):
                p["affiliate_url"] = i["affiliateURL"]
                p["dmm_url"] = i.get("URL") or p["affiliate_url"]
                p["affiliate_match_status"] = "matched"
            elif s >= 45:
                p["affiliate_match_status"] = "review"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
            else:
                p["affiliate_match_status"] = "unmatched"
                p.pop("affiliate_url", None)
                p.pop("dmm_url", None)
        except Exception as e:
            p["affiliate_match_status"] = "error"
            p["affiliate_error"] = str(e)
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    enrich()

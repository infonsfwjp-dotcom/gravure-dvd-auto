from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
import requests

API_URL = os.getenv("DMM_API_URL", "https://api.dmm.com/affiliate/v3/ItemList")
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")
DATA = Path(__file__).resolve().parents[1] / "data/products.json"


def request(cid):
    params = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "service": "mono",
        "floor": "dvd",
        "cid": cid,
        "hits": 20,
        "output": "json",
    }
    r = requests.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("result", {}).get("items", []) or []


def strong_match(p, item):
    code = re.sub(r"[^a-z0-9]", "", str(p.get("product_code") or "").lower())
    candidates = [
        re.sub(r"[^a-z0-9]", "", str(item.get("maker_product") or "").lower()),
        re.sub(r"[^a-z0-9]", "", str(item.get("product_id") or "").lower()),
        re.sub(r"[^a-z0-9]", "", str(item.get("content_id") or "").lower()),
    ]
    if code and code in candidates:
        return True
    pt = re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(p.get("title") or "")).lower()
    it = re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(item.get("title") or "")).lower()
    return bool(pt and it and (pt == it or pt in it or it in pt))


def main():
    products = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    updated = 0
    for p in products:
        cid = str(p.get("source_dmm_cid") or "").strip()
        if not cid or p.get("affiliate_url"):
            continue
        try:
            items = request(cid)
            matches = [i for i in items if strong_match(p, i) and i.get("affiliateURL")]
            if matches:
                item = matches[0]
                p["affiliate_url"] = item["affiliateURL"]
                p["dmm_url"] = item.get("URL") or p["affiliate_url"]
                p["affiliate_match_status"] = "matched"
                p["affiliate_match_score"] = 300
                updated += 1
                print(f"CID MATCH title={p.get('title')} cid={cid} dmm_title={item.get('title','')}")
            else:
                print(f"CID MISS title={p.get('title')} cid={cid} items={len(items)}")
        except Exception as e:
            print(f"CID ERROR title={p.get('title')} cid={cid} error={e}")
        time.sleep(0.2)
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"source-cid matches={updated}")


if __name__ == "__main__":
    main()

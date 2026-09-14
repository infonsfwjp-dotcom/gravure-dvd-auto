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

CID_PATTERNS=(r"[?&]cid=([a-z0-9_\-]+)",r"/cid/([a-z0-9_\-]+)",r"/cid=([a-z0-9_\-]+)",r"/(?:mono|product|detail)/([a-z0-9_\-]+)(?:[/?#]|$)")

def extract_cid(url):
    if not url: return ""
    for pat in CID_PATTERNS:
        m=re.search(pat,str(url),re.I)
        if m: return m.group(1)
    return ""

def resolve_cid(url):
    cid=extract_cid(url)
    if cid: return cid
    try:
        r=requests.get(url,timeout=20,allow_redirects=True,headers={"User-Agent":"Mozilla/5.0"})
        cid=extract_cid(r.url)
        if cid: return cid
        for value in (r.text[:500000],):
            m=re.search(r"(?:cid|content_id)\s*[=:]\s*[\"']?([a-z0-9_\-]+)",value,re.I)
            if m: return m.group(1)
    except Exception:
        pass
    return ""

def request(cid):
    params={"api_id":API_ID,"affiliate_id":AFFILIATE_ID,"site":"FANZA","service":"mono","floor":"dvd","cid":cid,"hits":20,"output":"json"}
    r=requests.get(API_URL,params=params,timeout=30); r.raise_for_status()
    return r.json().get("result",{}).get("items",[]) or []

def strong_match(p,item):
    code=re.sub(r"[^a-z0-9]","",str(p.get("product_code") or "").lower())
    candidates=[re.sub(r"[^a-z0-9]","",str(item.get(k) or "").lower()) for k in ("maker_product","product_id","content_id")]
    if code and code in candidates: return True
    pt=re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+","",str(p.get("title") or "")).lower()
    it=re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+","",str(item.get("title") or "")).lower()
    return bool(pt and it and (pt==it or pt in it or it in pt))

def main():
    products=json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    updated=0
    for p in products:
        cid=str(p.get("source_dmm_cid") or "").strip()
        if not cid:
            cid=resolve_cid(str(p.get("source_dmm_url") or "").strip())
            if cid: p["source_dmm_cid"]=cid
        if not cid or p.get("affiliate_url"): continue
        try:
            items=request(cid); matches=[i for i in items if strong_match(p,i) and i.get("affiliateURL")]
            if matches:
                item=matches[0]; p["affiliate_url"]=item["affiliateURL"]; p["dmm_url"]=item.get("URL") or p["affiliate_url"]; p["affiliate_match_status"]="matched"; p["affiliate_match_score"]=300; updated+=1
                print(f"CID MATCH title={p.get('title')} cid={cid} dmm_title={item.get('title','')}")
            else: print(f"CID MISS title={p.get('title')} cid={cid} items={len(items)}")
        except Exception as e: print(f"CID ERROR title={p.get('title')} cid={cid} error={e}")
        time.sleep(0.2)
    DATA.write_text(json.dumps(products,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"source-cid matches={updated}")

if __name__=="__main__": main()

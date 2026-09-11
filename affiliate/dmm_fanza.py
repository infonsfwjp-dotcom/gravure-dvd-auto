from __future__ import annotations
import os,json,re,time
from pathlib import Path
import requests
API_URL=os.getenv("DMM_API_URL","https://api.dmm.com/affiliate/v3/ItemList"); API_ID=os.getenv("DMM_API_ID",""); AFFILIATE_ID=os.getenv("DMM_AFFILIATE_ID",""); SITE=os.getenv("DMM_SITE","FANZA")
DATA=Path(__file__).resolve().parents[1]/"data/products.json"
def norm(s): return re.sub(r"[\s　「」『』（）()\-ー・:：/／]+","",s or "").lower()
def score(p,i):
    v=0; pt=norm(p.get("title")); it=norm(i.get("title"))
    if pt and it: v += 80 if pt==it else (45 if pt in it or it in pt else 0)
    code=p.get("product_code")
    if code and code.lower() in str(i.get("content_id","")).lower(): v+=35
    if p.get("jan") and str(p["jan"])==str(i.get("jan","") ): v+=100
    if p.get("release_date") and str(i.get("date",""))[:10]==p["release_date"]: v+=10
    return v
def search(p):
    if not API_ID or not AFFILIATE_ID: return []
    keyword=p.get("jan") or p.get("product_code") or p.get("title")
    if not keyword:return []
    params={"api_id":API_ID,"affiliate_id":AFFILIATE_ID,"site":SITE,"service":"digital","floor":"videoa","keyword":keyword,"hits":20,"output":"json"}
    r=requests.get(API_URL,params=params,timeout=30); r.raise_for_status(); return r.json().get("result",{}).get("items",[]) or []
def enrich():
    products=json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    for p in products:
        try:
            ranked=sorted(((score(p,i),i) for i in search(p)),key=lambda x:x[0],reverse=True)
            if not ranked: p["affiliate_match_status"]="not_found"; continue
            s,i=ranked[0]; p["affiliate_match_score"]=s
            if s>=80:
                p["affiliate_url"]=i.get("affiliateURL") or ""; p["dmm_url"]=i.get("URL") or p["affiliate_url"]; p["affiliate_match_status"]="matched"
            elif s>=45: p["affiliate_match_status"]="review"
            else: p["affiliate_match_status"]="unmatched"
            time.sleep(.2)
        except Exception as e: p["affiliate_match_status"]="error"; p["affiliate_error"]=str(e)
    DATA.write_text(json.dumps(products,ensure_ascii=False,indent=2),encoding="utf-8")
if __name__=="__main__": enrich()

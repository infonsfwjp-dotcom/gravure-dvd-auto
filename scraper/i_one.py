from __future__ import annotations
import re
from urllib.parse import urljoin
from scraper.base import clean,parse_japanese_date,now,add_common_tags
from scraper.http import soup
BASE="https://www.i-one-net.com"; MAKER="ラインコミュニケーションズ / I-ONE"; ID="i-one"

def parse(url, s):
    txt=clean(s.get_text(" ",strip=True)); title=clean((s.find("h1") or s.find("h2") or s.title).get_text(" ",strip=True) if (s.find("h1") or s.find("h2") or s.title) else "")
    date=parse_japanese_date(txt); code=None
    for pat in [r"(?:品番|型番|商品番号|Model)\s*[:：]?\s*([A-Z0-9-]{5,})", r"\b(L[A-Z0-9-]{6,})\b"]:
        m=re.search(pat,txt,re.I)
        if m: code=m.group(1); break
    return add_common_tags({"maker":MAKER,"maker_id":ID,"title":title,"release_date":date,"product_code":code,"source_url":url,"source_checked_at":now()})

def scrape():
    urls={BASE,BASE+"/new",BASE+"/dvd/release_date"}; found=set(); out=[]
    for u in urls:
        s=soup(u)
        for a in s.select('a[href*="/item/"]'):
            href=urljoin(BASE,a.get("href"));
            if href in found: continue
            found.add(href)
            try: out.append(parse(href,soup(href)))
            except Exception: pass
    return [p for p in out if p.get("title")]

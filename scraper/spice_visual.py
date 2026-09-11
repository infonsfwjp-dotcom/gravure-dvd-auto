from __future__ import annotations
import re
from urllib.parse import urljoin
from scraper.base import clean,parse_japanese_date,now,add_common_tags
from scraper.http import soup
BASE="https://www.spicevisual.com"; ID="spice-visual"; MAKER="スパイスビジュアル"

def scrape():
    s=soup(BASE); links=set(); out=[]
    for a in s.select("a[href]"):
        h=urljoin(BASE,a.get("href"))
        if any(x in h.lower() for x in ("product","item","dvd")): links.add(h)
    for u in links:
        try:
            d=soup(u); txt=clean(d.get_text(" ",strip=True)); title=clean((d.find("h1") or d.find("h2") or d.title).get_text(" ",strip=True) if (d.find("h1") or d.find("h2") or d.title) else "")
            jan=re.search(r"\b([0-9]{13})\b",txt); code=re.search(r"\b([A-Z]{2,6}-[A-Z0-9-]{4,})\b",txt)
            out.append(add_common_tags({"maker":MAKER,"maker_id":ID,"title":title,"release_date":parse_japanese_date(txt),"jan":jan.group(1) if jan else None,"product_code":code.group(1) if code else None,"source_url":u,"source_checked_at":now()}))
        except Exception: pass
    return [p for p in out if p.get("title")]

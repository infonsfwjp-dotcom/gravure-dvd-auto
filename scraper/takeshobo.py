from __future__ import annotations
import re
from urllib.parse import urljoin
from scraper.base import clean,parse_japanese_date,now,add_common_tags
from scraper.http import soup
START="https://www.takeshobo.co.jp/search/?search_genre=106104"; ID="takeshobo"; MAKER="竹書房"

def scrape():
    s=soup(START); links=set(); out=[]
    for a in s.select("a[href]"):
        h=urljoin(START,a.get("href"));
        if any(x in h for x in ("/book/","/item/","/product/")): links.add(h)
    for u in links:
        try:
            d=soup(u); txt=clean(d.get_text(" ",strip=True)); title=clean((d.find("h1") or d.find("h2") or d.title).get_text(" ",strip=True) if (d.find("h1") or d.find("h2") or d.title) else "")
            m=re.search(r"(?:ISBN|JAN|EAN)\s*[:：]?\s*([0-9]{10,13})",txt,re.I); c=re.search(r"(?:品番|型番)\s*[:：]?\s*([A-Z0-9-]{5,})",txt,re.I)
            out.append(add_common_tags({"maker":MAKER,"maker_id":ID,"title":title,"release_date":parse_japanese_date(txt),"jan":m.group(1) if m else None,"product_code":c.group(1) if c else None,"source_url":u,"source_checked_at":now()}))
        except Exception: pass
    return [p for p in out if p.get("title")]

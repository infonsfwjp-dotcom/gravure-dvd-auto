from __future__ import annotations
import re
from urllib.parse import urljoin
from scraper.base import clean,parse_japanese_date,now,add_common_tags
from scraper.http import soup

BASE="https://www.i-one-net.com"
MAKER="ラインコミュニケーションズ / I-ONE"
ID="i-one"


def parse(url, s):
    txt=clean(s.get_text(" ",strip=True))
    heading=s.find("h1") or s.find("h2") or s.title
    title=clean(heading.get_text(" ",strip=True) if heading else "")
    date=parse_japanese_date(txt)
    code=None
    for pat in [
        r"(?:型番|品番|商品番号|Model)\s*[:：]?\s*([A-Z0-9-]{5,})",
        r"\b(L[A-Z0-9-]{6,})\b",
    ]:
        m=re.search(pat,txt,re.I)
        if m:
            code=m.group(1)
            break
    # Product pages expose the performer separately in the page heading/title area.
    talent=[]
    if heading:
        name=clean(heading.get_text(" ",strip=True))
        if name and name != title:
            talent=[name]
    return add_common_tags({
        "maker":MAKER,
        "maker_id":ID,
        "title":title,
        "release_date":date,
        "product_code":code,
        "talent":talent,
        "source_url":url,
        "source_checked_at":now(),
    })


def scrape():
    # The current I-ONE site exposes product pages directly from the homepage,
    # and `/new` is no longer a valid route. Keep release-date as a secondary source.
    urls={BASE, BASE+"/release_date"}
    found=set()
    out=[]
    for u in urls:
        try:
            s=soup(u)
        except Exception:
            continue
        for a in s.select('a[href*="/item/"]'):
            href=urljoin(BASE,a.get("href"))
            if href in found:
                continue
            found.add(href)
            try:
                out.append(parse(href,soup(href)))
            except Exception:
                continue
    return [p for p in out if p.get("title")]

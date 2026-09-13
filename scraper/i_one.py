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
    # I-ONE item pages use the performer and work title in a heading such as
    # `柳瀬 さき 「ずっとそばにいて」`. The global HTML <title> is not useful.
    title=None
    talent=[]
    for node in s.select("h1,h2,h3"):
        t=clean(node.get_text(" ",strip=True))
        m=re.search(r"(.+?)\s*[「『](.+?)[」』]",t)
        if m and "アイドルワン" not in t:
            talent=[m.group(1).strip()]
            title=m.group(2).strip()
            break
    if not title:
        # Search the item content before falling back to the first heading.
        for m in re.finditer(r"([^「『<>]{1,40})\s*[「『]([^」』]{1,100})[」』]",txt):
            performer,work=m.group(1).strip(),m.group(2).strip()
            if performer and work and "アイドルワン" not in performer and work not in {"次回作","制作中"}:
                talent=[performer]
                title=work
                break
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
    if not title:
        heading=s.find("h1") or s.find("h2")
        title=clean(heading.get_text(" ",strip=True) if heading else "")
        if "アイドルワン" in title:
            title=code or url.rstrip("/").split("/")[-1]
    return add_common_tags({
        "maker":MAKER,"maker_id":ID,"title":title,"release_date":date,
        "product_code":code,"talent":talent,"source_url":url,"source_checked_at":now(),
    })


def scrape():
    urls={BASE,BASE+"/release_date"}
    found=set(); out=[]
    for u in urls:
        try: s=soup(u)
        except Exception: continue
        for a in s.select('a[href*="/item/"]'):
            href=urljoin(BASE,a.get("href"))
            if not re.search(r"/item/\d+/?$",href) or href in found: continue
            found.add(href)
            try: out.append(parse(href,soup(href)))
            except Exception: continue
    return [p for p in out if p.get("title")]

from __future__ import annotations
import re
from urllib.parse import urljoin, urlparse, parse_qs
from scraper.base import clean,parse_japanese_date,now,add_common_tags
from scraper.http import soup

BASE="https://www.i-one-net.com"
MAKER="ラインコミュニケーションズ / I-ONE"
ID="i-one"

CATEGORIES=(
    "スレンダー系", "グラマー系", "いもうと系", "お姉さま系", "癒し系", "ドキドキ系", "清楚系",
    "スレンダー", "グラマー", "いもうと", "お姉さま", "癒し", "ドキドキ", "清楚",
)

def clean_performer(value):
    text=clean(value).strip(" ・|｜:：")
    for cat in CATEGORIES:
        text=re.sub(rf"(?:^|[ ・|｜]+){re.escape(cat)}(?=$|[ ・|｜]+)", " ", text)
    text=re.sub(r"\s+", " ", text).strip(" ・|｜:：")
    text=re.sub(r"^[ー―–—-]+\s*", "", text).strip()
    return text

def find_dmm_link(s):
    for a in s.select("a[href]"):
        href=str(a.get("href") or "").strip()
        if not href:
            continue
        full=urljoin(BASE,href)
        low=full.lower()
        if "dmm.com" not in low and "fanza" not in low:
            continue
        cid=""
        for pat in (r"[?&]cid=([a-z0-9_\-]+)",r"/cid/([a-z0-9_\-]+)",r"/cid=([a-z0-9_\-]+)",r"/(?:mono|product|detail)/([a-z0-9_\-]+)(?:[/?#]|$)"):
            m=re.search(pat,full,re.I)
            if m:
                cid=m.group(1)
                break
        if not cid:
            try:
                q=parse_qs(urlparse(full).query)
                cid=(q.get("cid") or [""])[0]
            except Exception:
                pass
        return full,cid
    return None,None

def parse(url, s):
    txt=clean(s.get_text(" ",strip=True))
    title=None; talent=[]
    for node in s.select("h1,h2,h3"):
        t=clean(node.get_text(" ",strip=True))
        m=re.search(r"(.+?)\s*[「『](.+?)[」』]",t)
        if m and "アイドルワン" not in t:
            performer=clean_performer(m.group(1)); work=m.group(2).strip()
            if performer and work and work not in {"次回作","制作中","発売中","新作"}:
                talent=[performer]; title=work; break
    if not title:
        candidates=[]
        for m in re.finditer(r"([^「『<>]{1,50})\s*[「『]([^」』]{1,100})[」』]",txt):
            performer=clean_performer(m.group(1)); work=m.group(2).strip()
            if performer and work and "アイドルワン" not in performer and work not in {"次回作","制作中","発売中","新作"}:
                candidates.append((performer,work))
        for performer,work in candidates:
            if len(performer) <= 20:
                talent=[performer]; title=work; break
        if not title and candidates:
            talent=[candidates[0][0]]; title=candidates[0][1]
    date=parse_japanese_date(txt); code=None
    for pat in [r"(?:型番|品番|商品番号|Model)\s*[:：]?\s*([A-Z0-9-]{5,})",r"\b(L[A-Z0-9-]{6,})\b"]:
        m=re.search(pat,txt,re.I)
        if m: code=m.group(1); break
    if not title:
        heading=s.find("h1") or s.find("h2")
        title=clean(heading.get_text(" ",strip=True) if heading else "")
        if "アイドルワン" in title: title=code or url.rstrip("/").split("/")[-1]
    if talent:
        cleaned=clean_performer(talent[0]); talent=[cleaned] if cleaned else []
    dmm_url,dmm_cid=find_dmm_link(s)
    item={"maker":MAKER,"maker_id":ID,"title":title,"release_date":date,"product_code":code,"talent":talent,"source_url":url,"source_checked_at":now()}
    if dmm_url: item["source_dmm_url"]=dmm_url
    if dmm_cid: item["source_dmm_cid"]=dmm_cid
    return add_common_tags(item)

def scrape():
    urls={BASE,BASE+"/release_date"}; found=set(); out=[]
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

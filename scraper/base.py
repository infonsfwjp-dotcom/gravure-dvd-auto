from __future__ import annotations
import re
from datetime import datetime, timezone

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def parse_japanese_date(text: str):
    patterns = [r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"]
    for pat in patterns:
        m = re.search(pat, text or "")
        if m:
            y, mo, d = map(int, m.groups())
            try: return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError: return None
    return None

def status_for_date(release_date: str|None):
    if not release_date: return "unknown"
    from datetime import date
    return "released" if date.fromisoformat(release_date) <= date.today() else "upcoming"

def now(): return datetime.now(timezone.utc).isoformat()

def add_common_tags(p: dict):
    tags=[]
    if p.get("release_date"):
        y,m,_=map(int,p["release_date"].split("-"))
        tags += [f"{y}年", f"{y}年{m}月", f"{y}年{m}月発売"]
    if p.get("maker"): tags.append(p["maker"])
    if p.get("brand"): tags.append(p["brand"])
    p["tags"]=list(dict.fromkeys(tags)); p["status"]=status_for_date(p.get("release_date")); return p

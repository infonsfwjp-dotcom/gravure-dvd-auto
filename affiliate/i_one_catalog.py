from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
API_URL = "https://api.dmm.com/affiliate/v3/ItemList"
API_ID = os.getenv("DMM_API_ID", "")
AFFILIATE_ID = os.getenv("DMM_AFFILIATE_ID", "")


def norm(s: str) -> str:
    return re.sub(r"[\s　「」『』（）()\-ー・:：/／.。,，!?！？]+", "", str(s or "")).lower()


def api_items(params):
    try:
        r = requests.get(API_URL, params=params, timeout=30)
        if r.status_code >= 400:
            return []
        return r.json().get("result", {}).get("items", []) or []
    except Exception:
        return []


def dmm_match(code, title, model, release):
    if not API_ID or not AFFILIATE_ID:
        return None
    base = {
        "api_id": API_ID,
        "affiliate_id": AFFILIATE_ID,
        "site": "FANZA",
        "service": "mono",
        "floor": "dvd",
        "gte_date": f"{(release - timedelta(days=7)).isoformat()}T00:00:00",
        "lte_date": f"{(release + timedelta(days=7)).isoformat()}T23:59:59",
        "sort": "date",
        "mono_stock": "reserve",
        "hits": 100,
        "offset": 1,
        "output": "json",
    }
    for keyword in (code, title, model):
        if not keyword:
            continue
        items = api_items({**base, "keyword": keyword})
        for item in items:
            raw = norm(json.dumps(item, ensure_ascii=False))
            item_code = norm(" ".join(str(item.get(k) or "") for k in ("maker_product", "product_id", "content_id", "cid")))
            item_title = norm(item.get("title") or "")
            maker_ok = any(x in raw for x in (norm("ラインコミュニケーションズ"), norm("I-ONE"), norm("アイドルワン")))
            if norm(code) in item_code or (maker_ok and (norm(title) in item_title or (model and norm(model) in item_title))):
                return item
    return None


def parse_detail(url, start, end):
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    cm = re.search(r"品番\s*[：:]\s*([A-Z0-9-]+)", text, re.I)
    dm = re.search(r"発売日\s*[：:]\s*(\d{4})/(\d{1,2})/(\d{1,2})", text)
    if not cm or not dm:
        return None
    release = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
    if not (start <= release <= end):
        return None
    code = cm.group(1).upper()
    og = soup.find("meta", attrs={"property": "og:title"})
    raw_title = (og.get("content") if og else "") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    title = re.sub(r"\s*[|｜].*$", "", raw_title).strip()
    title = re.sub(r"\s*〖[^〗]*〗", "", title).strip()
    model_m = re.search(r"モデル名\s*[：:]\s*([^\n]{1,80}?)(?:\s+商品詳細|\s+ファイル内容|\s+発売日)", text)
    model = model_m.group(1).strip() if model_m else ""
    return code, release, title, model, url


def main():
    if not DATA.exists():
        return
    products = json.loads(DATA.read_text(encoding="utf-8"))
    existing_codes = {norm(p.get("product_code")) for p in products if p.get("product_code")}
    start = date.today() - timedelta(days=30)
    end = date.today() + timedelta(days=180)
    base = "https://i-one.tv/content/?maker=line-communications&page={}"
    seen = set()
    details = []
    for page in range(1, 4):
        try:
            r = requests.get(base.format(page), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        except requests.RequestException:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/content/detail/" not in href:
                continue
            url = requests.compat.urljoin(r.url, href)
            if url not in seen:
                seen.add(url)
                details.append(url)

    added = 0
    for url in details:
        parsed = parse_detail(url, start, end)
        if not parsed:
            continue
        code, release, title, model, source_url = parsed
        if norm(code) in existing_codes:
            continue
        matched = dmm_match(code, title, model, release)
        if matched:
            item_title = str(matched.get("title") or title).strip()
            product_code = str(matched.get("maker_product") or matched.get("product_id") or code).strip()
            affiliate_url = str(matched.get("affiliateURL") or "")
            dmm_url = str(matched.get("URL") or "")
            talent = [model] if model else []
        else:
            item_title = title or (f"{model} {code}" if model else code)
            product_code = code
            affiliate_url = ""
            dmm_url = ""
            talent = [model] if model else []
        products.append({
            "maker": "ラインコミュニケーションズ / I-ONE",
            "maker_id": "i-one",
            "title": item_title,
            "release_date": release.isoformat(),
            "product_code": product_code,
            "jan": "",
            "talent": talent,
            "source_url": source_url,
            "affiliate_url": affiliate_url,
            "dmm_url": dmm_url,
            "affiliate_match_status": "matched" if affiliate_url else "unmatched",
            "status": "upcoming" if release >= date.today() else "released",
            "tags": [f"{release.year}年", release.strftime("%Y-%m"), f"{release.strftime('%Y-%m')}発売", "ラインコミュニケーションズ / I-ONE"],
        })
        existing_codes.add(norm(code))
        added += 1

    products.sort(key=lambda p: (p.get("release_date") or "", p.get("maker") or "", p.get("title") or ""), reverse=True)
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"i-one official catalog added={added}")
    print(f"products total={len(products)}")


if __name__ == "__main__":
    main()

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from requests_oauthlib import OAuth1
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
BEFORE = ROOT / "data/products_before.json"
STATE = ROOT / "data/x_posted.json"
API_URL = "https://api.x.com/2/tweets"


def key(p):
    raw = "|".join(str(p.get(k) or "") for k in ("maker_id", "product_code", "jan", "title", "release_date"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def required(name):
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Missing GitHub Actions secret: {name}")
    return value


def text_for(p):
    title = str(p.get("title") or "新作DVD")
    maker = str(p.get("maker") or "")
    date = str(p.get("release_date") or "")
    talent = "、".join(p.get("talent") or [])
    url = str(p.get("affiliate_url") or "")
    lines = ["【新作グラビアDVD】", title]
    if talent:
        lines.append(f"出演：{talent}")
    if date:
        lines.append(f"発売日：{date}")
    if maker:
        lines.append(f"メーカー：{maker}")
    if url:
        lines.append(f"FANZA：{url}")
    lines.append("#グラビアDVD #新作DVD")
    text = "\n".join(lines)
    return text[:275] if len(text) > 280 else text


def post(text):
    auth = OAuth1(required("X_API_KEY"), required("X_API_KEY_SECRET"), required("X_ACCESS_TOKEN"), required("X_ACCESS_TOKEN_SECRET"))
    r = requests.post(API_URL, auth=auth, json={"text": text}, timeout=30)
    r.raise_for_status()
    return r.json().get("data", {}).get("id", "")


def main():
    current = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []
    before = json.loads(BEFORE.read_text(encoding="utf-8")) if BEFORE.exists() else []
    before_keys = {key(p) for p in before}
    posted = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    changed = False
    for p in current:
        k = key(p)
        if k in before_keys or k in posted:
            continue
        # Prefer posts with a confirmed FANZA affiliate URL; this avoids dead purchase links.
        if p.get("affiliate_match_status") != "matched" or not p.get("affiliate_url"):
            posted[k] = {"status": "pending", "title": p.get("title"), "release_date": p.get("release_date")}
            changed = True
            continue
        tweet_id = post(text_for(p))
        posted[k] = {"status": "posted", "tweet_id": tweet_id, "title": p.get("title"), "release_date": p.get("release_date")}
        changed = True
    if changed:
        STATE.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

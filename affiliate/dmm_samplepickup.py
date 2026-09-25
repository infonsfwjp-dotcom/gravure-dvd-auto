from __future__ import annotations

"""Refresh LCDV-41448 sample images from DMM's numbered samplepickup pages.

Checks num=1 through num=15 on each site deployment, keeps only distinct
real image assets that can be extracted from those DMM pages, and writes the
available URLs to data/products.json.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"
CID = "n_691lcdv41448"
BASE = f"https://www.dmm.com/mono/dvd/-/detail/samplepickup/=/cid={CID}/num={{}}/"
IMAGE_RE = re.compile(r"\.(?:jpe?g|png|webp)(?:[?#]|$)", re.I)


def is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def main() -> None:
    products = json.loads(DATA.read_text(encoding="utf-8"))
    product = next((p for p in products if p.get("product_code") == "LCDV-41448"), None)
    if not product:
        raise SystemExit("LCDV-41448 not found in data/products.json")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; gravure-dvd-auto/1.0)",
        "Referer": "https://www.dmm.com/",
    })
    found: list[str] = []
    hashes: set[str] = set()

    for number in range(1, 16):
        page_url = BASE.format(number)
        try:
            response = session.get(page_url, timeout=20)
            if response.status_code >= 400:
                print(f"num={number}: unavailable (HTTP {response.status_code})")
                continue

            candidates: list[str] = []
            if is_image(response.content):
                candidates.append(response.url or page_url)
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup.select("img[src], img[data-src], meta[property='og:image'][content]"):
                    raw = tag.get("src") or tag.get("data-src") or tag.get("content") or ""
                    absolute = urljoin(response.url or page_url, raw.strip())
                    if absolute.startswith("https://") and IMAGE_RE.search(absolute):
                        candidates.append(absolute)
                # DMM may embed the sample asset URL in script/JSON markup.
                for raw in re.findall(r"""https?:\\?/\\?/[^"'\\s<>]+?\\.(?:jpg|jpeg|png|webp)(?:\\?[^"'\\s<>]*)?""", response.text, re.I):
                    candidates.append(raw.replace("\\/", "/"))

            accepted = False
            for candidate in candidates:
                try:
                    image_response = session.get(candidate, timeout=20)
                    if image_response.status_code != 200 or not is_image(image_response.content):
                        continue
                    digest = hashlib.sha256(image_response.content).hexdigest()
                    if digest in hashes:
                        continue
                    hashes.add(digest)
                    found.append(candidate)
                    accepted = True
                    break
                except requests.RequestException:
                    continue
            print(f"num={number}: {'image found' if accepted else 'no usable image'}")
        except requests.RequestException as exc:
            print(f"num={number}: request failed ({exc})")

    product["sample_image_urls"] = found
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"LCDV-41448: saved {len(found)} distinct DMM sample images from num=1..15")


if __name__ == "__main__":
    main()

from __future__ import annotations

"""Refresh LCDV-41448 sample images from DMM's numbered samplepickup pages.

Checks num=1 through num=15, extracts image URLs actually present in each
response, validates the downloaded bytes, deduplicates by content hash, and
writes only verified URLs to data/products.json.
"""
import hashlib
import html
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
IMAGE_RE = re.compile(r"\.(?:jpe?g|png|gif|webp)(?:[?#]|$)", re.I)
IMAGE_URL_RE = re.compile(
    r"""(?:https?:)?//[^\\"'\s<>]+?\.(?:jpe?g|png|gif|webp)(?:\?[^\\"'\s<>]*)?|(?:/|\.\.?/)[^\\"'\s<>]+?\.(?:jpe?g|png|gif|webp)(?:\?[^\\"'\s<>]*)?""",
    re.I,
)


def is_image(data: bytes) -> bool:
    return (
        data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )


def normalize_url(raw: str, page_url: str) -> str | None:
    raw = html.unescape(raw.strip()).replace("\\/", "/")
    if not raw or raw.startswith(("data:", "javascript:", "#")):
        return None
    absolute = urljoin(page_url, raw)
    if absolute.startswith("https://"):
        return absolute
    return None


def extract_candidates(page_text: str, page_url: str, number: int) -> list[str]:
    soup = BeautifulSoup(page_text, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = normalize_url(raw, page_url)
        if url and url not in seen:
            seen.add(url)
            candidates.append(url)

    # Read image-related attributes, including lazy-load and responsive-image variants.
    attrs = (
        "src", "data-src", "data-original", "data-lazy-src", "data-image",
        "data-url", "href", "content", "srcset", "data-srcset",
    )
    for tag in soup.find_all(True):
        for attr in attrs:
            value = tag.get(attr)
            if not value:
                continue
            if attr in ("srcset", "data-srcset"):
                for item in value.split(","):
                    add(item.strip().split()[0])
            elif attr == "style":
                for match in re.findall(r"url\\((?:['\"]?)(.*?)(?:['\"]?)\\)", value, re.I):
                    add(match)
            else:
                add(value)
        style = tag.get("style", "")
        for match in re.findall(r"url\\((?:['\"]?)(.*?)(?:['\"]?)\\)", style, re.I):
            add(match)

    # Some pages embed the actual asset URL in inline JavaScript or JSON.
    for raw in IMAGE_URL_RE.findall(page_text):
        add(raw)

    # Prefer the numbered sample asset when its real URL is present in the response.
    expected = f"5125lcdv41448jp-{number}"
    candidates.sort(key=lambda url: (
        0 if expected.lower() in url.lower() else
        1 if "5125lcdv41448jp-" in url.lower() else
        2 if "lcdv41448" in url.lower() else 3
    ))
    return candidates


def main() -> None:
    products = json.loads(DATA.read_text(encoding="utf-8"))
    product = next((p for p in products if p.get("product_code") == "LCDV-41448"), None)
    if not product:
        raise SystemExit("LCDV-41448 not found in data/products.json")

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.dmm.com/",
    })
    found: list[str] = []
    hashes: set[str] = set()

    for number in range(1, 16):
        page_url = BASE.format(number)
        try:
            response = session.get(page_url, timeout=25)
            content_type = response.headers.get("Content-Type", "")
            if response.status_code >= 400:
                print(f"num={number}: unavailable (HTTP {response.status_code})")
                continue

            if is_image(response.content):
                candidates = [response.url or page_url]
            else:
                candidates = extract_candidates(response.text, response.url or page_url, number)

            accepted = False
            for candidate in candidates:
                try:
                    image_response = session.get(
                        candidate, headers={"Referer": response.url or page_url}, timeout=25
                    )
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
            print(
                f"num={number}: {'image found' if accepted else 'no usable image'} "
                f"(HTTP {response.status_code}, {content_type or 'unknown content type'}, "
                f"{len(candidates)} candidates)"
            )
        except requests.RequestException as exc:
            print(f"num={number}: request failed ({exc})")

    product["sample_image_urls"] = found
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"LCDV-41448: saved {len(found)} distinct verified DMM sample images from num=1..15")


if __name__ == "__main__":
    main()

import os
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

site = os.environ["SITE_URL"].rstrip("/") + "/"
url = urljoin(site, "products/i-one-LCDV-41448")
r = requests.get(url, timeout=20)
r.raise_for_status()
soup = BeautifulSoup(r.text, "html.parser")

if "LCDV-41448" not in r.text or "日下部式学習法" not in r.text:
    raise SystemExit("LCDV-41448 content missing")
if "JAN" in r.text:
    raise SystemExit("JAN must not be shown")

imgs = soup.select('img[alt*="サンプル画像"]')
if len(imgs) < 1:
    raise SystemExit("No DMM/FANZA sample images are displayed")

def image_ok(u):
    x = requests.get(urljoin(site, u), timeout=20)
    if x.status_code != 200 or len(x.content) < 1024:
        return False, x.status_code, len(x.content), x.headers.get("content-type", "")
    b = x.content
    magic = (
        b.startswith(b"\xff\xd8\xff") or
        b.startswith(b"\x89PNG\r\n\x1a\n") or
        b.startswith(b"GIF87a") or b.startswith(b"GIF89a") or
        (b.startswith(b"RIFF") and b[8:12] == b"WEBP")
    )
    return magic, x.status_code, len(b), x.headers.get("content-type", "")

for i, img in enumerate(imgs, 1):
    src = img.get("src", "")
    ok, status, size, ct = image_ok(src)
    if not ok:
        raise SystemExit(f"Sample image {i} failed: {src} status={status} type={ct} bytes={size}")
print(f"Verified {len(imgs)} sample images as real image bytes")

cover = soup.select_one("img.cover")
if not cover:
    raise SystemExit("Cover image missing")
ok, status, size, ct = image_ok(cover.get("src", ""))
if not ok:
    raise SystemExit(f"Cover image failed: status={status} type={ct} bytes={size}")
print(f"Verified cover image as real image bytes ({size} bytes)")

video = soup.find(href=lambda x: isinstance(x, str) and "dmm.co.jp/litevideo/" in x)
if not video:
    video = soup.find(src=lambda x: isinstance(x, str) and "dmm.co.jp/litevideo/" in x)
if not video:
    raise SystemExit("DMM sample video link missing")
print("Verified DMM sample video link")

for marker in ("product-shell", "product-hero", "sample-gallery", "FREE SAMPLE", "SAMPLE GALLERY"):
    if marker not in r.text:
        raise SystemExit(f"Visual section marker missing: {marker}")
print("Verified LCDV-41448 visual layout markers")

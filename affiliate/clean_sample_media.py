from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/products.json"

# Common site-navigation/advertising assets that can be returned alongside
# real sample images by FANZA/official product pages.
BAD_TOKENS = (
    "slider-left", "slider-right", "logo", "dmmbooks", "nav1_", "nav2_",
    "nav3_", "nav4_", "but_tw", "but_fb", "but_pk", "but_li", "but_pi",
    "header", "footer", "banner", "bg_", "background", "icon", "arrow",
)


def keep_image(value: str) -> bool:
    if not value.startswith(("http://", "https://")):
        return False
    path = urlparse(value).path.lower()
    name = path.rsplit("/", 1)[-1]
    return not any(token in name for token in BAD_TOKENS)


def main() -> None:
    if not DATA.exists():
        return
    products = json.loads(DATA.read_text(encoding="utf-8"))
    changed = 0
    for product in products:
        images = product.get("sample_image_urls") or []
        filtered = []
        for image in images:
            if image not in filtered and keep_image(str(image)):
                filtered.append(str(image))
        filtered = filtered[:8]
        if filtered != images:
            product["sample_image_urls"] = filtered
            changed += 1
    DATA.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sample media cleanup changed={changed}")


if __name__ == "__main__":
    main()

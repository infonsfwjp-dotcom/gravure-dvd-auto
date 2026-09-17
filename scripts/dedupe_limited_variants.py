from __future__ import annotations
import json
import re
from pathlib import Path

DATA = Path("data/products.json")

def base_title(title: str) -> str:
    s = str(title or "")
    s = re.sub(r"【[^】]*限定[^】]*】", "", s)
    s = re.sub(r"\s*\(?(?:数量)?限定\)?", "", s, flags=re.I)
    s = re.sub(r"\s*チェキ(?:付き|付)?", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_limited_cheki(p: dict) -> bool:
    title = str(p.get("title") or "")
    code = str(p.get("product_code") or "")
    return "チェキ" in title or ("限定" in title and code.lower().endswith("tk"))

def key(p: dict) -> tuple:
    return (p.get("maker_id", ""), p.get("release_date", ""), base_title(p.get("title", "")))

def main() -> None:
    if not DATA.exists():
        return
    products = json.loads(DATA.read_text(encoding="utf-8"))
    normal_keys = {key(p) for p in products if not is_limited_cheki(p)}
    filtered = [p for p in products if not (is_limited_cheki(p) and key(p) in normal_keys)]
    DATA.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"limited_cheki_removed={len(products) - len(filtered)} total={len(filtered)}")

if __name__ == "__main__":
    main()

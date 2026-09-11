from __future__ import annotations
import json
from pathlib import Path
from scraper.i_one import scrape as scrape_i_one
from scraper.takeshobo import scrape as scrape_takeshobo
from scraper.spice_visual import scrape as scrape_spice

OUT=Path(__file__).resolve().parents[1]/"data/products.json"

def merge(items):
    old=json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    bykey={}
    for p in old+items:
        key=(p.get("maker_id"), p.get("product_code") or p.get("source_url") or p.get("title"))
        if key not in bykey: bykey[key]=p
        else:
            merged={**bykey[key], **{k:v for k,v in p.items() if v not in (None, "", [], {})}}
            bykey[key]=merged
    result=list(bykey.values())
    result.sort(key=lambda p:(p.get("release_date") or "9999-99-99", p.get("maker") or "", p.get("title") or ""), reverse=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"products={len(result)} newly_scraped={len(items)}")

def main():
    all_items=[]
    errors=[]
    for name,fn in [("i_one",scrape_i_one),("takeshobo",scrape_takeshobo),("spice_visual",scrape_spice)]:
        try: all_items.extend(fn())
        except Exception as e: errors.append(f"{name}: {e}")
    merge(all_items)
    if errors:
        Path("data/scrape_errors.log").write_text("\n".join(errors)+"\n",encoding="utf-8")
        print("scrape warnings:", *errors, sep="\n- ")

if __name__=="__main__": main()

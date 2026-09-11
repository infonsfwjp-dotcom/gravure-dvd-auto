from pathlib import Path
import json, sys
root=Path(__file__).resolve().parents[1]
data=root/'data/products.json'; dist=root/'dist'
errors=[]
try: products=json.loads(data.read_text(encoding='utf-8'))
except Exception as e: errors.append(f'products.json invalid: {e}'); products=[]
if not isinstance(products,list): errors.append('products.json must be an array')
for f in ['index.html','months/index.html','makers/index.html','robots.txt','sitemap.xml']:
    if not (dist/f).exists(): errors.append(f'missing dist/{f}')
for p in products:
    if not p.get('title'): errors.append('product without title')
    if p.get('release_date') and len(p['release_date']) < 10: errors.append(f'invalid release_date: {p.get("release_date")}')
if errors:
    print('\n'.join(errors)); sys.exit(1)
print(f'OK: {len(products)} products, required site files present')

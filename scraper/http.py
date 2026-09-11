from __future__ import annotations
import time, requests
from bs4 import BeautifulSoup
UA="Mozilla/5.0 (compatible; GravureReleaseBot/0.3; +https://github.com/)"

def get(url, retries=3):
    last=None
    for i in range(retries):
        try:
            r=requests.get(url,headers={"User-Agent":UA,"Accept-Language":"ja,en;q=0.8"},timeout=25)
            r.raise_for_status(); return r
        except Exception as e:
            last=e
            if i+1<retries: time.sleep(2**i)
    raise last

def soup(url): return BeautifulSoup(get(url).text,"lxml")

def text(s): return " ".join(s.stripped_strings) if s else ""

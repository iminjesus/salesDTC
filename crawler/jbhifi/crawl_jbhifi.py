#!/usr/bin/env python3
"""Crawl Samsung products from JB Hi-Fi (jbhifi.com.au) into a CSV.

    python crawl_jbhifi.py                         # default: site search for SAMSUNG
    python crawl_jbhifi.py --category tvs phones   # named categories (see CATEGORIES)
    python crawl_jbhifi.py --url "https://www.jbhifi.com.au/collections/tvs?query=samsung"
    python crawl_jbhifi.py --headed --dump-dir dump   # watch it run / keep raw payloads

Output columns
    crawled_at, category, brand, product_name, product_url, sku,
    on_sale, original_price, sale_price, discount_pct, currency

How it reads the page
    The storefront renders client side, so the page is driven with a real browser.
    Two extractors run and their results are merged by product URL:

      1. network  - every JSON response the page fetches is kept, then walked for
                    product-shaped records (a name-ish key next to a price-ish key).
                    This survives CSS changes and is the primary source.
      2. dom      - the rendered product cards are read as a fallback, for the case
                    where the data arrives server side instead of as JSON.

    If both come back empty, run with --dump-dir and send the dump: it holds the
    captured payloads and an HTML snapshot, which is what the field names have to
    be pinned against.

Be a good citizen: this pulls public listing pages at a walking pace (--delay),
identifies itself in the user agent, and is meant for price monitoring of a brand
you already sell. Check the site's terms and robots.txt before scheduling it.
"""
from __future__ import annotations

import argparse
import csv
import os
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                    # pragma: no cover
    sys.exit('playwright is not installed. Run:\n'
             '    pip install -r requirements.txt\n'
             '    python -m playwright install chromium')

BASE = 'https://www.jbhifi.com.au'

# Named categories -> listing URL. Add your own; the value is used as-is.
# 'search' is the plain site search the brand page links to.
CATEGORIES = {
    'search':      f'{BASE}/search?query={{brand}}',
    'tvs':         f'{BASE}/collections/tvs?query={{brand}}',
    'phones':      f'{BASE}/collections/mobile-phones?query={{brand}}',
    'tablets':     f'{BASE}/collections/tablets?query={{brand}}',
    'laptops':     f'{BASE}/collections/laptops?query={{brand}}',
    'audio':       f'{BASE}/collections/headphones?query={{brand}}',
    'wearables':   f'{BASE}/collections/smart-watches-fitness-trackers?query={{brand}}',
    'whitegoods':  f'{BASE}/collections/fridges?query={{brand}}',
    'laundry':     f'{BASE}/collections/washing-machines?query={{brand}}',
    'monitors':    f'{BASE}/collections/computer-monitors?query={{brand}}',
}

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/124.0 Safari/537.36 (price-monitor; contact: your-email@example.com)')

# Keys a product record may use. Lower-cased, punctuation stripped, for matching.
NAME_KEYS  = ('name', 'title', 'productname', 'displayname', 'producttitle')
SALE_KEYS  = ('saleprice', 'currentprice', 'finalprice', 'offerprice', 'nowprice',
              'sellingprice', 'priceincludingtax', 'price', 'pricevalue', 'minprice')
WAS_KEYS   = ('wasprice', 'originalprice', 'regularprice', 'listprice', 'rrp',
              'recommendedretailprice', 'strikethroughprice', 'compareatprice',
              'priceBeforeDiscount', 'baseprice', 'ticketprice')
SALE_FLAGS = ('onsale', 'ison sale', 'isonsale', 'isdiscounted', 'hasdiscount',
              'ispromotional', 'onpromotion', 'issale')
URL_KEYS   = ('url', 'producturl', 'link', 'permalink', 'slug', 'handle', 'path')
SKU_KEYS   = ('sku', 'skuid', 'productid', 'itemcode', 'code', 'objectid', 'id')
BRAND_KEYS = ('brand', 'brandname', 'manufacturer', 'vendor')

MONEY = re.compile(r'\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)')


# ── small helpers ───────────────────────────────────────────────────────────
def norm_key(k: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(k).lower())


def pick(d: dict, keys) -> object:
    """First value in d whose normalised key matches one of keys."""
    lookup = {norm_key(k): v for k, v in d.items()}
    for k in keys:
        v = lookup.get(norm_key(k))
        if v not in (None, '', [], {}):
            return v
    return None


def to_money(v) -> float | None:
    """Accept 1299, '1,299.00', '$1,299', {'amount': 1299}, ['$1299']."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    if isinstance(v, dict):
        for k in ('amount', 'value', 'price', 'centamount', 'displayvalue', 'formatted'):
            hit = pick(v, (k,))
            if hit is not None:
                out = to_money(hit)
                if out is not None:
                    # cent amounts come through as integers 100x too large
                    return out / 100 if norm_key(k) == 'centamount' else out
        return None
    if isinstance(v, (list, tuple)):
        for item in v:
            out = to_money(item)
            if out is not None:
                return out
        return None
    s = str(v).strip().replace(',', '').lstrip('$').strip()
    try:
        f = float(s)
    except ValueError:
        m = MONEY.search(str(v))
        if not m:
            return None
        f = float(m.group(1).replace(',', ''))
    return f if f > 0 else None


def abs_url(u) -> str:
    if not u:
        return ''
    u = str(u)
    if u.startswith('http'):
        return u
    if not u.startswith('/'):
        u = '/products/' + u              # bare slug / handle
    return BASE + u


def discount(original: float | None, sale: float | None) -> float | None:
    if not original or not sale or original <= 0 or sale >= original:
        return None
    return round((original - sale) / original * 100, 1)


# ── extractor 1: JSON captured from the network ─────────────────────────────
def looks_like_product(d: dict) -> bool:
    keys = {norm_key(k) for k in d}
    has_name = any(norm_key(k) in keys for k in NAME_KEYS)
    has_price = any(norm_key(k) in keys for k in SALE_KEYS + WAS_KEYS)
    return has_name and has_price


def walk(node, out: list, depth: int = 0):
    """Collect every product-shaped dict in an arbitrary JSON tree."""
    if depth > 12:
        return
    if isinstance(node, dict):
        if looks_like_product(node):
            out.append(node)
        for v in node.values():
            walk(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            walk(v, out, depth + 1)


def from_record(rec: dict) -> dict | None:
    name = pick(rec, NAME_KEYS)
    if not name or not isinstance(name, str):
        return None
    sale = to_money(pick(rec, SALE_KEYS))
    was = to_money(pick(rec, WAS_KEYS))
    if sale is None and was is None:
        return None
    if sale is None:
        sale, was = was, None
    if was is not None and was < sale:          # some feeds swap the two
        sale, was = was, sale
    flag = pick(rec, SALE_FLAGS)
    on_sale = bool(flag) if isinstance(flag, bool) else (was is not None and was > sale)
    brand = pick(rec, BRAND_KEYS)
    return {
        'brand': str(brand) if brand else '',
        'product_name': name.strip(),
        'product_url': abs_url(pick(rec, URL_KEYS)),
        'sku': str(pick(rec, SKU_KEYS) or ''),
        'on_sale': on_sale,
        'original_price': was if was is not None else sale,
        'sale_price': sale,
        'discount_pct': discount(was, sale),
        'source': 'network',
    }


# ── extractor 2: the rendered cards ─────────────────────────────────────────
DOM_JS = r"""
() => {
  const seen = new Set(), out = [];
  // A product card is the smallest block that holds a /products/ link and a price.
  for (const a of document.querySelectorAll('a[href*="/products/"]')) {
    let card = a, hops = 0;
    while (card && hops < 6 && !/\$\s*\d/.test(card.innerText || '')) {
      card = card.parentElement; hops++;
    }
    if (!card) continue;
    const href = a.getAttribute('href');
    if (!href || seen.has(href)) continue;
    seen.add(href);

    const text = card.innerText || '';
    const name = (a.getAttribute('aria-label') || a.innerText || '').trim().split('\n')[0]
              || (card.querySelector('h1,h2,h3,h4,[class*="title" i],[class*="name" i]')
                  ?.innerText || '').trim();

    // Struck-through / "was" price, if the card shows one.
    let wasText = '';
    for (const el of card.querySelectorAll('s, del, [class*="was" i], [class*="strike" i], [class*="rrp" i], [class*="compare" i]')) {
      if (/\$\s*\d/.test(el.innerText || '')) { wasText = el.innerText; break; }
    }
    const prices = (text.match(/\$\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?/g) || []);
    out.push({ href, name, wasText, prices, text: text.slice(0, 400) });
  }
  return out;
}
"""


def from_dom(card: dict) -> dict | None:
    name = (card.get('name') or '').strip()
    prices = [to_money(p) for p in card.get('prices') or []]
    prices = [p for p in prices if p]
    if not name or not prices:
        return None
    was = to_money(card.get('wasText'))
    if was:
        sale = min(p for p in prices if p != was) if any(p != was for p in prices) else was
    else:
        sale = prices[0]
        # two prices and no explicit markup: assume higher one is the was price
        was = max(prices) if len(prices) > 1 and max(prices) > sale else None
    if was is not None and was <= sale:
        was = None
    return {
        'brand': '',
        'product_name': name,
        'product_url': abs_url(card.get('href')),
        'sku': '',
        'on_sale': was is not None,
        'original_price': was if was is not None else sale,
        'sale_price': sale,
        'discount_pct': discount(was, sale),
        'source': 'dom',
    }


# ── page driving ────────────────────────────────────────────────────────────
def harvest(page, payloads: list, url: str, args, dump: Path | None) -> list[dict]:
    print(f'  open {url}', flush=True)
    payloads.clear()
    page.goto(url, wait_until='domcontentloaded', timeout=args.timeout * 1000)
    try:
        page.wait_for_selector('a[href*="/products/"]', timeout=args.timeout * 1000)
    except Exception:
        print('    no product links appeared (blocked, or the layout changed)')

    # Scroll until the list stops growing - the listing pages load as you go.
    last, stable = 0, 0
    for i in range(args.max_scrolls):
        page.mouse.wheel(0, 4000)
        time.sleep(args.delay)
        count = page.evaluate('document.querySelectorAll(\'a[href*="/products/"]\').length')
        if count == last:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last = count
    print(f'    {last} product links, {len(payloads)} json responses')

    rows = []
    for body in payloads:
        found = []
        walk(body, found)
        for rec in found:
            row = from_record(rec)
            if row:
                rows.append(row)
    for card in page.evaluate(DOM_JS):
        row = from_dom(card)
        if row:
            rows.append(row)

    if dump:
        stamp = re.sub(r'[^a-z0-9]+', '-', url.lower())[-60:]
        (dump / f'page-{stamp}.html').write_text(page.content(), encoding='utf-8')
        (dump / f'payloads-{stamp}.json').write_text(
            json.dumps(payloads, ensure_ascii=False, indent=1)[:8_000_000], encoding='utf-8')
    return rows


def merge(rows: list[dict]) -> list[dict]:
    """One row per product; a network row wins over a dom row, and a row that
    knows the original price wins over one that does not."""
    best: dict[str, dict] = {}
    for r in rows:
        key = r['product_url'] or f"{r['product_name']}|{r['sale_price']}"
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        score = (r['source'] == 'network', r['discount_pct'] is not None, bool(r['sku']))
        cur_score = (cur['source'] == 'network', cur['discount_pct'] is not None, bool(cur['sku']))
        if score > cur_score:
            best[key] = r
    return list(best.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--brand', default='SAMSUNG',
                    help='brand to search for and filter on (default: SAMSUNG)')
    ap.add_argument('--category', nargs='*', default=['search'],
                    help='categories to crawl: ' + ', '.join(CATEGORIES) + ' (default: search)')
    ap.add_argument('--url', nargs='*', default=[],
                    help='explicit listing URLs, used instead of --category')
    ap.add_argument('--out', default='jbhifi_samsung.csv', help='output CSV path')
    ap.add_argument('--delay', type=float, default=1.5,
                    help='seconds between scrolls (default: 1.5)')
    ap.add_argument('--max-scrolls', type=int, default=40)
    ap.add_argument('--timeout', type=int, default=30, help='per-step timeout, seconds')
    ap.add_argument('--headed', action='store_true', help='show the browser')
    ap.add_argument('--browser-path', default=os.environ.get('CHROMIUM_PATH'),
                    help='Chromium executable to use, when Playwright cannot find its own '
                         '(also read from CHROMIUM_PATH)')
    ap.add_argument('--dump-dir', help='keep raw payloads and an HTML snapshot here')
    ap.add_argument('--no-brand-filter', action='store_true',
                    help='keep every product, not just the brand')
    args = ap.parse_args()

    def label(u: str) -> str:
        m = re.search(r'/([^/?]+)(?:\?|$)', u)
        return m.group(1) if m else u

    targets = [(label(u), u) for u in args.url] or [
        (c, CATEGORIES[c].format(brand=args.brand)) for c in args.category if c in CATEGORIES]
    unknown = [c for c in args.category if c not in CATEGORIES and not args.url]
    if unknown:
        print(f'unknown category: {", ".join(unknown)}', file=sys.stderr)
    if not targets:
        print('nothing to crawl', file=sys.stderr)
        return 2

    dump = Path(args.dump_dir) if args.dump_dir else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    all_rows: list[dict] = []
    payloads: list = []

    with sync_playwright() as pw:
        launch = {'headless': not args.headed}
        if args.browser_path:
            launch['executable_path'] = args.browser_path
        browser = pw.chromium.launch(**launch)
        ctx = browser.new_context(user_agent=UA, locale='en-AU',
                                  viewport={'width': 1440, 'height': 1000})
        page = ctx.new_page()

        def on_response(resp):
            ct = (resp.headers or {}).get('content-type', '')
            if 'json' not in ct.lower():
                return
            try:
                payloads.append(resp.json())
            except Exception:
                pass

        page.on('response', on_response)

        for name, url in targets:
            try:
                rows = harvest(page, payloads, url, args, dump)
            except Exception as exc:
                print(f'    failed: {exc}')
                continue
            for r in rows:
                r['category'] = name
                r['crawled_at'] = stamp
                r['currency'] = 'AUD'
            all_rows += rows
            time.sleep(args.delay)

        browser.close()

    rows = merge(all_rows)
    if not args.no_brand_filter:
        b = args.brand.lower()
        rows = [r for r in rows
                if b in r['product_name'].lower() or b in r['brand'].lower()
                or b in r['product_url'].lower()]
    rows.sort(key=lambda r: (r['category'], r['product_name']))

    cols = ['crawled_at', 'category', 'brand', 'product_name', 'product_url', 'sku',
            'on_sale', 'original_price', 'sale_price', 'discount_pct', 'currency']
    out = Path(args.out)
    with out.open('w', newline='', encoding='utf-8-sig') as f:   # utf-8-sig: Excel friendly
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({**r, 'on_sale': 'Y' if r['on_sale'] else 'N'})

    on_sale = sum(1 for r in rows if r['on_sale'])
    print(f'\n{len(rows)} products -> {out}  ({on_sale} on sale)')
    if not rows:
        print('Nothing was captured. Re-run with --dump-dir dump --headed and check the '
              'dump: the site may be blocking the browser, or the field names moved.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

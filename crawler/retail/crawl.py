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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                    # pragma: no cover
    sys.exit('playwright is not installed. Run:\n'
             '    pip install -r requirements.txt\n'
             '    python -m playwright install chromium')

# Everything site-specific lives here; the extraction below is shared. Each site
# filters by brand through its own facet parameter, so listing pages come back
# already filtered instead of relying on the name check afterwards.
SITES = {
    'jbhifi': {
        'base':          'https://www.jbhifi.com.au',
        'search':        '/search',
        'query_param':   'query',
        'brand_param':   'Brand',
        # /search?query=samsung&Brand=SAMSUNG
        'brand_value':   lambda b: b.upper(),
        'query_value':   lambda b: b.lower(),
        'link_selector': 'a[href*="/products/"]',
        'product_href':  r'/products/',
        'category_href': r'/collections/([a-z0-9\-]+)',
        'category_path': '/collections/{slug}',
        'categories': {
            'tvs':        '/collections/tvs',
            'phones':     '/collections/mobile-phones',
            'tablets':    '/collections/tablets',
            'laptops':    '/collections/laptops',
            'audio':      '/collections/headphones',
            'wearables':  '/collections/smart-watches-fitness-trackers',
            'whitegoods': '/collections/fridges',
            'laundry':    '/collections/washing-machines',
            'monitors':   '/collections/computer-monitors',
        },
    },
    'harveynorman': {
        'base':          'https://www.harveynorman.com.au',
        'search':        '/catalogsearch/result/',
        'query_param':   'q',
        'brand_param':   'af',
        # /catalogsearch/result/?q=samsung&af=def_general_brand%3ASamsung
        'brand_value':   lambda b: f'def_general_brand:{b.title()}',
        'query_value':   lambda b: b.lower(),
        # Product urls here are not a reliable shape, so every link is considered
        # and the price-bearing card around it decides. The wait/count selector
        # tracks the price elements instead, which is what grows as you scroll.
        'link_selector': 'a[href]',
        'wait_selector': '[class*="price" i], [data-price], [itemprop="price"]',
        'product_href':  r'',
        'category_href': r'/([a-z0-9\-]+/[a-z0-9\-]+)/?$',
        'category_path': '/{slug}',
        'categories': {},
    },
}

# Filled in from the chosen site at start-up.
SITE = SITES['jbhifi']
BASE = SITE['base']
BRAND_PARAM = SITE['brand_param']
LINK_SELECTOR = SITE['link_selector']
WAIT_SELECTOR = SITE['link_selector']


def use_site(name: str) -> None:
    global SITE, BASE, BRAND_PARAM, LINK_SELECTOR, WAIT_SELECTOR, CATEGORIES
    SITE = SITES[name]
    BASE = SITE['base']
    BRAND_PARAM = SITE['brand_param']
    LINK_SELECTOR = SITE['link_selector']
    WAIT_SELECTOR = SITE.get('wait_selector') or SITE['link_selector']
    CATEGORIES = {'search': SITE['search'], **SITE['categories']}

# Named categories -> listing URL. Add your own; the value is used as-is.
# 'search' is the plain site search the brand page links to.
CATEGORIES = {'search': SITE['search'], **SITE['categories']}

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
# In priority order: a field actually called sku beats the search engine's own id.
SKU_KEYS   = ('sku', 'skuid', 'itemcode', 'productcode', 'productid', 'objectid', 'id')
CAT_KEYS   = ('category', 'categories', 'productcategory', 'primarycategory',
              'categorypath', 'categoryname', 'breadcrumb', 'departmentname')
BRAND_KEYS = ('brand', 'brandname', 'manufacturer', 'vendor')
MODEL_KEYS = ('model', 'modelnumber', 'modelcode', 'modelname', 'mpn',
              'manufacturerpartnumber', 'partnumber', 'productmodel')

# The product page prints it as "MODEL: SM-A376BZAAATS_11901362224 SKU: 892910"
MODEL_TEXT = re.compile(r'\bmodel\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9._/\-]{3,})', re.I)

MONEY = re.compile(r'\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)')


def listing_url(url: str, brand: str) -> str:
    """Add the search term and the brand facet, leaving any the url already has.

        /search                      -> /search?query=samsung&Brand=SAMSUNG
        /collections/tvs?query=x     -> /collections/tvs?query=x&Brand=SAMSUNG
    """
    parts = urlsplit(url if url.startswith('http') else BASE + url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params.setdefault(SITE['query_param'], SITE['query_value'](brand))
    params.setdefault(SITE['brand_param'], SITE['brand_value'](brand))
    return urlunsplit(parts._replace(query=urlencode(params)))


# ── small helpers ───────────────────────────────────────────────────────────
def norm_key(k: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(k).lower())


def pick(d: dict, keys) -> object:
    """First value in d whose normalised key matches one of keys."""
    return pick_with_key(d, keys)[0]


def pick_with_key(d: dict, keys) -> tuple:
    """As pick(), but also returns the source key - so the CSV can say where a
    value such as the sku actually came from."""
    lookup = {norm_key(k): (k, v) for k, v in d.items()}
    for k in keys:
        hit = lookup.get(norm_key(k))
        if hit and hit[1] not in (None, '', [], {}):
            return hit[1], hit[0]
    return None, ''


def flatten_text(v) -> str:
    """'TVs' | ['Home','TVs'] | [{'name':'TVs'}] -> 'Home > TVs'"""
    if v is None:
        return ''
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return flatten_text(pick(v, ('name', 'title', 'label', 'value')))
    if isinstance(v, (list, tuple)):
        parts = [flatten_text(x) for x in v]
        return ' > '.join(p for p in parts if p)
    return str(v)


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
        u = '/' + u                       # bare slug / handle
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
    sku, sku_key = pick_with_key(rec, SKU_KEYS)
    return {
        'brand': str(brand) if brand else '',
        'product_name': name.strip(),
        'product_url': abs_url(pick(rec, URL_KEYS)),
        'sku': str(sku or ''),
        'sku_field': sku_key,
        'model': flatten_text(pick(rec, MODEL_KEYS)),
        'site_category': flatten_text(pick(rec, CAT_KEYS)),
        'on_sale': on_sale,
        'original_price': was if was is not None else sale,
        'sale_price': sale,
        'discount_pct': discount(was, sale),
        'source': 'network',
    }


# ── extractor 2: the rendered cards ─────────────────────────────────────────
DOM_JS = r"""
(SELECTOR) => {
  const RE = /\$\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?/g;
  const seen = new Set(), out = [];
  // A product card is the smallest block that holds a /products/ link and a price.
  for (const a of document.querySelectorAll(SELECTOR)) {
    let card = a, hops = 0;
    while (card && hops < 6 && !RE.test(card.innerText || '')) {
      RE.lastIndex = 0; card = card.parentElement; hops++;
    }
    RE.lastIndex = 0;
    // Climbing as far as the page body means this link just happens to sit on a
    // page that has prices somewhere - navigation, footer - not a product card.
    if (!card || card === document.body || card === document.documentElement) continue;
    const href = a.getAttribute('href');
    if (!href || seen.has(href)) continue;
    seen.add(href);

    const text = card.innerText || '';
    const name = (a.getAttribute('aria-label') || a.innerText || '').trim().split('\n')[0]
              || (card.querySelector('h1,h2,h3,h4,[class*="title" i],[class*="name" i]')
                  ?.innerText || '').trim();

    // Struck-through / ticket / "was" price, if the card shows one.
    let wasText = '';
    for (const el of card.querySelectorAll('s, del, [class*="was" i], [class*="strike" i], [class*="ticket" i], [class*="rrp" i], [class*="compare" i]')) {
      if (/\$\s*\d/.test(el.innerText || '')) { wasText = el.innerText; break; }
    }

    // Prices carried by elements that say they are prices. A badge like
    // "Save $2,000" is not one of these, which is what keeps it out of the
    // price list even when it sits right next to the real price.
    const priced = [];
    for (const el of card.querySelectorAll(
        '[class*="price" i], [data-price], [itemprop="price"], [class*="amount" i]')) {
      const t = (el.innerText || '').trim();
      if (!/\$\s*\d/.test(t)) continue;
      if (el.querySelector('[class*="price" i], [data-price], [itemprop="price"]'))
        continue;                       // outer wrapper; the inner ones carry the values
      const cls = ((el.className || '') + ' ' + (el.getAttribute('data-testid') || '')
                   + ' ' + (el.parentElement?.className || '')).toLowerCase();
      priced.push({ text: t, cls, struck: !!el.closest('s, del') });
    }

    // Every money token with the text around it, so "$100 OFF" can be told apart
    // from an actual price.
    const tokens = [];
    let m;
    RE.lastIndex = 0;
    while ((m = RE.exec(text)) !== null) {
      const end = m.index + m[0].length;
      // Clip each window at the neighbouring '$', so a word belonging to the next
      // price ("... $2,449 SAVE $500") is not read as belonging to this one.
      const before = text.slice(Math.max(0, m.index - 24), m.index).split('$').pop();
      const after = text.slice(end, end + 24).split('$')[0];
      tokens.push({ value: m[0], before, after });
    }
    out.push({ href, name, wasText, tokens, priced, text: text.slice(0, 400) });
  }
  return out;
}
"""


# A discount amount rather than a price. The two shapes read in opposite
# directions: "$100 OFF" has the word after it, "SAVE $500" has it before.
OFF_AFTER = re.compile(r'^\W*(off|cashback|credit|bonus|back)\b', re.I)
OFF_BEFORE = re.compile(r'\b(save|saved|saving|savings|less|off|bonus|cashback|'
                        r'credit|gift|voucher|redeem)\W*$', re.I)
# Class names that say which side of a discount a price element is on.
WAS_CLASS = re.compile(r'was|strike|rrp|ticket|compare|before|original|regular', re.I)
NOW_CLASS = re.compile(r'now|sale|special|current|final|today|our', re.I)
SAVE_CLASS = re.compile(r'save|saving|discount|bonus|cashback|credit', re.I)


def from_dom(card: dict) -> dict | None:
    name = (card.get('name') or '').strip()

    # Preferred path: elements that declare themselves as prices.
    was = now = None
    plain = []
    for el in card.get('priced') or []:
        v = to_money(el.get('text'))
        if not v or SAVE_CLASS.search(el.get('cls') or ''):
            continue
        if el.get('struck') or WAS_CLASS.search(el.get('cls') or ''):
            was = v if was is None else max(was, v)
        elif NOW_CLASS.search(el.get('cls') or ''):
            now = v if now is None else min(now, v)
        else:
            plain.append(v)
    if now is None and plain:
        now = min(plain) if was is None else min([p for p in plain if p <= was] or plain)
    if was is None and len(plain) > 1:
        was = max(plain)
    if now is not None and name:
        if was is not None and was <= now:
            was = None
        return {
            'brand': '', 'product_name': name,
            'product_url': abs_url(card.get('href')), 'sku': '', 'sku_field': '',
            'model': (MODEL_TEXT.search(card.get('text') or '') or [None, ''])[1],
            'site_category': '',
            'on_sale': was is not None,
            'original_price': was if was is not None else now,
            'sale_price': now,
            'discount_pct': discount(was, now),
            'source': 'dom',
        }

    # Fallback: read the money out of the card's text.
    prices, offs = [], []
    for tok in card.get('tokens') or []:
        v = to_money(tok.get('value'))
        if not v:
            continue
        is_off = (OFF_AFTER.search(tok.get('after') or '')
                  or OFF_BEFORE.search(tok.get('before') or ''))
        (offs if is_off else prices).append(v)
    if not name or not prices:
        return None

    was = to_money(card.get('wasText'))
    if was is None and len(prices) > 1:
        was = max(prices)                       # no markup: the highest is the ticket price
    if was is not None:
        # The sale price is the highest price below the ticket price - not the
        # lowest, which would pick up a "$100 OFF" badge that slipped through.
        below = [p for p in prices if p < was]
        sale = max(below) if below else was
        # Backstop: if a candidate is exactly the gap, it was the discount amount.
        if below and (was - sale) in offs + prices and sale != max(below, default=sale):
            sale = max(below)
    else:
        sale = prices[0]
    if was is not None and was <= sale:
        was = None
    return {
        'brand': '',
        'product_name': name,
        'product_url': abs_url(card.get('href')),
        'sku': '',
        'sku_field': '',
        'model': (MODEL_TEXT.search(card.get('text') or '') or [None, ''])[1],
        'site_category': '',
        'on_sale': was is not None,
        'original_price': was if was is not None else sale,
        'sale_price': sale,
        'discount_pct': discount(was, sale),
        'source': 'dom',
    }


# ── category discovery ──────────────────────────────────────────────────────
# The categories are whatever the site itself offers for this brand, so they are
# read off the seed search page rather than hard-coded: the refinement links in
# the markup, plus any facet counts in the JSON the page fetched.
CAT_LINKS_JS = r"""
() => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    const text = (a.innerText || a.getAttribute('aria-label') || '').trim();
    if (href && text && text.length < 60) out.push({ href, text });
  }
  return out;
}
"""


def facet_categories(payloads: list) -> list[str]:
    """Facet blocks look like {"category": {"TVs": 42, "Phones": 17}}."""
    found, seen = [], set()

    def walk_facets(node, key_hint='', depth=0):
        if depth > 10 or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            for v in node:
                walk_facets(v, key_hint, depth + 1)
            return
        for k, v in node.items():
            hint = str(k).lower()
            if isinstance(v, dict) and v and 'categor' in hint:
                # {name: count} map
                if all(isinstance(x, (int, float)) for x in v.values()):
                    for name in v:
                        if name not in seen:
                            seen.add(name)
                            found.append(str(name))
                    continue
            walk_facets(v, hint, depth + 1)

    walk_facets(payloads)
    return found


def discover_categories(page, payloads: list, brand: str, limit: int) -> list[tuple]:
    """Return [(label, url)] for the categories the site shows for this brand."""
    cats, seen = [], set()

    for link in page.evaluate(CAT_LINKS_JS):
        href, text = link['href'], link['text']
        if SITE['product_href'] and re.search(SITE['product_href'], href.split('?')[0]):
            continue                              # that is a product, not a category
        m = re.search(SITE['category_href'], href.split('?')[0])
        if not m:
            continue
        slug = m.group(1)
        if slug in seen or slug.split('/')[-1] in ('all', 'sale', 'home'):
            continue
        seen.add(slug)
        cats.append((text or slug, listing_url(abs_url(href), brand)))

    # Facet names have no url of their own; map them onto a search refinement.
    for name in facet_categories(payloads):
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
        if not slug or slug in seen:
            continue
        seen.add(slug)
        cats.append((name, listing_url(BASE + SITE['category_path'].format(slug=slug),
                                       brand)))

    return cats[:limit]


# ── page driving ────────────────────────────────────────────────────────────
def harvest(page, payloads: list, url: str, args, dump: Path | None) -> tuple:
    """Load a listing page and pull the products out of it.

    Returns (rows, stopped). Ctrl+C during the scroll does not throw the page
    away: scrolling stops and whatever has loaded so far is still extracted.
    """
    print(f'  open {url}', flush=True)
    payloads.clear()
    page.goto(url, wait_until='domcontentloaded', timeout=args.timeout * 1000)
    try:
        page.wait_for_selector(WAIT_SELECTOR, timeout=args.timeout * 1000)
    except Exception:
        print('    no product links appeared (blocked, or the layout changed)')

    # Scroll until the list stops growing - the listing pages load as you go.
    last, stable, stopped = 0, 0, False
    try:
        for _ in range(args.max_scrolls):
            page.mouse.wheel(0, 4000)
            time.sleep(args.delay)
            count = page.evaluate(
                'sel => document.querySelectorAll(sel).length', WAIT_SELECTOR)
            if count == last:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last = count
    except KeyboardInterrupt:
        stopped = True
        print('\n    stopped scrolling - extracting what is loaded')
    print(f'    {last} price elements, {len(payloads)} json responses')

    rows = []
    for body in payloads:
        found = []
        walk(body, found)
        for rec in found:
            row = from_record(rec)
            if row:
                rows.append(row)
    for card in page.evaluate(DOM_JS, LINK_SELECTOR):
        row = from_dom(card)
        if row:
            rows.append(row)

    if not rows and dump is None:
        dump = Path('dump')               # nothing found: keep the evidence anyway
        dump.mkdir(parents=True, exist_ok=True)
    if dump:
        stamp = re.sub(r'[^a-z0-9]+', '-', url.lower())[-60:]
        (dump / f'page-{stamp}.html').write_text(page.content(), encoding='utf-8')
        (dump / f'payloads-{stamp}.json').write_text(
            json.dumps(payloads, ensure_ascii=False, indent=1)[:8_000_000], encoding='utf-8')
    if not rows:
        print('    nothing matched on this page:')
        diagnose(page, payloads, dump)
    return rows, stopped


def diagnose(page, payloads: list, dump: Path | None) -> None:
    """Print what the page actually looks like, so an empty result can be pinned
    down from the console alone instead of needing the dump shipped anywhere."""
    try:
        info = page.evaluate(r"""
        () => {
          const hrefs = [...document.querySelectorAll('a[href]')]
            .map(a => a.getAttribute('href')).filter(Boolean);
          const uniq = [...new Set(hrefs)];
          const money = (document.body.innerText.match(/\$\s*[0-9][0-9,]*/g) || []);
          const classes = new Set();
          for (const el of document.querySelectorAll('[class*="price" i]'))
            (el.className || '').split(/\s+/).forEach(c => c && classes.add(c));
          return { links: hrefs.length, sample: uniq.slice(0, 12),
                   money: money.slice(0, 8), priceClasses: [...classes].slice(0, 8),
                   title: document.title,
                   bodyStart: (document.body.innerText || '').trim().slice(0, 200) };
        }
        """)
    except Exception as exc:
        print(f'    could not inspect the page: {exc}')
        return

    print(f"    page title : {info['title']}")
    print(f"    links      : {info['links']}")
    for h in info['sample']:
        print(f'      {h[:100]}')
    print(f"    prices seen: {', '.join(info['money']) or 'none'}")
    print(f"    price css  : {', '.join(info['priceClasses']) or 'none'}")
    if not info['money']:
        print(f"    body starts: {info['bodyStart'][:120]!r}")
    for body in payloads[:4]:
        if isinstance(body, dict):
            print(f"    json keys  : {', '.join(list(body)[:10])}")
    if dump:
        print(f'    raw page and payloads written to {dump}')



def merge(rows: list[dict]) -> list[dict]:
    """One row per product. The same product shows up several times - once per
    extractor, and once per category page it appears on - so identity falls back
    from sku to url to name: a dom row has no sku, and a network row may carry no
    url, which is why matching on a single field left duplicates behind."""
    best: dict[str, dict] = {}
    alias: dict[str, str] = {}          # every identity seen -> the key it merged into

    def identities(r):
        out = []
        if r['sku']:
            out.append('sku:' + r['sku'])
        if r['product_url']:
            out.append('url:' + r['product_url'].rstrip('/').lower())
        out.append('name:' + re.sub(r'\s+', ' ', r['product_name']).strip().lower())
        return out

    ID_FIELDS = ('sku', 'product_url', 'site_category', 'brand', 'sku_field', 'model')
    PRICE_FIELDS = ('on_sale', 'original_price', 'sale_price', 'discount_pct')

    def combine(cur: dict, new: dict) -> dict:
        """Fold new into cur. Identity fields fill gaps; price fields are taken as a
        set from whichever row actually knows about a discount - a card showing a
        struck-through price beats a feed that only carries the current price."""
        for f in ID_FIELDS:
            if not cur.get(f) and new.get(f):
                cur[f] = new[f]
        cur_knows = cur.get('discount_pct') is not None
        new_knows = new.get('discount_pct') is not None
        if new_knows and not cur_knows:
            for f in PRICE_FIELDS:
                cur[f] = new[f]
        elif new_knows and cur_knows and cur.get('source') != 'network' \
                and new.get('source') == 'network':
            for f in PRICE_FIELDS:     # the feed beats a card read out of rendered text
                cur[f] = new[f]
        elif not cur_knows and not new_knows and new.get('sale_price') \
                and new['sale_price'] < cur.get('sale_price', float('inf')):
            for f in PRICE_FIELDS:
                cur[f] = new[f]
        if cur.get('source') != 'network' and new.get('source') == 'network':
            cur['source'] = 'network'
        return cur

    for r in rows:
        ids = identities(r)
        key = next((alias[i] for i in ids if i in alias), ids[0])
        cur = best.get(key)
        best[key] = r if cur is None else combine(cur, r)
        for i in ids:
            alias[i] = key
    return list(best.values())


COLUMNS = ['crawled_at', 'category', 'brand', 'product_name', 'product_url', 'sku',
           'sku_field', 'model', 'on_sale', 'original_price', 'sale_price',
           'discount_pct', 'currency']


def write_csv(path: Path, rows: list[dict], brand: str, brand_filter: bool,
              max_discount: float = 100.0) -> tuple:
    """Write everything gathered so far and return (row count, path written).

    Called after every page, so an interrupted run still leaves a usable file.
    On Windows the swap into place is refused while the CSV is open in Excel, so
    it retries and then falls back to a sibling file rather than losing the rows -
    the returned path is what the caller should keep writing to.
    """
    rows = merge(rows)
    rows = drop_impossible_discounts(rows, max_discount)
    if brand_filter:
        rows = keep_brand(rows, brand)
    rows.sort(key=lambda r: (r['category'], r['product_name']))
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='', encoding='utf-8-sig') as f:   # utf-8-sig: Excel friendly
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({**r, 'on_sale': 'Y' if r['on_sale'] else 'N'})
    # Swap into place so the CSV on disk is never half-written, even if killed here.
    for attempt in range(6):
        try:
            tmp.replace(path)
            return len(rows), path
        except PermissionError:
            if attempt == 0:
                print(f'    {path.name} is locked - is it open in Excel? retrying')
            time.sleep(0.5 * (attempt + 1))

    alt = path.with_name(f'{path.stem}-{datetime.now().strftime("%H%M%S")}{path.suffix}')
    try:
        tmp.replace(alt)
    except OSError as exc:
        print(f'    could not save: {exc}')
        return len(rows), path
    print(f'    {path.name} is still locked; writing to {alt.name} from here on')
    return len(rows), alt


def drop_impossible_discounts(rows: list[dict], limit: float) -> list[dict]:
    """A discount far past anything a retailer runs means a savings or bonus amount
    was read as the price ("$7,944  SAVE $2,000" coming out as 7,944 -> 2,000).
    The higher number is the price in that case, so keep it and drop the discount."""
    hit = []
    for r in rows:
        if r.get('discount_pct') and r['discount_pct'] > limit:
            hit.append(r)
            r['sale_price'] = r['original_price']
            r['on_sale'] = False
            r['discount_pct'] = None
    if hit:
        print(f'\n  {len(hit)} product(s) showed a discount over {limit:g}% - that is '
              'almost always a savings')
        print('  amount read as the price, so the discount was dropped. Worth a look:')
        for r in hit[:10]:
            print(f"    {r['product_name'][:60]}  {r['product_url']}")
    return rows


def keep_brand(rows: list[dict], brand: str) -> list[dict]:
    b = brand.lower()
    return [r for r in rows
            if b in r['product_name'].lower() or b in r['brand'].lower()
            or b in r['product_url'].lower()]


def fill_models(page, rows: list[dict], args) -> int:
    """Open each product page that has no model code and read it off the page.

    Listing cards carry the sku but usually not the model, which is printed on the
    product page as "MODEL: ... SKU: ...". One page load per product, so this is
    opt-in (--with-model).
    """
    todo = [r for r in rows if not r.get('model') and r.get('product_url')]
    if not todo:
        return 0
    print(f'\n  filling model codes from {len(todo)} product pages '
          f'(about {len(todo) * args.delay / 60:.0f} min)')
    filled = 0
    for i, r in enumerate(todo, 1):
        try:
            page.goto(r['product_url'], wait_until='domcontentloaded',
                      timeout=args.timeout * 1000)
            text = page.evaluate('document.body.innerText.slice(0, 4000)')
            m = MODEL_TEXT.search(text or '')
            if m:
                r['model'] = m.group(1)
                filled += 1
            time.sleep(args.delay)
        except KeyboardInterrupt:
            print('    stopped - keeping the models filled so far')
            break
        except Exception:
            continue
        if i % 25 == 0:
            print(f'    {i}/{len(todo)}')
    return filled


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--site', default='jbhifi', choices=sorted(SITES),
                    help='which retailer to crawl (default: jbhifi)')
    ap.add_argument('--brand', default='SAMSUNG',
                    help='brand to search for and filter on (default: SAMSUNG)')
    ap.add_argument('--category', nargs='*', default=[],
                    help='crawl these named categories instead of discovering them: '
                         + ', '.join(CATEGORIES))
    ap.add_argument('--no-discover', action='store_true',
                    help='only crawl the seed search page, skip category discovery')
    ap.add_argument('--max-categories', type=int, default=25,
                    help='cap on discovered categories (default: 25)')
    ap.add_argument('--url', nargs='*', default=[],
                    help='explicit listing URLs, used instead of --category')
    ap.add_argument('--out', help='output CSV path (default: <site>_<brand>.csv)')
    ap.add_argument('--delay', type=float, default=1.5,
                    help='seconds between scrolls (default: 1.5)')
    ap.add_argument('--max-scrolls', type=int, default=40)
    ap.add_argument('--timeout', type=int, default=30, help='per-step timeout, seconds')
    ap.add_argument('--headed', action='store_true', help='show the browser')
    ap.add_argument('--profile', metavar='DIR',
                    help='keep cookies in this folder between runs, so a check you '
                         'passed once is not asked again (e.g. --profile .profile)')
    ap.add_argument('--pause-on-block', action='store_true',
                    help='when a page comes back with no products, wait at the console '
                         'so you can deal with it in the browser yourself, then retry '
                         'that page. Use with --headed.')
    ap.add_argument('--browser-path', default=os.environ.get('CHROMIUM_PATH'),
                    help='Chromium executable to use, when Playwright cannot find its own '
                         '(also read from CHROMIUM_PATH)')
    ap.add_argument('--dump-dir', help='keep raw payloads and an HTML snapshot here')
    ap.add_argument('--with-model', action='store_true',
                    help='also open each product page to read its MODEL code '
                         '(one extra page load per product, so it is slow)')
    ap.add_argument('--max-discount', type=float, default=70.0,
                    help='reject a discount above this %% as a misread - the higher '
                         'number is kept as the price and the row is reported '
                         '(default: 70, use 100 to trust everything)')
    ap.add_argument('--no-brand-filter', action='store_true',
                    help='keep every product, not just the brand')
    args = ap.parse_args()
    use_site(args.site)
    if args.pause_on_block and not args.headed:
        print('--pause-on-block needs --headed, so there is a window to work in.',
              file=sys.stderr)
        return 2

    def label(u: str) -> str:
        m = re.search(r'/([^/?]+)(?:\?|$)', u)
        return m.group(1) if m else u

    if args.url:
        targets = [(label(u), u) for u in args.url]
    elif args.category:
        unknown = [c for c in args.category if c not in CATEGORIES]
        if unknown:
            print(f'unknown category: {", ".join(unknown)}', file=sys.stderr)
        targets = [(c, listing_url(CATEGORIES[c], args.brand))
                   for c in args.category if c in CATEGORIES]
    else:
        targets = [('search', listing_url(CATEGORIES['search'], args.brand))]
    if not targets:
        print('nothing to crawl', file=sys.stderr)
        return 2

    dump = Path(args.dump_dir) if args.dump_dir else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    out = Path(args.out or f'{args.site}_{args.brand.lower()}.csv')
    stamp = datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    all_rows: list[dict] = []
    payloads: list = []

    with sync_playwright() as pw:
        launch = {'headless': not args.headed}
        if args.browser_path:
            launch['executable_path'] = args.browser_path
        common = {'user_agent': UA, 'locale': 'en-AU',
                  'viewport': {'width': 1440, 'height': 1000}}
        if args.profile:
            # A persistent profile keeps cookies, so a check passed by hand once is
            # not asked again on the next category or the next run.
            browser = None
            ctx = pw.chromium.launch_persistent_context(args.profile, **launch, **common)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        else:
            browser = pw.chromium.launch(**launch)
            ctx = browser.new_context(**common)
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

        discovered_from = None
        queue = list(targets)
        done = set()
        interrupted = False

        while queue:
            name, url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            try:
                rows, stopped = harvest(page, payloads, url, args, dump)
                if not rows and args.pause_on_block and not stopped:
                    print('\n  This page returned nothing. If the browser is showing a')
                    print('  check to confirm you are human, complete it in the browser')
                    print('  window, then press Enter here to read the page again.')
                    print('  (--profile DIR keeps it from being asked every time.)')
                    try:
                        input('  press Enter to continue: ')
                        rows, stopped = harvest(page, payloads, url, args, dump)
                    except (EOFError, KeyboardInterrupt):
                        interrupted = True
                if stopped:
                    interrupted = True
            except KeyboardInterrupt:
                print('\n  stopped - keeping what has been collected')
                interrupted = True
                break
            except Exception as exc:
                print(f'    failed: {exc}')
                continue
            for r in rows:
                r['category'] = r.get('site_category') or name
                r['crawled_at'] = stamp
                r['currency'] = 'AUD'
            all_rows += rows
            saved, out = write_csv(out, all_rows, args.brand, not args.no_brand_filter,
                                   args.max_discount)
            print(f'    saved {saved} products so far -> {out}')
            if interrupted:
                break

            # After the first (seed) page, ask the site which categories it has
            # for this brand and queue them up one by one.
            if discovered_from is None and not args.no_discover and not args.url \
                    and not args.category:
                discovered_from = url
                found = discover_categories(page, payloads, args.brand,
                                            args.max_categories)
                print(f'\n  discovered {len(found)} categories:')
                for lbl, curl in found:
                    print(f'    - {lbl}')
                    queue.append((lbl, curl))
                print()
            try:
                time.sleep(args.delay)
            except KeyboardInterrupt:
                print('\n  stopped - keeping what has been collected')
                interrupted = True
                break

        if args.with_model and not interrupted:
            try:
                to_fill = merge(all_rows)
                if not args.no_brand_filter:
                    to_fill = keep_brand(to_fill, args.brand)
                n = fill_models(page, to_fill, args)
                print(f'  model code filled for {n} products')
                write_csv(out, all_rows, args.brand, not args.no_brand_filter,
                          args.max_discount)
            except KeyboardInterrupt:
                pass

        ctx.close()
        if browser is not None:
            browser.close()

    _, out = write_csv(out, all_rows, args.brand, not args.no_brand_filter,
                       args.max_discount)
    rows = merge(all_rows)
    rows = drop_impossible_discounts(rows, args.max_discount)
    if not args.no_brand_filter:
        rows = keep_brand(rows, args.brand)

    on_sale = sum(1 for r in rows if r['on_sale'])
    note = ' (stopped early)' if interrupted else ''
    print(f'\n{len(rows)} products -> {out}  ({on_sale} on sale){note}')
    fields = sorted({r['sku_field'] for r in rows if r.get('sku_field')})
    if fields:
        print(f"sku column taken from the site field(s): {', '.join(fields)}")
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r['category']] = by_cat.get(r['category'], 0) + 1
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f'  {n:5}  {cat}')
    if not rows:
        print('Nothing was captured. Re-run with --dump-dir dump --headed and check the '
              'dump: the site may be blocking the browser, or the field names moved.')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

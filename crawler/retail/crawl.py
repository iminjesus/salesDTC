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
    Four extractors run and their results are merged by product URL. Two of them
    read what the site states; two guess from shape:

      1. catalogue - the listing the storefront hands its own app, as JSON in the
                     page (__NEXT_DATA__) and in its XHRs. Model code, price and
                     the amount off, from the site's own records. Where a site
                     publishes it, it supersedes the two that guess.
      2. ld+json   - the schema.org ItemList the page publishes for search
                     engines: name, price, currency and the product url.
      3. network   - every JSON response the page fetches is kept, then walked for
                     product-shaped records (a name-ish key next to a price-ish key).
                     This survives CSS changes.
      4. dom       - the rendered product cards are read as a fallback, for the case
                     where the data arrives server side instead of as JSON.

    If both come back empty, run with --dump-dir and send the dump: it holds the
    captured payloads and an HTML snapshot, which is what the field names have to
    be pinned against.

Be a good citizen: this pulls public listing pages at a walking pace (--delay),
identifies itself in the user agent, and is meant for price monitoring of a brand
you already sell. It reads the site's robots.txt itself and skips any page that
file disallows (--ignore-robots overrides, deliberately); the site's terms are
still yours to check before scheduling it.
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
    # Samsung's own store. Every product on it is Samsung, so there is no brand
    # facet to add and nothing to filter out afterwards - `own_brand` turns both
    # off. Product urls here are not a shape worth pinning, so every link is
    # considered and the price-bearing card around it decides, the same posture
    # harveynorman needed.
    #
    # Every listing publishes a schema.org ItemList of its products, so that is
    # read as well as the cards and the payloads - see from_ld_json.
    #
    # The categories below were read off the site itself: every /au/x/all-x/
    # path it links to. A product page is /au/<group>/<kind>/<model-slug>/, so
    # the listings are the ones whose second segment starts with `all-`.
    'samsung': {
        'base':          'https://www.samsung.com/au',
        'search':        '/',
        'own_brand':      True,
        'ld_json':        True,
        'needs_code':     True,
        'all_categories': True,
        'query_param':   'searchvalue',
        'brand_param':   'brand',
        'brand_value':   lambda b: b.title(),
        'query_value':   lambda b: b.lower(),
        'link_selector': 'a[href]',
        'wait_selector': '[class*="price" i], [data-price], [itemprop="price"]',
        'product_href':  r'',
        'category_href': r'/au/([a-z0-9\-]+/all-[a-z0-9\-]+)/?$',
        'category_path': '/{slug}',
        'categories': {
            'phones':       '/smartphones/all-smartphones/',
            'tablets':      '/tablets/all-tablets/',
            'watches':      '/watches/all-watches/',
            'rings':        '/rings/all-rings/',
            'tvs':          '/tvs/all-tvs/',
            'monitors':     '/monitors/all-monitors/',
            'projectors':   '/projectors/all-projectors/',
            'audio':        '/audio-devices/all-audio-devices/',
            'audiosound':   '/audio-sound/all-audio-sound/',
            'fridges':      '/refrigerators/all-refrigerators/',
            'laundry':      '/washers-and-dryers/all-washers-and-dryers/',
            'dishwashers':  '/dishwashers/all-dishwashers/',
            'microwaves':   '/microwave-ovens/all-microwave-ovens/',
            'aircon':       '/air-conditioners/all-air-conditioners/',
            'vacuums':      '/vacuum-cleaners/all-vacuum-cleaners/',
            'memory':       '/memory-storage/all-memory-storage/',
            'packages':     '/appliance-packages/all-appliance-packages/',
            'mobileacc':    '/mobile-accessories/all-mobile-accessories/',
            'audioacc':     '/audio-accessories/all-audio-accessories/',
            'tvacc':        '/tv-accessories/all-tv-accessories/',
            'homeacc':      '/home-appliance-accessories/all-home-appliance-accessories/',
        },
    },
    # Harvey Norman. Its robots.txt disallows /catalogsearch/, which is exactly
    # what this entry used to be built on, so the run goes to the category
    # listings instead - every one of them read off the site itself and checked
    # against robots.txt.
    #
    # There is no brand facet worth guessing at on a category page, so its url
    # is used exactly as written (`plain_urls`) and the brand filter narrows the
    # products afterwards. The listing itself comes back as JSON inside the
    # page, which is where the products are read from - see catalogue_rows.
    'harveynorman': {
        'base':          'https://www.harveynorman.com.au',
        # The site's own search is disallowed by robots.txt, so this stands in
        # for it: --category search is that one listing.
        'search':        '/tv-blu-ray-home-theatre/tvs-by-type/qled-lcd-tvs',
        'plain_urls':    True,
        'catalogue':     True,
        'facet_path':    '/{brand}/993',
        'pagination_selector': 'nav[aria-label="Pagination"] a[href]',
        'query_param':   'q',
        'brand_param':   'af',
        'brand_value':   lambda b: f'def_general_brand:{b.title()}',
        'query_value':   lambda b: b.lower(),
        # Product urls here are not a reliable shape, so every link is considered
        # and the price-bearing card around it decides. The wait/count selector
        # tracks the price elements instead, which is what grows as you scroll.
        'link_selector': 'a[href]',
        'wait_selector': '[class*="price" i], [data-price], [itemprop="price"]',
        # A headless browser gets an empty challenge page here; a visible one is
        # served normally, so run with a window unless told otherwise.
        'needs_headed':  True,
        'product_href':  r'',
        # A category is /<group>/<kind> or /<group>/<by-something>/<kind>. A
        # product page ends .html, and a numeric last segment is a filtered view
        # (/oled-tvs/1065) - neither is a listing to queue, so the last segment
        # has to carry a letter and no dot.
        'category_href': r'/((?:[a-z0-9\-]+/){1,2}[a-z0-9\-]*[a-z][a-z0-9\-]*)/?$',
        'category_path': '/{slug}',
        # Read off the site's own footer navigation, which lists every category
        # in the store - 806 of them, from bathroom basins up. These are the
        # ones Samsung sells in, with the brand's own landing pages preferred
        # where it has one. `all_categories` queues them all when nothing is
        # named, which is also what keeps discovery from wandering into tiles
        # and towels.
        'all_categories': True,
        'categories': {
            'tvs_samsung':   '/tv-blu-ray-home-theatre/tvs-by-brand/samsung-tvs',
            'tvs_all':       '/tv-blu-ray-home-theatre/tvs-by-screen-size/all-tvs',
            'tvs_qled':      '/tv-blu-ray-home-theatre/tvs-by-type/qled-lcd-tvs',
            'soundbars':     '/tv-blu-ray-home-theatre/home-theatre-speakers/soundbars',
            'phones_samsung': '/mobile-phones-wearables/samsung-galaxy',
            'phones_all':    '/mobile-phones-wearables/mobile-phones',
            'phones_fold':   '/mobile-phones-wearables/mobile-phones/flip-fold-phones',
            'watches':       '/mobile-phones-wearables/smart-watches/samsung-watch',
            'earbuds':       '/headphones-audio-music/headphones/true-wireless-earbuds',
            'tablets':       '/computers-tablets/ipads-surface-tablets/samsung-tablets',
            'monitors':      '/computers-tablets/monitors/samsung-monitors',
            'ssds':          '/computers-tablets/hard-drives-storage/portable-ssds',
            'memory_cards':  '/computers-tablets/hard-drives-storage/memory-cards',
            'usb_drives':    '/computers-tablets/hard-drives-storage/usb-flash-drives',
            'fridges':       '/kitchen-appliances/appliances/fridges',
            'dishwashers':   '/kitchen-appliances/appliances/dishwashers',
            'microwaves':    '/kitchen-appliances/appliances/microwave-ovens',
            'cooktops':      '/kitchen-appliances/appliances/cooktops',
            'ovens':         '/kitchen-appliances/appliances/ovens',
            'washing':       '/vacuum-laundry-appliances/washing-machines-dryers/washing-machines',
            'dryers':        '/vacuum-laundry-appliances/washing-machines-dryers/dryers',
            'washer_dryers': '/vacuum-laundry-appliances/washing-machines-dryers/washer-dryer-combos',
            'vacuums_stick': '/vacuum-laundry-appliances/vacuum-cleaners/stick-vacuum-cleaners',
            'vacuums_robot': '/vacuum-laundry-appliances/vacuum-cleaners/robotic-vacuum-cleaners',
            'aircon':        '/heating-cooling-air-treatment/air-conditioning/split-system-airconditioners',
        },
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
    # Harvey Norman's brand filter is a path segment rather than a query
    # parameter - /kitchen-appliances/appliances/fridges/samsung/993, where 993
    # is the brand attribute, as the site's own facet links are written. A
    # category without it answers with its first page of every brand: 4 Samsung
    # fridges out of the 53 the facet holds.
    facet = SITE.get('facet_path')
    if facet:
        path = parts.path.rstrip('/')
        if brand.lower() not in path.lower():
            # A listing that already names the brand is the brand's listing.
            path += facet.format(brand=brand.lower())
        return urlunsplit(parts._replace(path=path, query=''))
    # Some sites want neither. A search term appended to a category listing is
    # at best noise and at worst a page that answers nothing, and a single-brand
    # store has no facet to narrow to the brand. A site whose category urls
    # carry no facet worth guessing at (`plain_urls`) is left alone the same
    # way, and the brand filter narrows its results afterwards instead.
    if SITE.get('own_brand') or SITE.get('plain_urls'):
        return urlunsplit(parts)
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
    u = str(u).strip()
    if u.startswith('http'):
        return u
    # javascript:void(0), mailto:, tel: - a control, not a place. Glued to the
    # base these became .../au/javascript:void(0), which then carried the
    # banner's "$2,000" into the file as a product called "Accept".
    if re.match(r'(?i)^(javascript|mailto|tel|sms|about|data|#)', u):
        return ''
    if not u.startswith('/'):
        u = '/' + u                       # bare slug / handle
    # A base can carry a path of its own - samsung.com/au - and a root-relative
    # href on that site already starts with it. Gluing the whole base on then
    # gives /au/au/..., which the site answers 404 and the run reports as "no
    # product links appeared (blocked, or the layout changed)": a wrong url
    # wearing the costume of a changed page.
    root = urlsplit(BASE)
    prefix = root.path.rstrip('/')
    if prefix and (u == prefix or u.startswith(prefix + '/')):
        return urlunsplit((root.scheme, root.netloc, u, '', ''))
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


# ── extractor 3: the page's own structured data ─────────────────────────────
# schema.org JSON-LD, which samsung.com/au publishes on every listing as an
# ItemList of Products. It is the site telling search engines what is on the
# page, so it is steadier than either the cards or the XHR payloads: name,
# price, currency, availability and the product url, and on the mobile
# categories the url carries ?modelCode=SM-F971BZGDATS - the same code the
# sales data is keyed on.
#
# It carries ONE price, with no was/now pair, so a discount cannot be read from
# it. The other two extractors still run and merge in whatever the cards show,
# which is where a sale price comes from when there is one.
# The model code, off the product url. Mobile listings put it in a query -
# ?modelCode=SM-F971BZGDATS - and everywhere else it is the tail of the slug:
# .../s90f-55-inch-oled-4k-vision-ai-smart-tv-qa55s90fawxxy/ is QA55S90FAWXXY.
# Checked against every product on the phones, TV, fridge and laundry listings:
# 97 of 97 give a code.
CAPACITY = re.compile(r'^\d+(gb|tb|mb|kg|l|w|cm|mm|inch)$')
# The two-letter heads Samsung actually hyphenates. Joining any two-letter token
# would read `...-smart-tv-qa55s90fawxxy` as TV-QA55S90FAWXXY, which is a word
# from the name stuck onto the code.
# Heads Samsung hyphenates. Joining any short token would read
# `...-smart-tv-qa55s90fawxxy` as TV-QA55S90FAWXXY, a word from the name stuck
# onto the code, so this is a list rather than a shape.
CODE_HEAD = {'sm', 'hw', 'ef', 'ej', 'et', 'gp', 'mu', 'muf', 'skk', 'vca',
             'bn', 'da97', 'da29', 'db', 'ue', 'ls', 'aa'}
CODE_REGION = {'sa', 'xy', 'xsa', 'au', 'ww', 'zs', 'xsg', 'xxy', 'apc'}


def code_from_url(url: str) -> str:
    m = re.search(r'[?&]modelCode=([A-Za-z0-9_-]+)', url or '')
    if m:
        return m.group(1).upper()
    path = (url or '').split('?')[0].rstrip('/')
    slug = [p for p in path.split('/') if p]
    if not slug:
        return ''
    parts = slug[-1].split('-')
    region = ''
    if len(parts) >= 2 and parts[-1] in CODE_REGION:
        region, parts = '/' + parts[-1].upper(), parts[:-1]
    if not parts:
        return ''
    last = parts[-1]
    if CAPACITY.match(last):
        return ''                          # `...-128gb` is the size, not the model
    head = parts[-2] if len(parts) >= 2 and parts[-2] in CODE_HEAD else ''
    # A hyphenated code can be short on its own - HW-Q930H/XY is `q930h`, five
    # characters - so the length a code has to reach is lower once a head is
    # carrying part of it.
    need = 3 if head else 8
    if not (len(last) >= need and re.search(r'\d', last)
            and re.search(r'[a-z0-9]', last)):
        return ''
    return ((head + '-' + last) if head else last).upper() + region


LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I)


def from_ld_json(html: str) -> list[dict]:
    """Every Product in the page's JSON-LD, as rows."""
    rows = []
    for block in LD_RE.findall(html or ''):
        try:
            data = json.loads(block)
        except Exception:
            continue                       # a malformed block is not a reason to stop
        # Not walk(): that collects dicts with a price beside a name, and a
        # schema.org Product keeps its price one level down in `offers`, so it
        # never matches. These are found by their own @type instead.
        found: list = []

        def hunt(node):
            if isinstance(node, dict):
                t = node.get('@type')
                if t == 'Product' or (isinstance(t, list) and 'Product' in t):
                    found.append(node)
                for v in node.values():
                    hunt(v)
            elif isinstance(node, list):
                for v in node:
                    hunt(v)

        hunt(data)
        for rec in found:
            offers = rec.get('offers') or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = to_money(offers.get('price'))
            name = rec.get('name')
            if not price or not name:
                continue
            url = abs_url(rec.get('url') or rec.get('@id'))
            code = code_from_url(url)
            rows.append({
                'brand': '',
                'product_name': str(name).strip(),
                'product_url': url,
                'sku': code,
                'sku_field': 'product url' if code else '',
                'model': code,
                'site_category': '',
                'on_sale': False,
                'original_price': price,
                'sale_price': price,
                'discount_pct': None,
                'source': 'ld+json',
            })
    return rows


# ── extractor 4: the storefront's own catalogue records ─────────────────────
# An Adobe Commerce storefront - Harvey Norman is one - hands its React app the
# listing it is about to draw, as JSON inside the page: a __NEXT_DATA__ script
# whose pageData.productsData.items are the products, each with the sku, the
# name, the url slug and a price_range.
#
# This is the catalogue, not a guess at it. It carries the model code as the
# sku (QA75LS03HEWXXY), the real sale price, and the discount as an amount off
# - so the was-price is arithmetic rather than a strikethrough that has to be
# found on screen. It is also complete: the cards are drawn lazily, so the DOM
# on a page that has not been scrolled holds a fraction of what this holds.
#
# The same records come back from the storefront's GraphQL calls as you page
# through a listing, so network payloads are read for the shape too.
NEXT_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S)


def catalogue_records(node, out: list | None = None, depth: int = 0) -> list:
    """Every dict carrying a sku beside a price_range, however deeply nested."""
    out = [] if out is None else out
    if depth > 14:
        return out
    if isinstance(node, dict):
        if node.get('sku') and isinstance(node.get('price_range'), dict):
            out.append(node)
        for v in node.values():
            catalogue_records(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            catalogue_records(v, out, depth + 1)
    return out


def from_catalogue(rec: dict) -> dict | None:
    name = rec.get('name')
    low = ((rec.get('price_range') or {}).get('minimum_price') or {})
    sale = to_money((low.get('final_price') or {}).get('value'))
    if not name or sale is None:
        return None
    # amount_off is off the original, not off the price being charged:
    # $2,295 with 700 off and 23.37% off reads back as 700/2995.
    off = to_money((low.get('discount') or {}).get('amount_off')) or 0.0
    was = sale + off if off > 0 else None
    slug = rec.get('url_key')
    url = (BASE + '/' + str(slug).lstrip('/') + (rec.get('url_suffix') or '')
           if slug else abs_url(pick(rec, URL_KEYS)))
    # No brand field on these records; the storefront writes the brand as the
    # first word of every product name ("Samsung 75-inch The Frame ...").
    first = str(name).strip().split(' ')[0]
    return {
        'brand': first if first.isalpha() else '',
        'product_name': str(name).strip(),
        'product_url': url,
        'sku': str(rec.get('sku')),
        'sku_field': 'sku',
        'model': str(rec.get('sku')),
        'site_category': '',
        'on_sale': off > 0,
        'original_price': was if was is not None else sale,
        'sale_price': sale,
        'discount_pct': discount(was, sale),
        'source': 'catalogue',
    }


def catalogue_counts(node, out: list | None = None, depth: int = 0) -> list:
    """Every page_info the listing publishes, with the matching total_count.

    The listing states how many products it has and over how many pages. A
    category of 400 fridges hands the page the first 40 of them, and without
    this the run would quietly report 4 Samsung fridges off page one and call
    the category done.
    """
    out = [] if out is None else out
    if depth > 14:
        return out
    if isinstance(node, dict):
        info = node.get('page_info')
        if isinstance(info, dict) and 'total_pages' in info:
            out.append({'total': node.get('total_count'),
                        'page': info.get('current_page'),
                        'pages': info.get('total_pages')})
        for v in node.values():
            catalogue_counts(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node:
            catalogue_counts(v, out, depth + 1)
    return out


def catalogue_rows(html: str, payloads: list) -> tuple[list[dict], dict]:
    """The listing's own product records, from the page and from its XHRs.

    Returns (rows, what the listing says it holds).
    """
    trees = []
    for block in NEXT_RE.findall(html or ''):
        try:
            trees.append(json.loads(block))
        except Exception:
            continue                   # a malformed block is not a reason to stop
    trees += payloads
    rows, seen, counts = [], set(), []
    for tree in trees:
        counts += catalogue_counts(tree)
        for rec in catalogue_records(tree):
            row = from_catalogue(rec)
            if row and (row['sku'], row['sale_price']) not in seen:
                seen.add((row['sku'], row['sale_price']))
                rows.append(row)
    # The listing's own count, not the widest number on the page: a facet
    # group counts products the listing is not showing.
    best = max(counts, key=lambda c: c.get('pages') or 0, default={})
    return rows, best


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
    // innerText is empty for anything not on screen, and a site's categories
    // usually live in a mega-menu that is closed - so a link the page plainly
    // carries was being passed over for having no visible words. The title,
    // the label and finally the slug stand in for them.
    const text = (a.innerText || a.getAttribute('aria-label')
                  || a.getAttribute('title') || a.textContent || '').trim()
      || (href.split('?')[0].replace(/\/+$/, '').split('/').pop() || '')
           .replace(/-/g, ' ');
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


# ── what the site asks ──────────────────────────────────────────────────────
# The README has always said to check robots.txt. Saying so is not the same as
# doing it, and this crawler's own harveynorman entry was built on
# /catalogsearch/, which that file disallows - nobody noticed because nothing
# looked. So the crawler reads it itself, once per run, before it fetches.
#
# urllib.robotparser is not enough here. It compares paths with startswith, so
# every wildcard rule silently passes: Harvey Norman's "Disallow: /*1065" (the
# filtered listings) would read as allowed. The matcher below follows the rules
# the search engines publish - `*` is any run of characters, `$` anchors the
# end, and of the rules that match, the longest pattern wins, Allow breaking a
# tie - so a wildcard rule is honoured instead of ignored.
ROBOTS = {'rules': None, 'read': False, 'skipped': 0}


class Robots:
    def __init__(self, text: str):
        # robots.txt is read in groups: one or more User-agent lines, then the
        # rules that belong to them, until the next User-agent line starts a
        # new group. Only the groups addressed to everyone are kept - a rule
        # written for one named crawler is not ours to obey or to ignore.
        self.rules: list[tuple[str, bool]] = []
        agents: list[str] = []
        buf: list[tuple[str, bool]] = []
        naming = False

        def flush():
            if any(a == '*' for a in agents):
                self.rules.extend(buf)

        for line in text.splitlines():
            line = line.split('#', 1)[0].strip()
            if ':' not in line:
                continue
            field, _, value = line.partition(':')
            field, value = field.strip().lower(), value.strip()
            if field == 'user-agent':
                if not naming and agents:          # the group before is done
                    flush()
                    agents, buf = [], []
                agents.append(value.lower())
                naming = True
            elif field in ('allow', 'disallow'):
                naming = False
                if value:
                    buf.append((value, field == 'allow'))
        flush()

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        anchored = pattern.endswith('$')
        body = pattern[:-1] if anchored else pattern
        rx = ''.join('.*' if c == '*' else re.escape(c) for c in body)
        return re.match(rx + ('$' if anchored else ''), path) is not None

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        best: tuple[int, bool] | None = None
        for pattern, allowed in self.rules:
            if self._matches(pattern, path):
                key = (len(pattern.rstrip('$')), allowed)
                if best is None or key > best:
                    best = key
        return True if best is None else best[1]


def robots_for(page, say=print):
    """The site's robots.txt, read once through the same browser session.

    page.request, not a fetch() inside the page: the browser's own request
    context carries the session's cookies but is not bound by the page's
    origin, so a blank starting tab can still read it.
    """
    if ROBOTS['read']:
        return ROBOTS['rules']
    ROBOTS['read'] = True
    root = urlsplit(BASE)
    txt = ''
    try:
        reply = page.request.get(f'{root.scheme}://{root.netloc}/robots.txt',
                                 timeout=20_000)
        if reply.ok:
            txt = reply.text()
    except Exception as exc:
        say(f'  could not read robots.txt ({type(exc).__name__})')
    if not txt.strip():
        say('  robots.txt could not be read, so no page is checked against it')
        return None
    rules = Robots(txt)
    ROBOTS['rules'] = rules
    say(f'  robots.txt read: {len(rules.rules)} rule(s) for everyone, '
        f'checked before each page')
    return rules


def robots_allows(page, url: str, say=print) -> bool:
    rules = robots_for(page, say)
    return True if rules is None else rules.allows(url)


# ── page driving ────────────────────────────────────────────────────────────
def harvest(page, payloads: list, url: str, args, dump: Path | None) -> tuple:
    """Load a listing page and pull the products out of it.

    Returns (rows, stopped). Ctrl+C during the scroll does not throw the page
    away: scrolling stops and whatever has loaded so far is still extracted.
    """
    # An already-open tab is read where it stands. Navigating it would throw
    # away the very thing it is being read for - a page a person loaded, past
    # whatever check stood in front of it.
    if getattr(args, 'open_tabs', False):
        print(f'  read {page.url}', flush=True)
    else:
        print(f'  open {url}', flush=True)
        payloads.clear()
        page.goto(url, wait_until='domcontentloaded',
                  timeout=args.timeout * 1000)
        try:
            page.wait_for_selector(WAIT_SELECTOR, timeout=args.timeout * 1000)
        except Exception:
            print('    no product links appeared (blocked, or the layout '
                  'changed)')

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
    if SITE.get('ld_json'):
        found = from_ld_json(page.content())
        print(f'    {len(found)} product(s) in the page\'s structured data')
        rows += found
    pages: list[str] = []
    if SITE.get('catalogue'):
        found, says = catalogue_rows(page.content(), payloads)
        print(f'    {len(found)} product(s) in the listing\'s own catalogue data')
        if (says.get('pages') or 1) > 1:
            print(f"    the listing says it holds {says.get('total')} product(s) "
                  f"over {says['pages']} pages")
            # Its own pagination links, read off the page rather than a guess at
            # the url shape. Queued by the caller; already-seen urls drop out.
            try:
                pages = [u for u in page.evaluate(
                    'sel => [...document.querySelectorAll(sel)].map(a => a.href)',
                    SITE.get('pagination_selector') or 'nav[aria-label="Pagination"] a[href]')
                    if u and u.startswith('http')]
            except Exception:
                pages = []
            print(f'    {len(pages)} page link(s) to follow'
                  if pages else
                  '    no page links on it, so only this page was read')
        if found:
            # The catalogue is the site's own record of what is on the page.
            # Next to it the card reader's output is noise - every link on
            # this site is a candidate, so the cookie banner and the cart
            # come back as products - and it holds nothing the catalogue
            # lacks.
            guessed = len(rows)
            rows = found
            if guessed:
                print(f'    {guessed} guessed row(s) dropped: the catalogue '
                      f'says what is on the page')
    if SITE.get('needs_code'):
        # Every link on the page is a candidate here, and the card reader finds
        # a price near enough to the cookie banner, the cart and the nav to call
        # them products - 36 rows of "Accept" and "Cart" on four listings, every
        # one of them flagged as on sale. A product url carries a model code;
        # none of those do, so that is the test.
        #
        # It is a test for the two extractors that guess. A JSON-LD row sits
        # inside a schema.org Product because the site put it there, so it is a
        # product whatever its url looks like - and applying the test to those
        # as well threw away 56 of 62 appliance accessories and every soundbar,
        # whose codes are shapes the reader does not pick up (HW-Q930H/XY,
        # SKK-NWG/ZS, DA97-13137E). Being unable to read a code is not evidence
        # that there is no product.
        keep = [r for r in rows if r.get('source') == 'ld+json'
                or code_from_url(r.get('product_url') or '')]
        if len(keep) != len(rows):
            print(f'    {len(rows) - len(keep)} guessed row(s) dropped: no model '
                  f'code in the url, so not a product')
        rows = keep

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
    return rows, stopped, pages


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

    # What the site states about itself - its structured data, its own catalogue
    # records - against what had to be read off the rendered page.
    STATED = ('ld+json', 'catalogue')

    def about_something_else(cur: dict, new: dict) -> bool:
        """True when a card's numbers are too low to be this product's price.

        samsung.com prints "save up to $2,000 with trade-in" beside a $9,999 TV
        and "4 interest-free instalments between $30 - $3,000" across the top of
        every listing. Those were read as prices, and the rule below - neither
        row knows a discount, so the lower price wins - handed them the row: a
        98-inch QN90F came out at $2,000 against a stated $9,999, and three
        different portable SSDs all came out at $37.46.

        A real discount still gets through, because it is the card's HIGHER
        number that is tested: a card marked down from $9,999 to $4,999 still
        carries the $9,999 and is believed. A card whose every number sits far
        under the stated price is not about this product's price at all.
        """
        if cur.get('source') not in STATED or new.get('source') in STATED:
            return False
        stated = cur.get('sale_price') or cur.get('original_price')
        seen = [v for v in (new.get('original_price'), new.get('sale_price'))
                if isinstance(v, (int, float))]
        return bool(stated and seen and max(seen) < stated * 0.6)

    def combine(cur: dict, new: dict) -> dict:
        """Fold new into cur. Identity fields fill gaps; price fields are taken as a
        set from whichever row actually knows about a discount - a card showing a
        struck-through price beats a feed that only carries the current price."""
        for f in ID_FIELDS:
            if not cur.get(f) and new.get(f):
                cur[f] = new[f]
        if about_something_else(cur, new):
            return cur                     # identity merged, prices left alone
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
        # Two rows that both assert the same field and disagree on it are
        # different products, however alike the rest reads. The name fallback
        # is there for rows that assert neither - a card with no sku meeting a
        # payload with no url - and it was folding real products together:
        # Samsung lists a fridge in three colours under one name, and two USB
        # drives under one name at two urls. Where a field disagrees, that
        # field is the identity and the name is not.
        clash = next((f for f in ('sku', 'product_url')
                      if cur is not None and cur[f] and r[f] and cur[f] != r[f]),
                     None)
        if clash:
            key = ('sku:' + r['sku'] if clash == 'sku'
                   else 'url:' + r['product_url'].rstrip('/').lower())
            cur = best.get(key)
            ids = [i for i in ids if not i.startswith('name:')]
        best[key] = r if cur is None else combine(cur, r)
        for i in ids:
            alias[i] = key
    return list(best.values())


# ── what tells two listings of one product apart ────────────────────────────
# Comparing two retailers founders on the variants: samsung.com writes "Galaxy
# Tab S10 FE Wi-Fi" and leaves the storage and the colour to the url slug
# (galaxy-a17-5g-black-128gb-sm-a176bzkcats), while Harvey Norman writes them
# into the name ("... Wi-Fi 256GB - Grey"). Neither file could say whether two
# rows were the same configuration. Both are now read out, from wherever the
# site happens to put them, into columns of their own.
CAPACITY = re.compile(r'\b(\d+(?:\.\d+)?)\s*-?\s*(gb|tb)\b', re.I)
COLOURS = ('black', 'white', 'grey', 'gray', 'silver', 'blue', 'green', 'pink',
           'gold', 'titanium', 'titan', 'graphite', 'lavender', 'lilac', 'navy',
           'beige', 'cream', 'charcoal', 'steel', 'platinum', 'bronze', 'copper',
           'mint', 'coral', 'red', 'yellow', 'purple', 'violet', 'sand', 'ivory',
           'onyx', 'pebble', 'jade', 'amber', 'sapphire', 'cotta', 'stainless')
COLOUR_RE = re.compile(r'\b(' + '|'.join(COLOURS) + r')\b', re.I)


def variant_of(row: dict) -> tuple[str, str]:
    """(capacity, colour) for a row, from its name first and its url second."""
    name = row.get('product_name') or ''
    slug = re.sub(r'[-_/]+', ' ', (row.get('product_url') or '').split('?')[0])
    cap = ''
    for text in (name, slug):
        found = CAPACITY.findall(text)
        if found:
            # "12GB/512GB" is RAM then storage; the larger one is the storage.
            cap = max((f'{float(n):g}{u.upper()}' for n, u in found),
                      key=lambda v: float(re.match(r'[\d.]+', v).group())
                      * (1024 if v.endswith('TB') else 1))
            break
    colour = ''
    for text in (name, slug):
        hit = COLOUR_RE.findall(text)
        if hit:
            colour = ' '.join(dict.fromkeys(w.lower() for w in hit))
            colour = colour.replace('gray', 'grey')
            break
    return cap, colour


COLUMNS = ['crawled_at', 'category', 'brand', 'product_name', 'product_url', 'sku',
           'sku_field', 'model', 'capacity', 'colour', 'on_sale', 'original_price',
           'sale_price', 'discount_pct', 'currency']


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
            cap, colour = variant_of(r)
            w.writerow({**r, 'capacity': cap, 'colour': colour,
                        'on_sale': 'Y' if r['on_sale'] else 'N'})
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
    ap.add_argument('--from-html', nargs='*', default=[], metavar='PATH',
                    help='parse pages already saved to disk (files, or a folder of '
                         'them) instead of fetching anything. Save the listing page '
                         'from your own browser with Ctrl+S and point this at it.')
    ap.add_argument('--out', help='output CSV path (default: <site>_<brand>.csv)')
    ap.add_argument('--delay', type=float, default=1.5,
                    help='seconds between scrolls (default: 1.5)')
    ap.add_argument('--max-scrolls', type=int, default=40)
    ap.add_argument('--timeout', type=int, default=30, help='per-step timeout, seconds')
    ap.add_argument('--headed', action='store_true', help='show the browser')
    ap.add_argument('--headless', action='store_true',
                    help='force a hidden browser even for sites that need a window')
    ap.add_argument('--profile', metavar='DIR',
                    help='keep cookies in this folder between runs, so a check you '
                         'passed once is not asked again (e.g. --profile .profile)')
    ap.add_argument('--pause-on-block', action='store_true',
                    help='when a page comes back with no products, wait at the console '
                         'so you can deal with it in the browser yourself, then retry '
                         'that page. Use with --headed.')
    ap.add_argument('--attach', nargs='?', const='http://127.0.0.1:9222',
                    metavar='URL',
                    help='read a browser that is already running instead of '
                         'starting one, over its debugging port (default '
                         'http://127.0.0.1:9222 - the numeric address on '
                         'purpose: Chrome listens on IPv4 and "localhost" '
                         'resolves to ::1 first on Windows). Start Chrome with '
                         '--remote-debugging-port=9222, clear any check by '
                         'hand, and the crawl uses that window and its session')
    ap.add_argument('--open-tabs', action='store_true',
                    help='with --attach, read the tabs that are already open '
                         'and navigate nowhere - crawl what is on the screen')
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
    ap.add_argument('--ignore-robots', action='store_true',
                    help="fetch a page robots.txt disallows. Off by default: "
                         "the site is asking, and a listing it asks you to "
                         "leave alone usually has an allowed path to the same "
                         "products")
    ap.add_argument('--no-brand-filter', action='store_true',
                    help='keep every product, not just the brand')
    args = ap.parse_args()
    use_site(args.site)
    if SITE.get('own_brand') and not args.no_brand_filter:
        # Filtering a single-brand store by its own brand only throws away the
        # rows whose brand field the page happens not to carry.
        args.no_brand_filter = True
        print(f'{args.site} sells only {args.brand.title()}, so no brand filter '
              f'is applied.\n')
    if SITE.get('needs_headed') and not args.headed and not args.headless:
        args.headed = True
        print(f'{args.site} does not serve a headless browser, so a window is used.')
        print('Pass --headless to override, and --profile DIR to keep the cookies '
              'from a check you clear.\n')
    if args.pause_on_block and not args.headed:
        print('--pause-on-block needs --headed, so there is a window to work in.',
              file=sys.stderr)
        return 2

    def label(u: str) -> str:
        # The last path segment. A url ending in a slash - which every listing
        # on samsung.com does - matched nothing and fell through to the whole
        # url, so every row was filed under a category called
        # https://www.samsung.com/au/tvs/all-tvs/.
        path = u.split('?')[0].split('#')[0].rstrip('/')
        m = re.search(r'/([^/]+)$', path)
        return m.group(1) if m else u

    if args.from_html:
        files = []
        for raw in args.from_html:
            path = Path(raw)
            files += sorted(path.glob('*.htm*')) if path.is_dir() else [path]
        missing = [f for f in files if not f.exists()]
        for f in missing:
            print(f'no such file: {f}', file=sys.stderr)
        files = [f for f in files if f.exists()]
        targets = [(f.stem, f.resolve().as_uri()) for f in files]
    elif args.url:
        targets = [(label(u), u) for u in args.url]
    elif args.category:
        unknown = [c for c in args.category if c not in CATEGORIES]
        if unknown:
            print(f'unknown category: {", ".join(unknown)}', file=sys.stderr)
        targets = [(c, listing_url(CATEGORIES[c], args.brand))
                   for c in args.category if c in CATEGORIES]
    elif args.open_tabs:
        targets = []                      # filled from the browser once attached
    elif SITE.get('all_categories'):
        # The site's front page is a shop window: it links to the listings and
        # sells nothing itself - 0 products in its structured data. Searching it
        # for a brand means nothing either, because the whole store is that
        # brand. So with nothing named, every category is the run.
        targets = [(c, listing_url(path, args.brand))
                   for c, path in CATEGORIES.items() if c != 'search']
    else:
        targets = [('search', listing_url(CATEGORIES['search'], args.brand))]
    if not targets and not args.open_tabs:
        print('nothing to crawl', file=sys.stderr)
        return 2
    if args.open_tabs and not args.attach:
        print('--open-tabs needs --attach: there is no open browser to read '
              'otherwise', file=sys.stderr)
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
        if args.attach:
            # Read the browser already open instead of starting one. A site
            # that refuses automated browsers is not refused back: this is the
            # window a person opened, with the session they established, and
            # the pages they are already looking at. Nothing about the browser
            # is faked - it simply is the browser.
            #
            # Start Chrome once with a debugging port and leave it open:
            #   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\hn
            try:
                browser = pw.chromium.connect_over_cdp(args.attach)
            except Exception as exc:
                first = str(exc).splitlines()[0]
                print(f'could not attach to a browser at {args.attach}\n'
                      f'  {first}\n\n'
                      'Nothing is listening on that port. An already-running\n'
                      'Chrome does not have one - it has to be started with the\n'
                      'flag, in its own profile folder, and left open:\n\n'
                      '  Windows:\n'
                      '    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" ^\n'
                      '      --remote-debugging-port=9222 --user-data-dir=C:\\hn-profile\n\n'
                      '  macOS:\n'
                      '    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\\n'
                      '      --remote-debugging-port=9222 --user-data-dir=/tmp/hn-profile\n\n'
                      'Open the pages you want in that window, clear any check,\n'
                      'then run this again. Check the port is up first:\n'
                      '  curl http://127.0.0.1:9222/json/version',
                      file=sys.stderr)
                return 2
            if not browser.contexts:
                print(f'nothing is open in the browser at {args.attach}',
                      file=sys.stderr)
                return 2
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            print(f'attached to the browser at {args.attach}: '
                  f'{len(ctx.pages)} tab(s) open')
            if args.open_tabs:
                tabs = [t for t in ctx.pages if t.url.startswith('http')]
                targets = [(label(t.url), t.url) for t in tabs]
                open_pages = {t.url: t for t in tabs}
                for t in tabs:
                    print(f'    - {t.url[:96]}')
                if not targets:
                    print('no http tab is open to read', file=sys.stderr)
                    return 2
        elif args.profile:
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

        open_pages = locals().get('open_pages') or {}
        while queue:
            name, url = queue.pop(0)
            if args.open_tabs:
                page = open_pages.get(url, page)
            # A tab a person already opened is theirs, not the crawler's fetch,
            # so it is read either way; everything the crawler would go and get
            # is checked first.
            if not args.ignore_robots and not args.open_tabs \
                    and url.startswith('http') \
                    and not robots_allows(page, url):
                ROBOTS['skipped'] += 1
                print(f'  skipped, robots.txt disallows it: {url[:88]}')
                continue
            if url in done:
                continue
            done.add(url)
            try:
                rows, stopped, pages = harvest(page, payloads, url, args, dump)
                if not rows and args.pause_on_block and not stopped:
                    print('\n  This page returned nothing. If the browser is showing a')
                    print('  check to confirm you are human, complete it in the browser')
                    print('  window, then press Enter here to read the page again.')
                    print('  (--profile DIR keeps it from being asked every time.)')
                    try:
                        input('  press Enter to continue: ')
                        rows, stopped, pages = harvest(page, payloads, url, args, dump)
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
            for u in pages:
                if u not in done and (name, u) not in queue:
                    queue.append((name, u))
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
            # A site whose categories are listed here has already queued every
            # one of them, and discovery would only add the same pages back
            # under the words a promo tile happened to use - "Monitors &
            # Storage", "Bespoke AI Laundry" - which is how one run came out
            # labelled by banners instead of by categories.
            if discovered_from is None and not args.no_discover and not args.url \
                    and not args.category and not args.from_html \
                    and not SITE.get('all_categories'):
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

        if args.with_model and not interrupted and not args.from_html:
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
    if ROBOTS['skipped']:
        print(f"{ROBOTS['skipped']} page(s) were left alone because robots.txt "
              f'disallows them')
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

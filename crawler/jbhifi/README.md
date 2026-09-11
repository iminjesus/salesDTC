# JB Hi-Fi Samsung crawler

Pulls Samsung listings from jbhifi.com.au into a CSV: on-sale flag, product name,
original price, sale price and % off.

## Install

```sh
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```sh
# site search for SAMSUNG (the page you linked)
python crawl_jbhifi.py

# specific categories
python crawl_jbhifi.py --category tvs phones whitegoods --out samsung_2026-09-11.csv

# any listing URL, e.g. a filtered collection page
python crawl_jbhifi.py --url "https://www.jbhifi.com.au/collections/tvs?query=samsung"

# watch it work, and keep the raw payloads
python crawl_jbhifi.py --headed --dump-dir dump
```

Categories are a plain dict at the top of `crawl_jbhifi.py` (`CATEGORIES`) — add or
correct a slug there and it becomes available to `--category`.

## Output

`jbhifi_samsung.csv`, UTF-8 with BOM so Excel opens it without mangling:

| column | notes |
|---|---|
| `crawled_at` | local time the run started |
| `category` | which category the row came from |
| `brand` | as reported by the site, when it reports one |
| `product_name` | |
| `product_url` | absolute |
| `sku` | site product id, when available |
| `on_sale` | `Y` / `N` |
| `original_price` | the was / RRP price; equals `sale_price` when not on sale |
| `sale_price` | price being charged now |
| `discount_pct` | `(original - sale) / original * 100`, blank when not on sale |
| `currency` | `AUD` |

## How it reads the page

The storefront renders client side, so the crawler drives a real browser and runs two
extractors, merging them by product URL:

1. **network** — every JSON response the page fetches is captured and walked for
   product-shaped records (a name-ish key sitting next to a price-ish key). This is
   the primary source and survives CSS changes.
2. **dom** — the rendered cards are read as a fallback, covering the case where the
   data is delivered server side.

A row from the network extractor wins over a DOM row, and a row that knows the
original price wins over one that does not.

## If it comes back empty

```sh
python crawl_jbhifi.py --headed --dump-dir dump
```

`dump/` then holds the captured JSON payloads and an HTML snapshot of the page. That
is what the field names have to be pinned against — send it over and the parser can be
made exact rather than heuristic. An empty result usually means one of:

- the site served a bot challenge (visible with `--headed`)
- the category slug in `CATEGORIES` is wrong, so the page 404s
- field names moved, and the heuristics no longer recognise a product record

## Manners

This walks public listing pages at `--delay` seconds per scroll (1.5 by default),
identifies itself in the user agent, and makes no attempt to defeat bot protection.
Put a real contact address in `UA` before scheduling it, and check the site's terms
and robots.txt for what is allowed.

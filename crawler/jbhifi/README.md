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
# default: /search?query=samsung&Brand=SAMSUNG, then every category the site
# offers for that brand
python crawl_jbhifi.py

# just the search page, no category pass
python crawl_jbhifi.py --no-discover

# a fixed set of categories instead of discovering them
python crawl_jbhifi.py --category tvs phones whitegoods --out samsung_2026-09-11.csv

# any listing URL, e.g. an already filtered collection page
python crawl_jbhifi.py --url "https://www.jbhifi.com.au/collections/tvs?query=samsung"

# watch it work, and keep the raw payloads
python crawl_jbhifi.py --headed --dump-dir dump
```

### Brand

Every listing URL the crawler builds carries the site's own brand facet, so the pages
come back already filtered:

```
https://www.jbhifi.com.au/search?query=samsung&Brand=SAMSUNG
https://www.jbhifi.com.au/collections/tvs?query=samsung&Brand=SAMSUNG
```

`--brand` sets both (`--brand LG` gives `query=lg&Brand=LG`), and the facet name itself
is `BRAND_PARAM` at the top of the script. A URL passed with `--url` is used exactly as
given, so any facets already on it are kept. The name-based filter still runs afterwards
as a safety net; `--no-brand-filter` turns that off.

### Categories

By default the categories are not hard-coded: the seed search page is crawled first,
then the crawler asks that page which categories the site itself offers for the brand —
the `/collections/...` refinement links in the markup plus any category facet counts in
the JSON it fetched — and walks them one at a time, printing what it found:

```
  discovered 8 categories:
    - TVs
    - Mobile Phones
    - Home Appliances
    ...
```

`--max-categories` caps that list (25 by default). A full pass is one page load and a
scroll-to-bottom per category, so at the default `--delay 1.5` it takes a few minutes.

`CATEGORIES` at the top of the script is only the fallback list used by `--category`.

## Stopping part way

The CSV is rewritten after every page, and written atomically, so whatever has been
collected is always on disk. Ctrl+C stops the scroll, extracts the products already
loaded on that page, saves, and exits — the run summary then says `(stopped early)`.
A crawl killed half way still leaves a usable file.

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
| `sku_field` | which field on the site the `sku` came from, e.g. `sku` or `objectID` — so the number is traceable rather than anonymous |
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
original price wins over one that does not. The same product appears several times —
once per extractor, and again on every category page it belongs to — so rows are
merged on `sku` first, then product URL, then name, and fields missing from the
winning row are filled in from the others.

`category` is the product's own category as the site reports it (`Home > TVs`) when the
data carries one, and otherwise the page the row was found on.

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

The same applies if products you can see are discounted come back as `on_sale = N`:
that means the was/RRP price is under a field name the heuristics do not know yet. The
dump is what pins it down.

## Manners

This walks public listing pages at `--delay` seconds per scroll (1.5 by default),
identifies itself in the user agent, and makes no attempt to defeat bot protection.
Put a real contact address in `UA` before scheduling it, and check the site's terms
and robots.txt for what is allowed.

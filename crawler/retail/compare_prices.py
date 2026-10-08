#!/usr/bin/env python3
"""Compare two crawls of the same brand and report the models priced differently.

    python compare_prices.py samsung_samsung.csv harveynorman_samsung.csv gap.csv

Reads two files written by crawl.py, matches them on the model code, and writes
the rows whose original_price or sale_price disagree - widest gap first.

Matching
    The two sites write the same model slightly differently: samsung.com carries
    the Australian region suffix (/SA, SA, XSA) that Harvey Norman drops, and
    Harvey Norman puts an F- in front of the air conditioners. Those are stripped
    before comparing; everything else has to match exactly.

Reading the result
    A crawled price is a number off a page, and a page carries other numbers. On
    samsung.com three different portable SSDs all came back at $37.46 and $2,000
    landed on nine models - a trade-in or a bonus read as the price. The `flag`
    column marks a price that recurs across unrelated models while undercutting
    the other site, or that sits far under it. Those rows are not a price
    difference; they are a bad read, and the product page settles them.
"""
import csv, re, sys

def load(path):
    return list(csv.DictReader(open(path, encoding='utf-8-sig')))

def key(code):
    c = re.sub(r'[^A-Z0-9]', '', (code or '').upper())
    c = re.sub(r'^F', '', c)
    for suffix in ('XSA', 'XXY', 'AUS', 'XY', 'SA', 'AU'):
        if c.endswith(suffix):
            return c[:-len(suffix)]
    return c

def money(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None

def flag(sa, sb, shared):
    if sa is None or sb is None:
        return 'a price is missing'
    # A figure that recurs across unrelated models AND undercuts the shelf is
    # a trade-in or a bonus that was read as the price. A recurring figure on
    # its own is not suspicious - $1,999 is a price several Samsung products
    # genuinely carry - so both have to hold.
    if sa < sb and shared[sa] >= 3:
        return f'samsung.com price doubtful: {shared[sa]} models carry it'
    if sa < sb * 0.6:
        return 'samsung.com price doubtful: far under the shelf price'
    return ''


def index(rows):
    out = {}
    for r in rows:
        out.setdefault(key(r['sku']), []).append(r)
    return out

s, h = load(sys.argv[1]), load(sys.argv[2])
S, H = index(s), index(h)

# samsung.com repeats one figure across unrelated models - three different
# portable SSDs all read $37.46, and $2,000 lands on nine models - so that
# figure is something else on the page (a trade-in or a bonus), not the price.
# A price shared by several models is marked rather than silently compared.
import collections
shared = collections.Counter()
for r in s:
    v = money(r['sale_price'])
    if v is not None:
        shared[v] += 1
both = sorted(set(S) & set(H))

diff, same = [], 0
for k in both:
    a, b = S[k][0], H[k][0]
    sa, sb = money(a['sale_price']), money(b['sale_price'])
    oa, ob = money(a['original_price']), money(b['original_price'])
    if sa == sb and oa == ob:
        same += 1
        continue
    diff.append({
        'model': a['sku'],
        'hn_model': b['sku'],
        'product_name': a['product_name'],
        'hn_product_name': b['product_name'],
        'samsung_original': oa, 'samsung_sale': sa,
        'hn_original': ob, 'hn_sale': sb,
        'sale_gap': None if sa is None or sb is None else round(sb - sa, 2),
        'rrp_gap': None if oa is None or ob is None else round(ob - oa, 2),
        'samsung_price_also_on': shared[sa] - 1 if sa is not None else '',
        'flag': flag(sa, sb, shared),
        'samsung_url': a['product_url'], 'hn_url': b['product_url'],
    })

diff.sort(key=lambda d: abs(d['sale_gap'] or 0), reverse=True)
out = sys.argv[3]
with open(out, 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.DictWriter(f, fieldnames=list(diff[0]) if diff else ['model'])
    w.writeheader()
    w.writerows(diff)

print(f'{len(s)} samsung.com rows, {len(h)} Harvey Norman rows')
print(f'{len(both)} models on both sites: {len(diff)} priced differently, '
      f'{same} the same')
print(f'-> {out}\n')
head = f"{'model':<16} {'samsung now':>12} {'HN now':>10} {'gap':>9}   {'samsung was':>12} {'HN was':>9}  product"
print(head); print('-' * len(head))
for d in diff:
    mark = '!' if d['flag'] else ' '
    print(f"{mark}{d['model']:<15} {d['samsung_sale']:>12,.2f} {d['hn_sale']:>10,.2f} "
          f"{d['sale_gap']:>+9,.2f}   {d['samsung_original']:>12,.2f} "
          f"{d['hn_original']:>9,.2f}  {d['product_name'][:38]}")
print()
print(f"{sum(1 for d in diff if not d['flag'])} of the {len(diff)} are a clean "
      f"comparison; the {sum(1 for d in diff if d['flag'])} marked ! have a "
      f"samsung.com price that is not a price.")

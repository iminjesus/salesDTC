#!/usr/bin/env python3
"""Compare two crawls of the same brand and report the products priced differently.

    python compare_prices.py samsung_samsung.csv harveynorman_samsung.csv gap.csv

Reads two files written by crawl.py, pairs them up by product name, and writes
the pairs whose original_price or sale_price disagree - widest gap first.

Why the name and not the model code
    The two sites do not run the same model-code policy. samsung.com carries the
    region suffix Harvey Norman drops, Harvey Norman puts an F- in front of the
    air conditioners and sells plenty under a code of its own. Matching on the
    code found 50 products across files of 423 and 475; matching on the name
    finds about 250.

How a pair is decided
    1. The numbers in a name are a promise, so where both names state one they
       have to agree: a 75-inch is not a 65-inch, 4TB is not 2TB, 9kg is not
       12kg, 5.1.2ch is not 3.1.2ch.
    2. A word that names a different product in the same family - Shield, Pro,
       Plus, Ultra, Lite, FE, Edge, top- against front-load - has to be on both
       sides or neither. The Frame is not The Frame Pro.
    3. What is left is scored on the words the two names share, each weighted by
       how rare it is across both files, so "Samsung", "Smart" and "TV" count for
       little and "QN90F", "SpaceMax" or "BubbleStorm" count for a lot.
    4. The prices break a tie. Two sites selling the same product should post the
       same RRP, so an equal original_price is the strongest confirmation there
       is; the sale price is the weaker one. A samsung.com figure that recurs
       across unrelated models is ignored here - see below.
    5. A samsung.com package - "Washer 11kg & Dryer 9kg & Laundry Hub" - is not
       one product and is left unmatched rather than paired with a washer.

    Checked against the 54 products whose model codes do match across the two
    files: 42 paired correctly, 6 paired with another colour of the same product
    (4 of them at an identical price, so the comparison is unaffected), 6 left
    unmatched - all six samsung.com packages, which is the wanted answer.

Reading the result
    original_price is the RRP, and two sites selling the same product should
    carry the same one. A non-zero rrp_gap is therefore worth a look on its own:
    one of the two has the wrong RRP posted. sale_gap is the real difference in
    what a customer pays.

    `flag` marks a pair not to act on. A crawled price is a number off a page and
    a page carries other numbers: on samsung.com three different portable SSDs
    all came back at $37.46 and $2,000 landed on nine models, which is a trade-in
    or a bonus read as the price. `confidence` is the name score, 1.0 being a
    perfect overlap; anything under about 0.5 is worth reading the two names.
"""
import collections
import csv
import math
import re
import sys

SIZE = re.compile(r'(\d+(?:\.\d+)?)\s*(?:"|”|inch|inches|-inch)')
UNIT = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|tb|gb|mm|cm|kw|w|l|ch)\b')
MEASURE = re.compile(r'^\d+(?:\.\d+)?(in|kg|tb|gb|mm|cm|kw|w|l|ch)$')
NOISE = {'samsung', 'with', 'and', 'the', 'a', 'new'}
# Present on one side and absent on the other, these name a different product.
VARIANT = {'shield', 'pro', 'ultra', 'max', 'lite', 'fe', 'edge', 'plus',
           'top', 'front'}
MIN_SCORE = 0.35


def tokens(name: str) -> list[str]:
    # The export escapes the inch mark - 98\" - and a backslash sitting between
    # the number and the quote is what stopped 98-inch matching 98-inch.
    t = (name or '').lower().replace('\\', ' ').replace('”', '"').replace('’', "'")
    t = re.sub(r'\bplus\b', '+', t)
    t = re.sub(r'\bchannel[s]?\b', 'ch', t)
    t = SIZE.sub(r' \1in ', t)
    t = UNIT.sub(r' \1\2 ', t)
    t = re.sub(r'[^a-z0-9.+]+', ' ', t)
    return [w for w in (x.strip('.') for x in t.split()) if w and w not in NOISE]


def measures(ts) -> dict:
    out = collections.defaultdict(set)
    for w in ts:
        m = MEASURE.match(w)
        if m:                            # 5.0ch and 5ch are the same promise
            out[m.group(1)].add(re.sub(r'\.0(?=[a-z])', '', w))
    return out


# A word of letters and digits together is the series both sites print in the
# name - S95F, QN90F, G80HS, M70F, HW-Q930H. It is the sharpest thing either
# name carries, so where both state one they have to state the same one: an
# S95F is not an S90H and a G80HS is not a G30D, however alike the rest reads.
# Resolutions, network generations and years look the same and say nothing.
NOT_A_SERIES = {'4k', '8k', '2k', '5g', '4g', '3g', '1080p', '2160p', '2026',
                '2025', '2024', '2023'}


def series(ts) -> set:
    out = set()
    for w in ts:
        if (len(w) >= 2 and w not in NOT_A_SERIES and not MEASURE.match(w)
                and any(c.isdigit() for c in w) and any(c.isalpha() for c in w)):
            out.add(w)
    return out


def compatible(a, b) -> bool:
    A, B = set(a), set(b)
    for v in VARIANT:
        if (v in A) != (v in B):
            return False
    sa, sb = series(a), series(b)
    if sa and sb and not (sa & sb):
        return False
    ma, mb = measures(a), measures(b)
    for unit in set(ma) & set(mb):
        if not (ma[unit] & mb[unit]):
            return False
    return True


def same_variant(a, b) -> bool:
    """A 256GB is not a 512GB, and a black one is not a white one.

    Takes the two rows, not their names: capacity and colour are columns of
    their own. Where both rows state one it has to agree, and colours agree
    when they share a word, so "Titan Grey" meets "Grey".
    """
    ca, cb = variant(a), variant(b)
    if ca[0] and cb[0] and ca[0] != cb[0]:
        return False
    if ca[1] and cb[1] and not (ca[1] & cb[1]):
        return False
    return True


def variant(row) -> tuple[str, set]:
    """(capacity, colour words) for a row.

    crawl.py writes these as columns of their own, because the two sites put
    them in different places - samsung.com in the url slug, Harvey Norman in
    the name. A file crawled before those columns existed falls back to
    whatever the name happens to say.
    """
    cap = (row.get('capacity') or '').upper()
    colour = row.get('colour')
    if colour is None:
        ts = tokens(row['product_name'])
        cap = cap or next((w.upper() for w in ts
                           if re.match(r'^\d+(?:\.\d+)?(gb|tb)$', w)), '')
        colour = ''
    return cap, set(colour.split())


def bundle(name: str) -> bool:
    return (name or '').count('&') >= 2 or ' + ' in (name or '')


def money(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def load(path):
    return list(csv.DictReader(open(path, encoding='utf-8-sig')))


def main(left_path, right_path, out_path):
    left, right = load(left_path), load(right_path)

    corpus = [tokens(r['product_name']) for r in left + right]
    df = collections.Counter()
    for d in corpus:
        df.update(set(d))
    n = len(corpus)

    def weigh(ts):
        return sum(math.log(n / (1 + df[w])) for w in set(ts)) or 1e-9

    def name_score(a, b):
        shared = weigh(set(a) & set(b))
        ca, cb = shared / weigh(a), shared / weigh(b)
        return 2 * ca * cb / (ca + cb) if ca + cb else 0.0

    # A figure that recurs across unrelated models is not a price, so it can
    # neither confirm a pair nor be reported as a difference.
    seen = collections.Counter()
    for r in left:
        for field in ('sale_price', 'original_price'):
            v = money(r[field])
            if v is not None:
                seen[v] += 1

    def near(pa, pb, when_equal):
        if pa is None or pb is None or pa <= 0 or pb <= 0 or seen[pa] >= 5:
            return 0.0
        if pa == pb:
            return when_equal
        return max(0.0, 1 - abs(math.log(pa / pb)) / 0.35)

    def agreement(a, b):
        """How much the prices vouch for the pair. The RRP counts for more."""
        return max(near(money(a['original_price']), money(b['original_price']), 1.2),
                   0.8 * near(money(a['sale_price']), money(b['sale_price']), 1.0))

    pool = [(r, tokens(r['product_name'])) for r in right]
    rows, unmatched, packages = [], 0, 0
    for a in left:
        if bundle(a['product_name']):
            packages += 1
            continue
        at = tokens(a['product_name'])
        ranked = sorted(((b, name_score(at, bt),
                          name_score(at, bt) * (1 + 0.5 * agreement(a, b)))
                         for b, bt in pool
                         if compatible(at, bt) and same_variant(a, b)),
                        key=lambda x: -x[2])
        if not ranked or ranked[0][1] < MIN_SCORE:
            unmatched += 1
            continue
        b, score, _ = ranked[0]
        oa, ob = money(a['original_price']), money(b['original_price'])
        sa, sb = money(a['sale_price']), money(b['sale_price'])
        if oa == ob and sa == sb:
            continue

        flag = ''
        if sa is None or sb is None:
            flag = 'a price is missing'
        elif seen[sa] >= 5:
            flag = f'{left_path} price doubtful: {seen[sa]} rows carry it'
        elif sa < sb * 0.6:
            flag = f'{left_path} price doubtful: far under the other shelf price'
        # A runner-up as good as the winner but priced differently means the two
        # names do not tell the products apart - usually two colours of one.
        runner = ranked[1] if len(ranked) > 1 else None
        if (not flag and runner and runner[1] > score * 0.95
                and money(runner[0]['sale_price']) != sb):
            flag = 'more than one product fits this name'
        if not flag and score < 0.5:
            flag = 'the two names barely overlap - read them before using this'
        # samsung.com writes "Galaxy Tab S12 Ultra 5G" where Harvey Norman
        # writes "... 16GB/1TB". The capacity is a price, so a pair where only
        # one side states it may be two different configurations.
        if not flag:
            ca, cb = variant(a), variant(b)
            if bool(ca[0]) != bool(cb[0]):
                flag = 'the storage size is stated on one side only'
            elif bool(ca[1]) != bool(cb[1]):
                flag = 'the colour is stated on one side only'

        rows.append({
            'left_name': a['product_name'], 'right_name': b['product_name'],
            'left_model': a['sku'], 'right_model': b['sku'],
            'left_original': oa, 'left_sale': sa,
            'right_original': ob, 'right_sale': sb,
            'rrp_gap': None if oa is None or ob is None else round(ob - oa, 2),
            'sale_gap': None if sa is None or sb is None else round(sb - sa, 2),
            'confidence': round(score, 2),
            'flag': flag,
            'left_url': a['product_url'], 'right_url': b['product_url'],
        })

    rows.sort(key=lambda d: (d['flag'] != '', -abs(d['sale_gap'] or 0)))
    with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['left_name'])
        w.writeheader()
        w.writerows(rows)

    clean = [d for d in rows if not d['flag']]
    paired = len(left) - unmatched - packages
    print(f'{len(left)} rows in {left_path}, {len(right)} in {right_path}')
    print(f'{paired} paired by name  ({unmatched} found no counterpart, '
          f'{packages} are packages rather than one product)')
    print(f'{len(rows)} of the pairs are priced differently, {len(clean)} of them '
          f'cleanly\n-> {out_path}\n')
    bad_rrp = [d for d in clean if d['rrp_gap']]
    if bad_rrp:
        print(f'{len(bad_rrp)} carry a different RRP, which should not happen - '
              f'one of the two has it posted wrong:')
        for d in bad_rrp[:12]:
            print(f"    {d['left_original']:>10,.2f} vs {d['right_original']:>10,.2f}"
                  f"   {d['left_name'][:52]}")
        print()
    head = (f"{'confidence':>10} {'left now':>11} {'right now':>11} {'gap':>10}  product")
    print(head)
    print('-' * len(head))
    for d in clean:
        print(f"{d['confidence']:>10.2f} {d['left_sale']:>11,.2f} "
              f"{d['right_sale']:>11,.2f} {d['sale_gap']:>+10,.2f}  "
              f"{d['left_name'][:46]}")
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    sys.exit(main(*sys.argv[1:4]))

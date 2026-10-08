#!/usr/bin/env python3
"""Add the units a model actually sold, online and offline, to a price gap file.

    py tools\\gap_units.py gap.csv --sales sales_2609

Reads a file keyed on a model code - the crawler's `gap.csv` is the one this
was written for - looks each model up in a sales export, and writes the same
rows back with what that model sold beside the two shelf prices.

Which side of the business a row is on comes from `customer.py`, the same rule
both dashboards use: the account name, with anything spelled `off-line` on the
offline side and everything else online. A row whose customer the master does
not have is neither, and is counted and reported rather than quietly folded
into one of them - a split that does not add up to the export is worse than no
split.

New columns
    online units, offline units        what the export counted, by channel
    online share                       of the two, where there are any
    unplaced units                     sold, but the customer could not be placed
    online net sales, offline net sales

A model with no row in the export gets blanks, not zeros: "it sold none" and
"the export does not mention it" are different answers and only one of them is
a finding.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import promo_match as PM                                       # noqa: E402
from asp import AMT_NET, CUSTOMER_KEYS, PRODUCT_KEYS, QTY_NET  # noqa: E402
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_file, pick_series, read_any)

# The column in the gap file that holds a model code, in the order they are
# tried. The crawler writes both sides; either names the same product.
MODEL_COLS = ('model', 'left_model', 'right_model', 'sku', 'Material')


def cell(row, i):
    return (row[i] if i is not None and i < len(row) else '') or ''


def sold_by_channel(path: Path, cust: dict, online: str, say=print) -> tuple:
    """{model code: {'on': units, 'off': units, ...}} out of a sales export."""
    rows, info = read_any(path)
    if not rows:
        say(f'  {path.name}: empty')
        return {}, {}
    head = [h.strip() for h in rows[0]]
    i_sku = find(head, *PRODUCT_KEYS)
    i_qty = find(head, *QTY_NET)
    i_amt = find(head, *AMT_NET)
    i_cust = find(head, *CUSTOMER_KEYS)
    say(f'  {path.name}: {info["format"]}, {len(rows) - 1:,} rows')
    for what, i in (('product', i_sku), ('quantity', i_qty),
                    ('net sales', i_amt), ('customer', i_cust)):
        say(f'    {what:<10} ' + (repr(head[i]) if i is not None
                                  else '-- not found --'))
    if i_sku is None or i_qty is None:
        say('  without a product code and a quantity there is nothing to '
            'count', )
        return {}, {}
    if i_cust is None:
        say('  no customer column, so no row can be placed in a channel')
        return {}, {}

    out: dict[str, dict] = {}
    totals = {'rows': 0, 'on': 0.0, 'off': 0.0, 'lost': 0.0, 'nocode': 0.0}
    for r in rows[1:]:
        qty = parse_number(cell(r, i_qty)) or 0.0
        amt = parse_number(cell(r, i_amt)) or 0.0 if i_amt is not None else 0.0
        totals['rows'] += 1
        code = PM.code_norm(cell(r, i_sku))
        if not code:
            totals['nocode'] += qty
            continue
        c = cust.get(key_norm(cell(r, i_cust))) or {}
        where = CUST.channel_of(c.get('account'), bool(c))
        v = out.setdefault(code, {'on': 0.0, 'off': 0.0, 'lost': 0.0,
                                  'on_amt': 0.0, 'off_amt': 0.0})
        if where == online:
            v['on'] += qty
            v['on_amt'] += amt
            totals['on'] += qty
        elif where == CUST.OFFLINE:
            v['off'] += qty
            v['off_amt'] += amt
            totals['off'] += qty
        else:
            # Blank account name, or a customer the master does not have.
            v['lost'] += qty
            totals['lost'] += qty
    return out, totals


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('gap', help='the csv to add the columns to')
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--sales', default='sales', metavar='STEM',
                    help='how the sales export is named (default: sales; '
                         'try --sales sales_2609)')
    ap.add_argument('--customer', default='customer', metavar='STEM',
                    help='how the customer master is named (default: customer)')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME',
                    help=f'which channel counts as online (default: {CUST.ONLINE})')
    ap.add_argument('--out', default=None,
                    help='where to write (default: beside the input, '
                         '<name>_units.csv)')
    args = ap.parse_args()

    gap = Path(args.gap)
    if not gap.is_file():
        print(f'no such file: {gap.resolve()}', file=sys.stderr)
        return 2
    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    sp = pick_file(folder, args.sales) or next(
        iter(pick_series(folder, args.sales)), None)
    if sp is None:
        print(f'no sales export matching {args.sales!r} in {folder.resolve()}',
              file=sys.stderr)
        return 2

    print('customer master:')
    cp = next(iter(pick_series(folder, args.customer)), None)
    cust = {}
    if cp is not None:
        want = {slot: names for _, slot, names in CUST.LEVELS if names}
        want['account'] = CUST.ACCOUNT_NAMES
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'), want,
                      say=lambda *a: None)
        print(f'  {cp.name}, {len(cust):,} account(s)')
    else:
        print(f'  nothing matching {args.customer!r} - without it no row can '
              f'be placed in a channel', file=sys.stderr)
        return 2

    print('\nsales export:')
    sold, totals = sold_by_channel(sp, cust, args.channel)
    if not sold:
        return 2
    print(f'  {totals["on"]:,.0f} online, {totals["off"]:,.0f} offline unit(s)'
          + (f', {totals["lost"]:,.0f} whose customer the master does not have'
             if totals['lost'] else '')
          + (f', {totals["nocode"]:,.0f} with no product code'
             if totals['nocode'] else ''))

    with gap.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f'{gap.name} has no rows', file=sys.stderr)
        return 2
    cols = [c for c in MODEL_COLS if c in rows[0]]
    if not cols:
        print(f'{gap.name} has no model column (looked for '
              f'{", ".join(MODEL_COLS)})', file=sys.stderr)
        return 2
    print(f'\nmatching on {", ".join(cols)}')

    added = ['online units', 'offline units', 'online share', 'unplaced units',
             'online net sales', 'offline net sales']
    found = covered = 0.0
    for r in rows:
        hit = next((sold[k] for c in cols
                    if (k := PM.code_norm(r.get(c))) in sold), None)
        if hit is None:
            for a in added:
                r[a] = ''
            continue
        found += 1
        covered += hit['on'] + hit['off'] + hit['lost']
        both = hit['on'] + hit['off']
        r['online units'] = round(hit['on'], 2)
        r['offline units'] = round(hit['off'], 2)
        r['online share'] = round(hit['on'] / both, 4) if both else ''
        r['unplaced units'] = round(hit['lost'], 2) if hit['lost'] else ''
        r['online net sales'] = round(hit['on_amt'], 2)
        r['offline net sales'] = round(hit['off_amt'], 2)

    out = Path(args.out) if args.out else gap.with_name(f'{gap.stem}_units.csv')
    with out.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) + [
            a for a in added if a not in rows[0]])
        w.writeheader()
        w.writerows(rows)

    every = totals['on'] + totals['off'] + totals['lost']
    print(f'{found:,.0f} of {len(rows):,} row(s) in {gap.name} sold in that '
          f'month; they are {covered:,.0f} of the export\'s '
          f'{every:,.0f} unit(s) ({covered / every * 100:.1f}%)'
          if every else f'{found:,.0f} of {len(rows):,} row(s) matched')
    print(f'-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

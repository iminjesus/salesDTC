#!/usr/bin/env python3
"""How long after an order it leaves, per division.

    py tools\\lead_time.py --month 2609
    py tools\\lead_time.py --month 2609 --by div3

A month's target is hit by what **leaves** in the month, and an order placed
near the end of it leaves in the next one. So whether a division makes its
number depends on its lead time as much as on its demand, and the two are
measured in different places: demand is the order date, revenue is the goods
issue date, and the gap between them is this.

Only lines ordered in the month are read - what left in it but was ordered
earlier belongs to an earlier month's demand - and only lines that have
actually left can be averaged. Lines still open are counted and reported
beside the average rather than folded into it: they are the slow ones, so an
average that quietly dropped them would read faster than the business is.

The same filters the page uses: a store-stamped reference, nothing rejected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import sap as SAP                                              # noqa: E402
from rawdata import (find, key_norm, master, month_of,        # noqa: E402
                     parse_number, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# The product tree, as the profit page draws it. The key SAP builds is the
# customer levels then these, so a level is a position in that key.
PRODUCT = [('Biz', 'biz', ('Biz', 'Business', 'Business Unit', 'Division')),
           ('Div 1', 'div1', ('Div 1', 'Div1', 'Division 1', 'Division')),
           ('Div 2', 'div2', ('Div 2', 'Div2', 'Division 2', 'Division')),
           ('Div 3', 'div3', ('Div 3', 'Div3', 'Division 3', 'Prod_group',
                              'Product Group', 'Category')),
           ('Range', 'range', ('Range', 'product_range', 'Material Group')),
           ('SKU', 'sku', ())]
AT = {name.lower().replace(' ', ''): i for i, (name, _, _) in
      enumerate(PRODUCT)}


def read_master(folder: Path, prefix: str, keys, want, say=print):
    for cand in pick_series(folder, prefix):
        try:
            got = master(cand, keys, want)
        except (ValueError, OSError) as e:
            say(f'  {cand.name}: {e} - trying the next {prefix} export')
            continue
        if got:
            return cand, got
    return None, {}


class Pot:
    """One division: how long its shipped lines took, and what is still open."""

    def __init__(self):
        self.units = 0.0           # units that have left
        self.days = 0.0            # unit-days, for the weighted average
        self.open_units = 0.0      # ordered, not yet left
        self.lines = 0

    @property
    def mean(self):
        return self.days / self.units if self.units else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, required=True, metavar='YYMM',
                    help='the month whose orders are measured, as 2609')
    ap.add_argument('--sap', default='orders', metavar='STEM')
    ap.add_argument('--by', default='div1', metavar='LEVEL',
                    help='biz, div1, div2, div3, range or sku (default div1)')
    ap.add_argument('--online', action='store_true',
                    help='the online business only, as the target is')
    ap.add_argument('--skip-sku', default='', metavar='PREFIX',
                    help='leave out codes starting with this, comma-separated')
    args = ap.parse_args()
    skip_sku = tuple(t.strip().upper()
                     for t in args.skip_sku.split(',') if t.strip())

    at = AT.get(args.by.lower().replace(' ', ''))
    if at is None:
        raise SystemExit('--by ' + args.by + ' is not one of '
                         + ', '.join(sorted(AT)))
    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    # 2609 and 202609 are both in use. 202000 + 2609 is the year 2046, which
    # is the shape of bug that reads as "no export in the folder".
    m = args.month
    ym = m if m > 9999 else (2000 + m // 100) * 100 + m % 100

    print(f'reading {folder}')
    want = {slot: names for _, slot, names in CUST.LEVELS if names}
    want['account'] = CUST.ACCOUNT_NAMES
    cp, cust = read_master(folder, 'customer',
                           ('Sold-To', 'sold To', 'sold_to'), want)
    pp, prod = read_master(folder, 'product', ('SKU', 'sku', 'Material'),
                           {slot: names for _, slot, names in PRODUCT})
    if not prod:
        print('no product master could be read, so no line can be put on a '
              'division')
        return 1
    if args.online and not cust:
        print('--online needs the customer master, which could not be read')
        return 1
    print(f'  {pp.name}, {len(prod):,} products'
          + (f'; {cp.name}, {len(cust):,} accounts' if cp else ''))

    files = sorted(pick_series(folder, args.sap), key=lambda q: q.name)
    seen: set = set()
    files = [f for f in files
             if not (f.stem.lower() in seen or seen.add(f.stem.lower()))]
    # The month's own export and the ones after it: an order placed in
    # September that left in October is in October's file, and leaving it out
    # is what makes a lead time look shorter than it is.
    files = [f for f in files
             if (month_of([], [], f.stem, say=lambda *a: None) or 0) >= ym]
    if not files:
        print(f'no {args.sap}_* export for {ym} or later in the folder')
        return 1
    print(f'  orders: {", ".join(f.name for f in files)}')

    # A September order shows up twice: open on September's export and
    # shipped on October's. Both are the same line, so they are gathered by
    # their own reference first and the one that has left wins - counted from
    # both files it would be two orders, and averaged it would be one fast and
    # one that never happened.
    rec: dict = {}
    asof = None
    skipped = dupes = 0
    for f in files:
        rows, _ = read_any(f)
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        col = {k: find(head, *names) for k, names in
               (('ref', SAP.S_REF), ('payer', SAP.S_PAYER), ('sku', SAP.S_SKU),
                ('qty', SAP.S_QTY), ('gi', SAP.S_GI), ('made', SAP.S_MADE),
                ('reject', SAP.S_REJECT))}
        miss = [k for k in ('ref', 'sku', 'qty', 'gi', 'made') if col[k] is None]
        if miss:
            print(f'  {f.name}: no ' + ', no '.join(miss) + ' - skipped')
            continue
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
        for r in rows[1:]:
            if not SAP.STAMPED.match(cell(r, col['ref']).upper()):
                continue                       # a marketplace, not the store
            if cell(r, col['reject']):
                continue
            made = SAP.to_date(cell(r, col['made']))
            if made is None or made.year * 100 + made.month != ym:
                continue                       # ordered in another month
            if asof is None or made > asof:
                asof = made
            sku = cell(r, col['sku'])
            if skip_sku and sku.upper().startswith(skip_sku):
                continue
            if args.online:
                c = cust.get(key_norm(cell(r, col['payer']))) or {}
                if CUST.channel_of(c.get('account'), bool(c)) != CUST.ONLINE:
                    continue
            p = prod.get(key_norm(sku)) or {}
            if not p and at < len(PRODUCT) - 1:
                skipped += 1
            name = ((sku if PRODUCT[at][1] == 'sku'
                     else p.get(PRODUCT[at][1]) or '').strip() or '(blank)')
            qty = parse_number(cell(r, col['qty'])) or 0.0
            gi = SAP.to_date(cell(r, col['gi']))
            k = (cell(r, col['ref']).upper(), sku.upper(), qty, made)
            old = rec.get(k)
            if old is not None:
                dupes += 1
                # The one that has left is the one that is true; otherwise the
                # later export, which has seen more of the order's life.
                if old[0] is not None and gi is None:
                    continue
            rec[k] = (gi, made, qty, name)

    pots: dict = {}
    whole = Pot()
    for gi, made, qty, name in rec.values():
        pot = pots.setdefault(name, Pot())
        pot.lines += 1
        whole.lines += 1
        # A line with no despatch date has not left. It is the slow end of the
        # distribution, so it is counted and reported rather than averaged in
        # as nothing or dropped as if it had not happened.
        if gi is None:
            pot.open_units += qty
            whole.open_units += qty
            continue
        d = (gi - made).days
        pot.units += qty
        pot.days += d * qty
        whole.units += qty
        whole.days += d * qty
    print(f'  {len(rec):,} line(s) ordered in {ym}'
          + (f'; {dupes:,} seen on more than one export' if dupes else '')
          + (f'; {skipped:,} had no product master row' if skipped else ''))

    if not whole.lines:
        print(f'\nno order line was placed in {ym}')
        return 1

    name = PRODUCT[at][0]
    print(f'\ndays from order to despatch, {ym} orders, by {name}')
    print(f'  {name:<22}{"units":>12}{"avg days":>11}{"still open":>13}'
          f'{"of units":>10}')
    rows = sorted(pots.items(), key=lambda kv: -(kv[1].units + kv[1].open_units))
    for key, p in rows:
        tot = p.units + p.open_units
        print(f'  {key[:22]:<22}{p.units:>12,.0f}'
              + (f'{p.mean:>11.1f}' if p.mean is not None else f'{"-":>11}')
              + f'{p.open_units:>13,.0f}'
              + (f'{p.open_units / tot * 100:>9.0f}%' if tot else f'{"-":>10}'))
    tot = whole.units + whole.open_units
    print(f'  {"-" * 22}{"-" * 46}')
    print(f'  {"all":<22}{whole.units:>12,.0f}'
          + (f'{whole.mean:>11.1f}' if whole.mean is not None else f'{"-":>11}')
          + f'{whole.open_units:>13,.0f}'
          + (f'{whole.open_units / tot * 100:>9.0f}%' if tot else f'{"-":>10}'))

    if asof:
        print(f'\n  The newest order on the export is {asof}, so a line '
              'ordered near it has\n  had less time to leave than one ordered '
              'early in the month.')
    if whole.open_units:
        print(f'  {whole.open_units:,.0f} unit(s) have not left and are not in '
              'any average above:\n  they are the slow ones, so the real '
              'figure is longer than the one printed.')
    print('\n  An order placed this many days before month end is this '
          f'month\'s revenue;\n  later than that, it is next month\'s.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

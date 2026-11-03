#!/usr/bin/env python3
"""The DTC export: every e-store order line, with its list price on it.

    py tools\\dtc.py                      # what is in the folder
    py tools\\dtc.py --month 2610 --top 20

The order export (`orders_26XX`) says what was sold and for how much. This
export says the same and adds the two things the re-price otherwise has to
go looking for:

    AUD RRP           the list price, on the line, for 98% of them. The
                      promotion plan has one for about seven in ten, so
                      reading it here is not a convenience, it is coverage.
    promotion_rule    the rule that actually applied, rather than the one
                      the plan says covered that day.

What it does not have is a delivery date, so anything about despatch, lead
time or a month's orders landing in the next one cannot be answered from it.
That is the trade, and it is why this does not simply replace the order
export everywhere.

Files are found by name - anything with `dtc` in it - and the month is read
from each row's own `Year` and `Month` columns rather than from the file
name, so `26 DTC Sep.csv` and `26_DTC_Sep.csv` are both fine and a file
holding more than one month is read correctly either way.

Only the standard library, like the rest of the tools.
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import MONTHS, find, parse_number, read_any     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

COLS = {
    'code':   ('Product Code', 'Material', 'SKU'),
    'qty':    ('Quantity', 'Qty'),
    'amt':    ('AUD Revenue excl. GST', 'AUD Revenue', 'Revenue AUD'),
    'usd':    ('USD Revenue excl. GST', 'USD Revenue'),
    'rrp':    ('AUD RRP', 'RRP', 'RRP AUD'),
    'day':    ('Order Creation Date', 'Date', 'Order Date'),
    'cancel': ('Cancelled', 'Is Cancelled'),
    'status': ('order_status', 'Order Status'),
    'portal': ('Portal Group', 'Portal_Group'),
    'dist':   ('Distribution', 'Channel'),
    'rule':   ('promotion_rule', 'Promotion Rule'),
    'year':   ('Year',),
    'month':  ('Month',),
    # The export names its own product chain, so a drift report needs no
    # product master beside it.
    'div':    ('Product Division', 'Division'),
    'cat':    ('Product Category', 'Category'),
    'range':  ('Product Range', 'Range'),
}
# Install and delivery are charged on their own lines of the export and are
# not product revenue. They are named here so it is on the record that the
# money this reads is the product's, which is what a price is about.
NOT_PRODUCT = ('AUD Install Revenue excl. GST',
               'AUD Delivery Revenue excl. GST')


def files(folder: Path) -> list:
    """Every DTC export in the folder, oldest name first."""
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and 'dtc' in p.name.lower()
                  and p.suffix.lower() in ('.csv', '.xlsx', '.xlsm', '.txt'))


def when(v):
    """`31/10/2026`, with or without a time after it."""
    s = str(v or '').strip()
    if not s:
        return None
    s = s.split(' ')[0]
    for f in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def read(folder: Path, months=None, say=print, keep=None) -> list:
    """Order lines as dicts, for the months wanted.

    `months` is a set of YYYYMM; None takes everything. `keep` is an optional
    test on the row, for narrowing to a portal group or a channel.

    A cancelled line is dropped, and so is one that nets to nothing or less:
    a cancelled order was not a sale and a nil line has no price to read. The
    run says how many each was, because a filter nobody can see is a filter
    nobody can check.
    """
    out = []
    seen = collections.Counter()
    for path in files(folder):
        rows, _ = read_any(path)
        if not rows:
            continue
        head = [str(c or '').strip() for c in rows[0]]
        at = {k: find(head, *v) for k, v in COLS.items()}
        if at['code'] is None or at['qty'] is None or at['amt'] is None:
            say(f'  {path.name}: no product, quantity or revenue column '
                '- skipped')
            continue
        cell = lambda r, i: (r[i] if i is not None and i < len(r) else '')
        took = 0
        for r in rows[1:]:
            if len(r) <= at['code']:
                continue
            day = when(cell(r, at['day']))
            ym = None
            if at['year'] is not None and at['month'] is not None:
                y = parse_number(cell(r, at['year']))
                m = parse_number(cell(r, at['month']))
                if y and m:
                    ym = int(y) * 100 + int(m)
            if ym is None and day is not None:
                ym = day.year * 100 + day.month
            if months is not None and ym not in months:
                continue
            seen['read'] += 1
            if str(cell(r, at['cancel'])).strip().lower() in ('yes', 'y',
                                                              'true', '1'):
                seen['cancelled'] += 1
                continue
            qty = parse_number(cell(r, at['qty'])) or 0.0
            amt = parse_number(cell(r, at['amt'])) or 0.0
            if qty <= 0 or amt <= 0:
                seen['nil'] += 1
                continue
            row = {
                'code': str(cell(r, at['code'])).strip(),
                'qty': qty, 'amt': amt,
                'rrp': parse_number(cell(r, at['rrp'])) or 0.0,
                'day': day, 'ym': ym,
                'portal': str(cell(r, at['portal'])).strip(),
                'dist': str(cell(r, at['dist'])).strip(),
                'rule': str(cell(r, at['rule'])).strip(),
                'div': str(cell(r, at['div'])).strip(),
                'cat': str(cell(r, at['cat'])).strip(),
                'range': str(cell(r, at['range'])).strip(),
            }
            if keep and not keep(row):
                seen['filtered'] += 1
                continue
            out.append(row)
            took += 1
        say(f'  {path.name}: {took:,} line(s) kept')
    if out:
        got = sorted({r['ym'] for r in out})
        say(f'  {len(out):,} line(s) over '
            + ', '.join(str(m) for m in got)
            + f'; {len({r["code"] for r in out}):,} product(s)'
            + f', {sum(1 for r in out if r["rrp"] > 0) / len(out) * 100:.0f}%'
            ' with a list price on the line')
    for k in ('cancelled', 'nil', 'filtered'):
        if seen[k]:
            say(f'  {seen[k]:,} line(s) {k}')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM',
                    help='one month, 2610 or 202610 (default all of them)')
    ap.add_argument('--top', type=int, default=0, metavar='N',
                    help='also list the N biggest products')
    ap.add_argument('--fit', action='store_true',
                    help='how well a flat window predicts the newest month '
                         'against a recency-weighted one, and which '
                         'half-life came closest')
    ap.add_argument('--back', type=int, default=6, metavar='N',
                    help='months of history --fit reads (default 6)')
    ap.add_argument('--drift', default=None, metavar='LEVEL',
                    nargs='?', const='cat',
                    choices=('div', 'cat', 'range'),
                    help='how the discount off list moved month by month, '
                         'by division, category or range (default cat)')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        print(f'no such folder: {folder}')
        return 1
    found = files(folder)
    if not found:
        print(f'no file with "dtc" in its name in {folder}')
        return 1
    print(f'reading {folder}')

    months = None
    if args.month:
        ym = args.month if args.month >= 100000 else 2000 * 100 + args.month
        months = {ym}
    rows = read(folder, months)
    if not rows:
        print('nothing to report')
        return 1

    by = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        t = by[r['ym']]
        t[0] += r['qty']
        t[1] += r['amt']
        t[2] += r['qty'] * r['rrp']
    print(f'\n  {"month":<10}{"units":>10}{"AUD":>14}{"off list":>10}')
    for ym in sorted(by):
        q, a, listed = by[ym]
        off = (1 - a / listed) * 100 if listed else None
        print(f'  {MONTHS[(ym % 100) - 1] + " " + str(ym // 100):<10}'
              f'{q:>10,.0f}{a:>14,.0f}'
              f'{("-" if off is None else f"{off:.1f}%"):>10}')

    if args.fit:
        # The re-price takes a window of months, averages the discount in it
        # and applies that to the month after. This asks the only question
        # that settles how to weight that window: which weighting would have
        # got the month that already happened right.
        #
        # It is one month of backtest over a dozen categories, so the sharp
        # bottom of the curve is not to be trusted to a decimal - the shape
        # is. A flat window that is biased in one direction across most of
        # the book is a finding; the exact half-life is a starting point.
        lvl = args.drift if args.drift in ('div', 'cat', 'range') else 'cat'
        seen = sorted({r['ym'] for r in rows})
        if len(seen) < 3:
            print('\n  --fit needs the month to predict and a window before '
                  'it')
        else:
            target = seen[-1]
            window = seen[-1 - args.back:-1]
            pot = collections.defaultdict(lambda: collections.defaultdict(
                lambda: [0.0, 0.0]))
            for r in rows:
                if r['rrp'] <= 0 or (r['ym'] != target
                                     and r['ym'] not in window):
                    continue
                t = pot[r[lvl] or '(blank)'][r['ym']]
                t[0] += r['amt']
                t[1] += r['qty'] * r['rrp']
            use = {}
            for k, by in pot.items():
                if target not in by or by[target][1] <= 0:
                    continue
                hist = [(m, by[m]) for m in window
                        if m in by and by[m][1] > 0]
                if len(hist) < 2:
                    continue
                use[k] = (hist, 1 - by[target][0] / by[target][1],
                          by[target][1])

            def predict(hist, half):
                """The window's discount, weighted by age in months."""
                a = l = 0.0
                for m, (amt, listed) in hist:
                    age = ((window[-1] // 100 - m // 100) * 12
                           + (window[-1] % 100 - m % 100))
                    w = 1.0 if half <= 0 else 0.5 ** (age / half)
                    a += amt * w
                    l += listed * w
                return 1 - a / l if l else None

            print(f'\n  predicting {MONTHS[(target % 100) - 1]} from '
                  + ', '.join(MONTHS[(m % 100) - 1] for m in window)
                  + f'  ({lvl}, {len(use)} group(s))\n')
            print(f'  {"half-life":<12}{"mean |err| pp":>15}'
                  f'{"listed-wtd":>13}{"bias pp":>10}')
            best = None
            for half in (0, 6, 3, 2, 1.5, 1, 0.75, 0.5, 0.35, 0.25):
                errs, wsum, wq, bias = [], 0.0, 0.0, 0.0
                for k, (hist, act, listed) in use.items():
                    p = predict(hist, half)
                    if p is None:
                        continue
                    e = (p - act) * 100
                    errs.append(abs(e))
                    wsum += abs(e) * listed
                    bias += e * listed
                    wq += listed
                if not errs or wq <= 0:
                    continue
                lab = 'flat' if half == 0 else f'{half:g} month'
                print(f'  {lab:<12}{sum(errs) / len(errs):>15.2f}'
                      f'{wsum / wq:>13.2f}{bias / wq:>+10.2f}')
                if best is None or wsum / wq < best[1]:
                    best = (half, wsum / wq)
            if best:
                lab = 'flat' if best[0] == 0 else f'{best[0]:g} month'
                print(f'\n  closest: {lab}')
                print(f'  {"group":<16}{"flat":>8}{"best":>8}{"actual":>8}'
                      f'{"flat err":>10}{"best err":>10}')
                for k, (hist, act, listed) in sorted(
                        use.items(), key=lambda kv: -kv[1][2]):
                    f = predict(hist, 0)
                    d = predict(hist, best[0])
                    if f is None or d is None:
                        continue
                    print(f'  {k[:15]:<16}{f * 100:>8.1f}{d * 100:>8.1f}'
                          f'{act * 100:>8.1f}{(f - act) * 100:>+10.1f}'
                          f'{(d - act) * 100:>+10.1f}')
                print('\n  + means the window predicts more discount than '
                      'the month gave, which')
                print('    prices the month too cheap. Pass the half-life to '
                      'reprice as --decay.')

    if args.drift:
        # The re-price averages a window and applies it to the month after.
        # That is only right where the discount holds still. Where it drifts,
        # a flat average is wrong in one direction for a product early in its
        # life and the other for one late in it, which reads as two
        # categories failing for two reasons when it is one.
        pot = collections.defaultdict(lambda: collections.defaultdict(
            lambda: [0.0, 0.0, 0.0]))
        for r in rows:
            if r['rrp'] <= 0:
                continue
            t = pot[r[args.drift] or '(blank)'][r['ym']]
            t[0] += r['qty']
            t[1] += r['amt']
            t[2] += r['qty'] * r['rrp']
        cols = sorted({m for g in pot.values() for m in g})
        if len(cols) < 2:
            print(f'\n  only {len(cols)} month in the folder - a drift needs '
                  'at least two')
        else:
            w = max(14, max(len(k) for k in pot) + 1)
            head = ''.join(f'{MONTHS[(m % 100) - 1]:>9}' for m in cols)
            print(f'\n  discount off list, by month  ({args.drift})\n')
            print(f'  {args.drift:<{w}}{head}{"swing":>9}{"units":>9}')
            for k in sorted(pot, key=lambda k: -sum(
                    v[0] for v in pot[k].values())):
                cells, got = '', []
                for m in cols:
                    q, a, l = pot[k].get(m, [0.0, 0.0, 0.0])
                    if q < 20 or l <= 0:
                        cells += f'{"-":>9}'
                        continue
                    off = (1 - a / l) * 100
                    got.append(off)
                    cells += f'{off:>8.1f}%'
                q = sum(v[0] for v in pot[k].values())
                swing = (f'{max(got) - min(got):>8.1f}%' if len(got) > 1
                         else f'{"-":>9}')
                print(f'  {k[:w - 1]:<{w}}{cells}{swing}{q:>9,.0f}')
            print('\n  swing is the widest month-to-month gap. A category '
                  'that moves more than a few points')
            print('  is one a flat six-month average will price wrong in '
                  'whichever direction it has drifted.')

    if args.top:
        pot = collections.defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            t = pot[r['code']]
            t[0] += r['qty']
            t[1] += r['amt']
        big = sorted(pot.items(), key=lambda kv: -kv[1][1])[:args.top]
        print(f'\n  the {len(big)} biggest:')
        print(f'  {"product":<24}{"units":>9}{"AUD":>13}{"ASP":>10}')
        for c, (q, a) in big:
            print(f'  {c[:23]:<24}{q:>9,.0f}{a:>13,.0f}{a / q:>10,.0f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Which orders became a month's sales? Test it rather than assume it.

    py tools\\cohort.py                  # the whole test
    py tools\\cohort.py --profile        # describe the two order files and stop

The hypothesis being tested: **August's sales are August's COMPLETED orders,
plus the July orders that were not COMPLETED in July and completed later.**

That is a claim about the data, and the data can be asked. Every order line is
put in a bucket by which file it came from and what its status says, several
rules are built out of those buckets, and each rule's predicted units are
compared with the profit file's - overall, and product by product.

The rule that reproduces the month best wins. If the hypothesis is right it
should win by a distance; if something else wins, that is the finding.

Units are the comparator, never money: both files carry a quantity that means
one thing - a unit shipped - while the amounts differ by tax, by currency and
by what each file counts as revenue.

What this cannot do is see a shipment date. If the order export grows one, this
test stops being necessary - the answer is then read off the row.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from promo_match import NAMES as O_NAMES, to_date              # noqa: E402
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_file, pick_latest, read_any)
from reconcile import (O_AMT, O_QTY, O_SKU, O_STATUS, P_AMT,   # noqa: E402
                       P_CUST, P_QTY, P_SKU, classify)

ROOT = Path(__file__).resolve().parent.parent

O_ORDER = ('Order Code', 'Order No', 'Order Number', 'Order ID', 'order_code',
           'Sales Order', 'Document', 'Order')
O_LINE = ('Line', 'Line No', 'Item', 'Line Item', 'Position')
O_DATE = O_NAMES['date']
# Any date column that is not the order date is the thing this whole file exists
# to work around - so it is looked for, and said out loud when it is there.
O_SHIP = ('Shipping Date', 'Ship Date', 'Shipped Date', 'Delivery Date',
          'Delivered Date', 'Dispatch Date', 'Completion Date', 'Completed Date',
          'Invoice Date', 'Billing Date', 'Actual Delivery Date')


def is_dead(status: str) -> bool:
    """A status that can never become a later month's revenue.

    Cancelled, and every flavour of return. An order still in flight is carried
    forward; one that was called off or came back is not carried anywhere.
    """
    t = str(status or '').upper()
    return 'CANCEL' in t or 'RETURN' in t or 'NOT_AUTHORIZED' in t


class Side:
    """One order export, read into lines and tallied."""

    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.lines = []            # (ident, sku, status, qty, amt, date)
        self.status: dict[str, list[float]] = {}
        self.dates: list = []
        self.has_order_no = False
        self.has_ship_date = None


def read_side(name, path, say=print) -> Side:
    rows, info = read_any(path)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    s = Side(name, path)
    say(f'  {path.name}: {info["format"]}, {len(body):,} rows, {len(head)} columns')

    col = {'sku': find(head, *O_SKU), 'qty': find(head, *O_QTY),
           'amt': find(head, *O_AMT), 'status': find(head, *O_STATUS),
           'order': find(head, *O_ORDER), 'line': find(head, *O_LINE),
           'date': find(head, *O_DATE), 'ship': find(head, *O_SHIP)}
    for what in ('sku', 'qty', 'status', 'order', 'date', 'ship'):
        i = col[what]
        say(f'    {what:<6} ' + (repr(head[i]) if i is not None
                                 else '-- not found --'))
    s.has_order_no = col['order'] is not None
    s.has_ship_date = head[col['ship']] if col['ship'] is not None else None

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    for n, r in enumerate(body):
        ident = (key_norm(cell(r, col['order'])), key_norm(cell(r, col['sku'])),
                 key_norm(cell(r, col['line']))) if s.has_order_no else (n,)
        status = (cell(r, col['status']) or '(blank)').upper()
        qty = parse_number(cell(r, col['qty'])) or 0.0
        amt = parse_number(cell(r, col['amt'])) or 0.0
        d = to_date(cell(r, col['date'])) if col['date'] is not None else None
        s.lines.append((ident, key_norm(cell(r, col['sku'])), status, qty, amt, d))
        t = s.status.setdefault(status, [0.0, 0.0, 0.0])
        t[0] += 1
        t[1] += qty
        t[2] += amt
        if d:
            s.dates.append(d)
    return s


def describe(s: Side, done: set, say=print) -> None:
    say(f'\n{s.name} - {len(s.lines):,} line(s), {len(s.status)} status(es)')
    if s.dates:
        say(f'  order dates {min(s.dates)} .. {max(s.dates)}'
            + ('' if min(s.dates).month == max(s.dates).month else
               '   <- more than one month in this file'))
    else:
        say('  no order date could be read, so what the file covers is its name')
    if s.has_ship_date:
        say(f'  it carries {s.has_ship_date!r} - a second date. None of the '
            'inference below is needed if that column is filled in: the month a '
            'unit belongs to is then read off the row.')
    say(f'  {"status":<28} {"lines":>8} {"units":>10} {"revenue":>14}  counted as')
    live = 0.0
    for st, t in sorted(s.status.items(), key=lambda kv: -kv[1][1]):
        tag = 'COMPLETED' if st in done else classify(st)
        if tag not in ('COMPLETED',):
            live += t[1] if tag not in ('returned',) else 0
        say(f'  {st[:28]:<28} {t[0]:>8,.0f} {t[1]:>10,.0f} {t[2]:>14,.0f}  {tag}')
    total = sum(t[1] for t in s.status.values())
    pct = (total - live) / total * 100 if total else 0
    say(f'  {pct:.0f}% of units are in a finished state. A month-end snapshot '
        'leaves plenty in flight; a file re-exported later has almost nothing '
        'left, and then it cannot say when anything moved.')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--before', default='26 DTC Jul', metavar='NAME',
                    help='the earlier order export (default: 26 DTC Jul)')
    ap.add_argument('--after', default='26 DTC Aug', metavar='NAME',
                    help='the month being explained (default: 26 DTC Aug)')
    ap.add_argument('--profit', default=None,
                    help='default: the highest-numbered profit_* file')
    ap.add_argument('--completed', default='COMPLETED', metavar='LIST',
                    help='the status(es) that mean the money was booked '
                         '(default COMPLETED, comma-separated)')
    ap.add_argument('--online', default=CUST.ONLINE, metavar='NAME',
                    help=f'the channel the profit side is kept to '
                         f'(default {CUST.ONLINE}); "" keeps every channel')
    ap.add_argument('--profile', action='store_true',
                    help='describe the two order files and stop')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'cohort_sku.csv'))
    ap.add_argument('--keep-dead', action='store_true',
                    help='count cancelled and returned orders as carry-over. '
                         'They never become a later month, so by default they '
                         'are left out of the open buckets')
    ap.add_argument('--skip-sku', metavar='PREFIX', default='',
                    help='comma-separated product-code prefixes to leave out '
                         'of the comparison, e.g. SMC-AU- for service plans '
                         'that are ordered but never appear in the profit file')
    ap.add_argument('--top', type=int, default=12)
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    paths = {'before': pick_file(folder, args.before),
             'after': pick_file(folder, args.after)}
    for what, p in paths.items():
        if p is None:
            name = args.before if what == 'before' else args.after
            print(f'no file named like {name!r} in {folder.resolve()}',
                  file=sys.stderr)
            print('  files there: '
                  + ', '.join(sorted(q.name for q in folder.iterdir()
                                     if q.is_file())[:20]), file=sys.stderr)
            return 2
    pp = (pick_file(folder, args.profit) if args.profit
          else pick_latest(folder, 'profit'))
    if pp is None:
        print(f'no profit export in {folder.resolve()}', file=sys.stderr)
        return 2

    done = {t.strip().upper() for t in args.completed.split(',') if t.strip()}
    print('reading:')
    before = read_side(args.before, paths['before'])
    after = read_side(args.after, paths['after'])
    describe(before, done)
    describe(after, done)

    # ── do the two files share lines? ──────────────────────────────────────
    # This is what decides whether the earlier file can say anything about what
    # moved. If an order line appears in both, its status in each is a before
    # and an after, and the difference between them is the month.
    shared = {}
    if before.has_order_no and after.has_order_no:
        after_by = {}
        for ident, sku, st, qty, amt, d in after.lines:
            after_by.setdefault(ident, []).append(st)
        for ident, sku, st, qty, amt, d in before.lines:
            if ident in after_by:
                shared[ident] = (st, after_by[ident][0])
        print(f'\nshared lines: {len(shared):,} of {len(before.lines):,} line(s) '
              f'in {before.name} appear in {after.name} too')
        if shared:
            moved = sum(1 for a, b in shared.values() if a != b)
            print(f'  {moved:,} of them changed status between the two files')
            pairs: dict[tuple, int] = {}
            for a, b in shared.values():
                if a != b:
                    pairs[(a, b)] = pairs.get((a, b), 0) + 1
            for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1])[:8]:
                print(f'    {a} -> {b}: {n:,}')
            print('  a line that was unfinished in the earlier file and finished '
                  'in the later one moved in between, which is the only direct '
                  'evidence either file carries about timing')
            if len(shared) > len(before.lines) * 0.2:
                print()
                print(f'  READ THIS FIRST: {after.name} is not a month of '
                      'orders - it is the order book,')
                print('  and it already holds the July lines. Every rule below '
                      'that adds July to it')
                print('  counts those units twice, and "Aug COMPLETED only" is '
                      'already the hypothesis:')
                print('  the July carry-over is inside it.')
        else:
            print(f'  none - so {after.name} holds its own month only, and the '
                  'earlier file can be read as a snapshot beside it rather than '
                  'as a before-and-after of the same lines')
    else:
        print('\nno order number in one of the files, so their lines cannot be '
              'matched to each other; the rules below that need a before-and-'
              'after are skipped')

    if args.profile:
        return 0

    # ── what the month actually sold ───────────────────────────────────────
    rows, info = read_any(pp)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    print(f'\n{pp.name}: {info["format"]}, {len(body):,} rows')
    p_i = {k: find(head, *v) for k, v in
           {'sku': P_SKU, 'cust': P_CUST, 'qty': P_QTY, 'amt': P_AMT}.items()}
    if p_i['sku'] is None or p_i['qty'] is None:
        print('  the profit export carries no product code or no quantity, so '
              'there is nothing to compare against', file=sys.stderr)
        return 1

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    drop = tuple(t.strip().upper() for t in args.skip_sku.split(',') if t.strip())

    def skipped(code):
        return bool(drop) and str(code).upper().startswith(drop)

    cust = {}
    cp = pick_latest(folder, 'customer')
    if cp and p_i['cust'] is not None and args.online:
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'),
                      {'account': CUST.ACCOUNT_NAMES}, say=lambda *a: None)
    sales: dict[str, float] = {}
    sales_amt = 0.0
    off = 0.0
    for r in body:
        qty = parse_number(cell(r, p_i['qty'])) or 0.0
        if cust:
            c = cust.get(key_norm(cell(r, p_i['cust'])))
            channel = CUST.channel_of(c['account']) if c else CUST.NO_MATCH
            if args.online and channel != args.online:
                off += qty
                continue
        code = key_norm(cell(r, p_i['sku']))
        if skipped(code):
            continue
        sales[code] = sales.get(code, 0.0) + qty
        sales_amt += parse_number(cell(r, p_i['amt'])) or 0.0
    actual = sum(sales.values())
    print(f'  {args.online or "every channel"}: {actual:,.0f} units over '
          f'{len(sales):,} product(s), {sales_amt:,.0f}'
          + (f'   ({off:,.0f} units left out as not {args.online})' if off else ''))

    # ── the buckets every rule is built from ───────────────────────────────
    def bucket(side, want_done):
        out: dict[str, float] = {}
        for ident, sku, st, qty, amt, d in side.lines:
            if (st in done) != want_done:
                continue
            if skipped(sku):
                continue
            # An open order is carried forward; a cancelled or returned one is
            # not carried anywhere, so it is no part of a later month.
            if not want_done and not args.keep_dead and is_dead(st):
                continue
            out[sku] = out.get(sku, 0.0) + qty
        return out

    aug_done = bucket(after, True)
    aug_rest = bucket(after, False)
    jul_done = bucket(before, True)
    jul_open = bucket(before, False)
    jul_then = {}
    for ident, sku, st, qty, amt, d in before.lines:
        was_then = shared.get(ident)
        if was_then and st not in done and was_then[1] in done:
            jul_then[sku] = jul_then.get(sku, 0.0) + qty

    def merge(*parts):
        out: dict[str, float] = {}
        for p in parts:
            for k, v in p.items():
                out[k] = out.get(k, 0.0) + v
        return out

    rules = [
        ('Aug COMPLETED only',
         'the month is its own completed orders and nothing else',
         aug_done),
        ('Aug COMPLETED + Jul not-completed',
         "your hypothesis, read loosely: every July order still open at the "
         "end of July landed in August",
         merge(aug_done, jul_open)),
        ('Aug COMPLETED + Jul open that later completed',
         'your hypothesis, read strictly - needs the two files to share lines',
         merge(aug_done, jul_then) if jul_then else None),
        ('Aug COMPLETED + Jul COMPLETED',
         'both months booked in August, which would mean July was not booked '
         'in July',
         merge(aug_done, jul_done)),
        ('every Aug order, whatever the status',
         'the month is everything ordered in it',
         merge(aug_done, aug_rest)),
        ('Aug shipped-ish (the reconcile reading)',
         'COMPLETED, DELIVERED, SHIPPED and the rest of the shipped list',
         {sku: q for sku, q in
          ((sku, sum(qty for i2, s2, st2, qty, a2, d2 in after.lines
                     if s2 == sku and classify(st2) == 'shipped'))
           for sku in {s2 for _, s2, _, _, _, _ in after.lines})}),
    ]

    print('\nhow well each reading reproduces the month')
    print(f'  {"rule":<44} {"units":>11} {"vs sales":>9} {"per-product err":>16}')
    scored = []
    for name, why, pred in rules:
        if pred is None:
            print(f'  {name[:44]:<44} {"-":>11} {"-":>9} {"not available":>16}')
            continue
        total = sum(pred.values())
        err = sum(abs(pred.get(k, 0.0) - sales.get(k, 0.0))
                  for k in set(pred) | set(sales))
        rel = err / actual if actual else 0
        scored.append((rel, name, why, pred, total))
        print(f'  {name[:44]:<44} {total:>11,.0f} '
              f'{(total / actual * 100 if actual else 0):>8.0f}% {rel * 100:>15.0f}%')
    print('  "vs sales" is the total against the profit file; "per-product err" '
          'adds up every\n  product\'s miss in both directions, so a rule that '
          'is right in total and wrong\n  product by product cannot hide behind '
          'the total.')

    if not scored:
        print('\nnothing could be scored.', file=sys.stderr)
        return 1
    scored.sort()
    best = scored[0]
    rel, name, why, pred, total = best
    print(f'\nbest fit: {name}')
    print(f'  {why}')
    print(f'  {total:,.0f} units against the profit file\'s {actual:,.0f} '
          f'({total / actual * 100:.0f}%), missing {rel * 100:.0f}% of the month '
          'once every product is counted both ways')
    second = scored[1] if len(scored) > 1 else None
    if second:
        print(f'  next best is {second[1]} at {second[0] * 100:.0f}%'
              + (' - too close to call between them'
                 if second[0] - rel < 0.03 else ''))

    hyp = [s for s in scored if s[1].startswith('Aug COMPLETED + Jul')]
    plain = [s for s in scored if s[1] == 'Aug COMPLETED only']
    if hyp and plain:
        better = min(h[0] for h in hyp) < plain[0][0]
        print('\nthe hypothesis: adding July\'s unfinished orders '
              + ('does make the month fit better, so the carry-over is real and '
                 'this is the reading to build on'
                 if better else
                 'does not improve the fit - August\'s own completed orders '
                 'explain the month as well or better on their own, so either '
                 'there is little carry-over or the status is not what decides '
                 'it'))

    # ── where the miss actually lives ──────────────────────────────────────
    # A product the orders have and the profit file does not is a different
    # thing from a product both have and disagree about. Lumped together they
    # read as one error; apart, one of them is usually not merchandise at all.
    groups = {'in both': [0.0, 0], 'ordered, never sold': [0.0, 0],
              'sold, never ordered': [0.0, 0]}
    for k in set(pred) | set(sales):
        miss = abs(pred.get(k, 0.0) - sales.get(k, 0.0))
        where = ('in both' if k in pred and k in sales
                 else 'ordered, never sold' if k in pred
                 else 'sold, never ordered')
        groups[where][0] += miss
        groups[where][1] += 1
    print('\nwhere that miss sits')
    for g, (miss, n) in groups.items():
        print(f'  {g:<22} {n:>6,} product(s) {miss:>10,.0f} unit(s) '
              f'{miss / actual * 100 if actual else 0:>6.0f}% of the month')
    if groups['ordered, never sold'][0] > actual * 0.02:
        print('  a product that is ordered every month and never sold is usually '
              'not merchandise -\n  a service plan, a subscription, a bundle '
              'header. --skip-sku PREFIX leaves them out.')

    # ── the month's timing, which is what all of this was for ──────────────
    carry_in = sum(jul_open.values())
    carry_out = sum(aug_rest.values())
    own = sum(aug_done.values())
    print(f'\nthe month in and out, on the winning reading')
    print(f'  {after.name} completed in its own month   {own:>10,.0f} units '
          f'{own / actual * 100:>5.0f}% of what was sold')
    print(f'  carried in from {before.name:<22} {carry_in:>10,.0f} units '
          f'{carry_in / actual * 100:>5.0f}%')
    print(f'  carried out, still open at month end   {carry_out:>10,.0f} units '
          f'{carry_out / actual * 100:>5.0f}%')
    net = carry_in - carry_out
    print(f'  net                                    {net:>+10,.0f} units '
          f'{net / actual * 100:>+5.0f}%')
    if abs(net) > actual * 0.05:
        print('  the month took in more than it handed on, so its revenue is '
              'flattered by that\n  difference - a backlog cleared, not demand '
              'earned in the month' if net > 0 else
              '  the month handed on more than it took in, so its revenue is '
              'understated by that\n  difference - demand it earned and has '
              'not yet booked')

    # ── the detail, per product ────────────────────────────────────────────
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['sku', 'sales units', 'best rule units', 'difference',
                    'aug completed', 'aug other', 'jul completed', 'jul open',
                    'jul open then completed'])
        for sku in sorted(set(sales) | set(pred), key=lambda k:
                          -abs(pred.get(k, 0.0) - sales.get(k, 0.0))):
            w.writerow([sku, round(sales.get(sku, 0.0), 2),
                        round(pred.get(sku, 0.0), 2),
                        round(pred.get(sku, 0.0) - sales.get(sku, 0.0), 2),
                        round(aug_done.get(sku, 0.0), 2),
                        round(aug_rest.get(sku, 0.0), 2),
                        round(jul_done.get(sku, 0.0), 2),
                        round(jul_open.get(sku, 0.0), 2),
                        round(jul_then.get(sku, 0.0), 2)])
    print(f'\nthe worst-fitting products, under the best rule:')
    worst = sorted(set(sales) | set(pred),
                   key=lambda k: -abs(pred.get(k, 0.0) - sales.get(k, 0.0)))
    print(f'  {"product":<18} {"sold":>9} {"rule":>9} {"diff":>9}')
    for sku in worst[:args.top]:
        s_ = sales.get(sku, 0.0)
        p_ = pred.get(sku, 0.0)
        print(f'  {sku[:18]:<18} {s_:>9,.0f} {p_:>9,.0f} {p_ - s_:>+9,.0f}')
    print(f'\n-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

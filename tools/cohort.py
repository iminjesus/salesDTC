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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from promo_match import NAMES as O_NAMES, to_date              # noqa: E402
from rawdata import (MONTHS, find, key_norm, master,           # noqa: E402
                     month_before, month_name, month_of, parse_number,
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


# The booking rule as the store's own status list reads it. A status either
# books money this month, takes money back this month, or has not happened yet
# and belongs to a later one.
#
# The returns are negative rather than excluded because the profit file counts
# quantity **net of returns**: a return completed in September is already
# subtracted there, so the order side has to subtract it too or the two are
# counting different things.
POSITIVE = ('COMPLETED', 'PICKUP_COMPLETE')
NEGATIVE = ('RETURN_COMPLETED', 'RETURN_REFUNDED',
            'PARTIAL_RETURN_COMPLETED', 'PARTIAL_RETURN_REFUNDED')


def booking(status, positive=POSITIVE, negative=NEGATIVE) -> str:
    """'+' books, '-' takes back, 'carry' has not happened yet.

    Matched on the whole status, not on a word inside it: RETURN_REFUNDED is
    money back and RETURN_SHIPPING_PREPARATION is a return that has not landed,
    and nothing but the exact name separates them.
    """
    t = re.sub(r'[^A-Z0-9]+', '_', str(status or '').upper()).strip('_')
    if t in positive:
        return '+'
    if t in negative:
        return '-'
    return 'carry'


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

    def month(self):
        """The month this export covers, as YYYYMM, or None if it spans more."""
        if not self.dates:
            return None
        months = {d.year * 100 + d.month for d in self.dates}
        return months.pop() if len(months) == 1 else None

    def span(self):
        return (min(self.dates), max(self.dates)) if self.dates else (None, None)


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
    ap.add_argument('--before', default=None, metavar='NAME',
                    help='the earlier order export. By default the one named '
                         'for the month before the profit file covers')
    ap.add_argument('--after', default=None, metavar='NAME',
                    help='the month being explained. By default the one named '
                         'for the month the profit file covers')
    ap.add_argument('--any-month', action='store_true',
                    help='test the orders that were named even when their dates '
                         'say they are other months')
    ap.add_argument('--profit', default=None,
                    help='default: the highest-numbered profit_* file')
    ap.add_argument('--completed', default='COMPLETED', metavar='LIST',
                    help='the status(es) that mean the money was booked, for '
                         'the COMPLETED-only readings (default COMPLETED)')
    ap.add_argument('--positive', default=','.join(POSITIVE), metavar='LIST',
                    help='statuses that book money this month '
                         f'(default {", ".join(POSITIVE)})')
    ap.add_argument('--negative', default=','.join(NEGATIVE), metavar='LIST',
                    help='statuses that take money back this month. The profit '
                         'file counts quantity net of returns, so these are '
                         f'subtracted, not dropped (default {", ".join(NEGATIVE)})')
    ap.add_argument('--online', default=CUST.ONLINE, metavar='NAME',
                    help=f'the channel the profit side is kept to '
                         f'(default {CUST.ONLINE}); "" keeps every channel')
    ap.add_argument('--profile', action='store_true',
                    help='describe the two order files and stop')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'cohort_sku.csv'))
    ap.add_argument('--next-profit', metavar='NAME',
                    help="the NEXT month's profit export, e.g. profit_2609. The "
                         'units this month carries out have to turn up in it, so '
                         'this is the one test the rule cannot have been fitted '
                         'to - it was not used to choose the rule')
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
    # Which month is being explained decides which two order exports explain
    # it. Reading them off the profit file beats remembering to name them, and
    # beats comparing August's orders with September's sales by default.
    pp = (pick_file(folder, args.profit) if args.profit
          else pick_latest(folder, 'profit'))
    if pp is None:
        print(f'no profit export in {folder.resolve()}', file=sys.stderr)
        return 2
    p_rows, p_info = read_any(pp)
    p_head = [h.strip() for h in p_rows[0]]
    p_body = p_rows[1:]
    ym = month_of(p_head, p_body, pp.stem, say=lambda *a: None)
    want = {'after': args.after or (month_name(ym) if ym else None),
            'before': args.before or (month_name(month_before(ym)) if ym else None)}
    if ym:
        print(f'{pp.name} covers {ym}, so the orders that explain it are '
              f'{want["before"]} and {want["after"]}')
    paths = {}
    for what, name in want.items():
        hit = pick_file(folder, name) if name else None
        if hit is None:
            print(f'no file named like {name!r} in {folder.resolve()}',
                  file=sys.stderr)
            print('  order-looking files there: '
                  + ', '.join(sorted(q.name for q in folder.iterdir()
                                     if q.is_file() and 'dtc' in q.stem.lower())),
                  file=sys.stderr)
            return 2
        paths[what] = hit

    done = {t.strip().upper() for t in args.completed.split(',') if t.strip()}
    print('reading:')
    before = read_side(want['before'], paths['before'])
    after = read_side(want['after'], paths['after'])
    # An order export holding another month explains nothing about this one,
    # and every number below it would be arithmetic on the wrong rows.
    if ym and not args.any_month:
        for who, side, expect in (('after', after, ym),
                                  ('before', before, month_before(ym))):
            got = side.month()
            if got is None or got == expect:
                continue
            lo, hi = side.span()
            print(f'\n{side.path.name} is not the {expect} export: its orders '
                  f'run {lo} .. {hi}.\n{pp.name} covers {ym}, so --{who} wants '
                  f'the {expect} export. --any-month tests it anyway.',
                  file=sys.stderr)
            return 2
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

    # ── and do they share order numbers, never mind the lines? ─────────────
    # The line test above is (order, product). An order split across the two
    # months - one product fulfilled in July, another in August - shares its
    # number without sharing a line, and that is worth knowing on its own: it
    # says the files are cut by something other than the order.
    if before.has_order_no and after.has_order_no:
        def numbers(side):
            out: dict[str, list] = {}
            for ident, sku, st, qty, amt, d in side.lines:
                if not ident[0]:
                    continue
                v = out.setdefault(ident[0], [0, 0.0, set(), set()])
                v[0] += 1
                v[1] += qty
                v[2].add(sku)
                v[3].add(st)
            return out

        b_no, a_no = numbers(before), numbers(after)
        both = set(b_no) & set(a_no)
        print(f'\norder numbers: {len(b_no):,} in {before.name}, '
              f'{len(a_no):,} in {after.name}, {len(both):,} in both')
        if both:
            units = sum(b_no[n][1] + a_no[n][1] for n in both)
            split = sum(1 for n in both if not (b_no[n][2] & a_no[n][2]))
            print(f'  {units:,.0f} unit(s) sit on a number that appears in both '
                  f'files; {split:,} of those numbers\n  carry no product in '
                  'common, so they are one order cut across the two months')
            print(f'  {"order":<20} {before.name[:14]:<30} {after.name[:14]:<30}')
            for n in sorted(both, key=lambda k: -(b_no[k][1] + a_no[k][1]))[:8]:
                left = f'{b_no[n][0]} line(s) ' + ','.join(sorted(b_no[n][3]))[:20]
                right = f'{a_no[n][0]} line(s) ' + ','.join(sorted(a_no[n][3]))[:20]
                print(f'  {str(n)[:20]:<20} {left:<30} {right:<30}')
        else:
            print('  not one number is in both, so the two files are cut by the '
                  'order and nothing\n  crosses between them - the carry-over '
                  'can only be inferred from the statuses')

    if args.profile:
        return 0

    # ── what the month actually sold ───────────────────────────────────────
    head, body, info = p_head, p_body, p_info
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

    # The signed reading: a status either books, takes back, or waits. Returns
    # come out negative because the profit file is already net of them.
    pos = tuple(t.strip().upper() for t in args.positive.split(',') if t.strip())
    neg = tuple(t.strip().upper() for t in args.negative.split(',') if t.strip())

    def signed(side, want, drop_cancelled=False):
        """want '+-' for the month's own booking, 'carry' for what it hands on."""
        out: dict[str, float] = {}
        for ident, sku, st, qty, amt, d in side.lines:
            if skipped(sku):
                continue
            verdict = booking(st, pos, neg)
            if want == 'carry':
                if verdict != 'carry':
                    continue
                if drop_cancelled and 'CANCEL' in st.upper():
                    continue
                out[sku] = out.get(sku, 0.0) + qty
            else:
                if verdict == 'carry':
                    continue
                out[sku] = out.get(sku, 0.0) + (qty if verdict == '+' else -qty)
        return out

    aug_signed = signed(after, '+-')
    aug_carry = signed(after, 'carry')
    jul_carry = signed(before, 'carry')
    jul_carry_live = signed(before, 'carry', drop_cancelled=True)

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

    # The rules are named after the months they are actually about, so a run
    # explaining September does not print a table that says August.
    def label(side):
        ym = side.month()
        return MONTHS[(ym % 100) - 1] if ym else side.name

    now, was = label(after), label(before)
    rules = [
        (f'{now} COMPLETED only',
         'the month is its own completed orders and nothing else',
         aug_done),
        (f'{now} COMPLETED + {was} not-completed',
         f'your hypothesis, read loosely: every {was} order still open at the '
         f'end of {was} landed in {now}',
         merge(aug_done, jul_open)),
        (f'{now} COMPLETED + {was} open that later completed',
         'your hypothesis, read strictly - needs the two files to share lines',
         merge(aug_done, jul_then) if jul_then else None),
        (f'{now} COMPLETED + {was} COMPLETED',
         f'both months booked in {now}, which would mean {was} was not booked '
         f'in {was}',
         merge(aug_done, jul_done)),
        (f'every {now} order, whatever the status',
         'the month is everything ordered in it',
         merge(aug_done, aug_rest)),
        (f'{now} shipped-ish (the reconcile reading)',
         'COMPLETED, DELIVERED, SHIPPED and the rest of the shipped list',
         {sku: q for sku, q in
          ((sku, sum(qty for i2, s2, st2, qty, a2, d2 in after.lines
                     if s2 == sku and classify(st2) == 'shipped'))
           for sku in {s2 for _, s2, _, _, _, _ in after.lines})}),
        (f'{now} signed + everything {was} had not finished',
         'the status list read in full: completed and picked up add, returns '
         'subtract, everything else waits for a later month',
         merge(aug_signed, jul_carry)),
        (f'{now} signed + {was} unfinished, cancelled dropped',
         'the same, except a cancelled order is carried nowhere rather than '
         'into the next month',
         merge(aug_signed, jul_carry_live)),
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

    hyp = [s for s in scored if s[1].startswith(f'{now} COMPLETED + {was}')
           and 'COMPLETED + ' + was + ' COMPLETED' not in s[1]]
    plain = [s for s in scored if s[1] == f'{now} COMPLETED only']
    if hyp and plain:
        better = min(h[0] for h in hyp) < plain[0][0]
        print(f'\nthe hypothesis: adding {was}\'s unfinished orders '
              + ('does make the month fit better, so the carry-over is real and '
                 'this is the reading to build on'
                 if better else
                 f'does not improve the fit - {now}\'s own completed orders '
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

    # ── how the two readings of the status list differ ─────────────────────
    # Gross, off the lines: the per-product buckets are already netted, so a
    # product with a sale and a return against it would hide both.
    def gross(side, sign):
        return sum(qty for _, sku, st, qty, _, _ in side.lines
                   if not skipped(sku) and booking(st, pos, neg) == sign)

    print('\nthe status list, read two ways')
    print(f'  {"":<34} {now:>12} {was:>12}')
    for what, a, b in (
            ('books this month (+)', gross(after, '+'), gross(before, '+')),
            ('takes back this month (-)', gross(after, '-'), gross(before, '-')),
            ('waits for a later month', sum(aug_carry.values()),
             sum(jul_carry.values())),
            ('  of which cancelled',
             sum(aug_carry.values()) - sum(signed(after, 'carry', True).values()),
             sum(jul_carry.values()) - sum(jul_carry_live.values())),
            ('COMPLETED only, for comparison', sum(aug_done.values()),
             sum(jul_done.values())),
            ('not COMPLETED, returns dropped', sum(aug_rest.values()),
             sum(jul_open.values()))):
        print(f'  {what:<34} {a:>12,.0f} '
              + (f'{b:>12,.0f}' if b is not None else f'{"":>12}'))

    # ── the month's timing, which is what all of this was for ──────────────
    best_signed = best[1].endswith('had not finished') or 'cancelled dropped' in best[1]
    carry_in = sum((jul_carry if best[1].endswith('had not finished')
                    else jul_carry_live if 'cancelled dropped' in best[1]
                    else jul_open).values())
    carry_out = sum((aug_carry if best_signed else aug_rest).values())
    own = sum((aug_signed if best_signed else aug_done).values())
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

    # ── the one test the rule was not fitted to ────────────────────────────
    # Everything above was scored against the month the rule was chosen on, so
    # it had every chance to fit. What the month carries out is a claim about a
    # month the rule never saw, and that month either contains those units or
    # it does not.
    if args.next_profit:
        np_ = pick_file(folder, args.next_profit)
        if np_ is None:
            print(f'\nno file named like {args.next_profit!r} to check the '
                  'carry-out against', file=sys.stderr)
        else:
            n_rows, n_info = read_any(np_)
            n_head = [h.strip() for h in n_rows[0]]
            n_body = n_rows[1:]
            n_i = {k: find(n_head, *v) for k, v in
                   {'sku': P_SKU, 'cust': P_CUST, 'qty': P_QTY}.items()}
            nxt: dict[str, float] = {}
            for r in n_body:
                q = parse_number(cell(r, n_i['qty'])) or 0.0
                if cust and args.online:
                    c = cust.get(key_norm(cell(r, n_i['cust'])))
                    if (CUST.channel_of(c['account']) if c
                            else CUST.NO_MATCH) != args.online:
                        continue
                code = key_norm(cell(r, n_i['sku']))
                if skipped(code):
                    continue
                nxt[code] = nxt.get(code, 0.0) + q
            out_u = sum(aug_rest.values())
            nxt_u = sum(nxt.values())
            print(f'\nout of sample: {np_.name}, {n_info["format"]}, '
                  f'{len(n_body):,} rows')
            print(f'  {after.name} carries out {out_u:,.0f} unit(s); the next '
                  f'month sold {nxt_u:,.0f}')
            # A carry-out bigger than the month it lands in is the one way this
            # can be plainly wrong, and it can be checked product by product.
            over = {k: v - nxt.get(k, 0.0) for k, v in aug_rest.items()
                    if v - nxt.get(k, 0.0) > 0.5}
            short = sum(over.values())
            print(f'  {len(over):,} product(s) carry out more than the next '
                  f'month sold of them, {short:,.0f} unit(s) over in total '
                  f'({short / out_u * 100 if out_u else 0:.0f}% of the carry-out)')
            if out_u:
                print('  the carry-out is '
                      + (f'{out_u / nxt_u * 100:.0f}% of the next month - so the '
                         'rule says that much of it was already ordered'
                         if nxt_u else 'larger than the next month entirely'))
            print('  this does not prove the rule; it is the thing that would '
                  'have disproved it.\n  A carry-out that will not fit in the '
                  'month it lands in cannot be right, and\n  the shortfall '
                  'above is how much of it does not fit.')
            if out_u and short > out_u * 0.25:
                print('  more than a quarter of it does not fit, which is a '
                      'real problem with the rule')

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

#!/usr/bin/env python3
"""Do the shipped online orders turn up in the profit file?

    py tools\\reconcile.py --statuses    # list the order statuses and stop
    py tools\\reconcile.py               # -> docs/reconcile_sku.csv

Two files counting different things. `26 DTC Aug` is online orders - an order
placed is not a sale, and one that has not shipped is not August revenue.
`profit_2608_3` is sales, online and offline together, so its online half is
what the shipped orders should have become.

So: keep the orders whose status says they shipped, keep the profit rows whose
customer is online, and put them side by side by product.

Units are the comparator, not money. Both files carry a quantity that means one
thing - a unit shipped - while the amounts differ by tax, by currency and by
what each file counts as revenue. Money is reported beside it, with the ratio,
because a systematic difference there is worth seeing and is not a reconciling
difference.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                       # noqa: E402
from rawdata import (find, key_norm, master, parse_number,    # noqa: E402
                     pick_file, pick_latest, read_any)

ROOT = Path(__file__).resolve().parent.parent

# What an order status has to say before the units behind it count as August
# sales. Read as whole words against the status, upper-cased.
SHIPPED = ('COMPLETE', 'COMPLETED', 'DELIVERED', 'SHIPPED', 'DISPATCHED',
           'FULFILLED', 'CLOSED', 'PICKED UP', 'COLLECTED')
NOT_SHIPPED = ('CANCEL', 'CANCELLED', 'PENDING', 'PREPARATION', 'PROCESSING',
               'CREATED', 'PLACED', 'HOLD', 'FAILED', 'REJECTED', 'RETURNED',
               'REFUNDED', 'PAYMENT', 'BACKORDER', 'RESERVED')

O_SKU = ('Product Code', 'SKU', 'Material', 'Model Code', 'Product Number')
O_QTY = ('Quantity', 'Qty', 'Units')
O_AMT = ('AUD Revenue excl. GST', 'Net Amount', 'Amount', 'Revenue')
O_STATUS = ('order_status', 'Order Status', 'Status')
P_SKU = ('Material', 'Product Number', 'SKU', 'Material Code', 'Model Code')
P_CUST = ('Customer', 'Payer', 'sold To', 'Sold-To')
P_QTY = ('Quantity(Net)', 'Net Sales Qty', 'Qty', 'Quantity')
P_AMT = ('*Net Sales', 'Net Sales', 'Net Sales Amt')


def classify(status: str) -> str:
    """'shipped', 'not shipped', or 'unknown' - never a silent guess."""
    t = re.sub(r'[^A-Z ]+', ' ', str(status or '').upper()).strip()
    if not t:
        return 'unknown'
    words = set(t.split())
    if any(w in words or w in t for w in NOT_SHIPPED):
        return 'not shipped'
    if any(w in words or w in t for w in SHIPPED):
        return 'shipped'
    return 'unknown'


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--orders', default='26 DTC Aug')
    ap.add_argument('--profit', default=None,
                    help='default: the highest-numbered profit_* file')
    ap.add_argument('--statuses', action='store_true',
                    help='list the order statuses with how each is read, and stop')
    ap.add_argument('--shipped', metavar='LIST',
                    help='comma-separated statuses to count as shipped, replacing '
                         'the built-in list. Everything else is not shipped')
    ap.add_argument('--online', default=CUST.ONLINE, metavar='NAME',
                    help=f'the channel the profit file is filtered to '
                         f'(default {CUST.ONLINE}); "" keeps every channel')
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--tolerance', type=float, default=0.5, metavar='UNITS',
                    help='how far the two unit counts may differ and still be '
                         'called equal (default 0.5). A profit file that splits '
                         'a line across payers leaves fractions behind, and '
                         'those are rounding, not a missing sale')
    ap.add_argument('--top', type=int, default=15)
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    op = pick_file(folder, args.orders)
    pp = (pick_file(folder, args.profit) if args.profit
          else pick_latest(folder, 'profit'))
    for what, p in (('order', op), ('profit', pp)):
        if p is None:
            print(f'no {what} file in {folder.resolve()}', file=sys.stderr)
            return 2

    print('reading:')
    o_rows, o_info = read_any(op)
    o_head, o_body = [h.strip() for h in o_rows[0]], o_rows[1:]
    print(f'  {op.name}: {o_info["format"]}, {len(o_body):,} rows')
    p_rows, p_info = read_any(pp)
    p_head, p_body = [h.strip() for h in p_rows[0]], p_rows[1:]
    print(f'  {pp.name}: {p_info["format"]}, {len(p_body):,} rows')

    o_i = {k: find(o_head, *v) for k, v in
           {'sku': O_SKU, 'qty': O_QTY, 'amt': O_AMT, 'status': O_STATUS}.items()}
    p_i = {k: find(p_head, *v) for k, v in
           {'sku': P_SKU, 'cust': P_CUST, 'qty': P_QTY, 'amt': P_AMT}.items()}
    print('\ncolumns:')
    for side, head, got in ((op.name, o_head, o_i), (pp.name, p_head, p_i)):
        for what, i in got.items():
            print(f'  {side[:18]:<18} {what:<7} '
                  + (repr(head[i]) if i is not None else '-- not found --'))
    missing = [k for k, i in o_i.items() if i is None and k != 'status'] \
        + [k for k, i in p_i.items() if i is None and k != 'cust']
    if missing:
        print(f'\ncannot compare without {", ".join(missing)}', file=sys.stderr)
        return 1

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── how the statuses are read ──────────────────────────────────────────
    keep = None
    if args.shipped:
        keep = {s.strip().upper() for s in args.shipped.split(',') if s.strip()}
    tally: dict[str, list[float]] = {}
    for r in o_body:
        st = cell(r, o_i['status']) or '(blank)'
        t = tally.setdefault(st, [0.0, 0.0, 0.0])
        t[0] += 1
        t[1] += parse_number(cell(r, o_i['qty'])) or 0.0
        t[2] += parse_number(cell(r, o_i['amt'])) or 0.0

    def verdict(st: str) -> str:
        if keep is not None:
            return 'shipped' if st.upper() in keep else 'not shipped'
        return classify(st)

    print(f'\norder statuses in {op.name} ({len(tally)} of them):')
    print(f'  {"status":<30} {"lines":>8} {"units":>10} {"revenue":>14}   read as')
    for st, t in sorted(tally.items(), key=lambda kv: -kv[1][0]):
        print(f'  {st[:30]:<30} {t[0]:>8,.0f} {t[1]:>10,.0f} {t[2]:>14,.0f}'
              f'   {verdict(st)}')
    unknown = [st for st in tally if verdict(st) == 'unknown']
    if unknown:
        print(f'\n  {len(unknown)} status(es) are not recognised either way and '
              'are left out of the comparison:')
        print('    ' + ', '.join(unknown[:8]))
        print('    name the ones that mean shipped with --shipped "A,B,C"')
    if args.statuses:
        return 0
    return compare(args, op, pp, o_head, o_body, p_head, p_body, o_i, p_i,
                   verdict, folder, cell)


def compare(args, op, pp, o_head, o_body, p_head, p_body, o_i, p_i,
            verdict, folder, cell) -> int:
    # ── the orders that shipped ────────────────────────────────────────────
    orders: dict[str, list[float]] = {}
    waiting: dict[str, float] = {}
    spell: dict[str, str] = {}
    kept = dropped = 0
    for r in o_body:
        code = key_norm(cell(r, o_i['sku']))
        if verdict(cell(r, o_i['status']) or '(blank)') != 'shipped':
            dropped += 1
            # Kept per product: where the profit file shows more units than
            # shipped, what is waiting to ship is the first thing to compare
            # the excess against.
            waiting[code] = waiting.get(code, 0.0) \
                + (parse_number(cell(r, o_i['qty'])) or 0.0)
            continue
        kept += 1
        spell.setdefault(code, cell(r, o_i['sku']))
        v = orders.setdefault(code, [0.0, 0.0, 0.0])
        v[0] += 1
        v[1] += parse_number(cell(r, o_i['qty'])) or 0.0
        v[2] += parse_number(cell(r, o_i['amt'])) or 0.0
    print(f'\nshipped: {kept:,} of {kept + dropped:,} order line(s) counted, '
          f'{dropped:,} left out')

    # ── the profit rows that are online ────────────────────────────────────
    cust = {}
    cp = pick_file(folder, 'customer_2608')
    if cp and p_i['cust'] is not None and args.online:
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'),
                      {'account': CUST.ACCOUNT_NAMES})
        print(f'customer master: {len(cust):,} accounts')

    sales: dict[str, list[float]] = {}
    by_channel: dict[str, list[float]] = {}
    matched = 0
    for r in p_body:
        c = cust.get(key_norm(cell(r, p_i['cust']))) if cust else None
        matched += bool(c)
        channel = (CUST.channel_of(c['account']) if c
                   else CUST.NO_MATCH if cust else '(all)')
        qty = parse_number(cell(r, p_i['qty'])) or 0.0
        amt = parse_number(cell(r, p_i['amt'])) or 0.0
        agg = by_channel.setdefault(channel, [0.0, 0.0, 0.0])
        agg[0] += 1
        agg[1] += qty
        agg[2] += amt
        if args.online and channel != args.online:
            continue
        code = key_norm(cell(r, p_i['sku']))
        spell.setdefault(code, cell(r, p_i['sku']))
        v = sales.setdefault(code, [0.0, 0.0, 0.0])
        v[0] += 1
        v[1] += qty
        v[2] += amt
    if cust:
        print(f'profit rows by channel (the comparison keeps '
              f'{args.online or "all of them"}):')
        for ch, v in sorted(by_channel.items(), key=lambda kv: -kv[1][1]):
            print(f'  {ch[:22]:<22} {v[0]:>8,.0f} rows {v[1]:>11,.0f} units '
                  f'{v[2]:>16,.0f}')

    # ── side by side ───────────────────────────────────────────────────────
    codes = set(orders) | set(sales)
    rows = []
    buckets = {'agree': 0, 'differ': 0, 'orders only': 0, 'profit only': 0}
    tot = [0.0, 0.0, 0.0, 0.0]          # order units, sales units, $ , $
    for code in codes:
        o = orders.get(code, [0.0, 0.0, 0.0])
        s = sales.get(code, [0.0, 0.0, 0.0])
        if code in orders and code in sales:
            where = ('agree' if abs(s[1] - o[1]) <= args.tolerance else 'differ')
        else:
            where = 'orders only' if code in orders else 'profit only'
        buckets[where] += 1
        tot[0] += o[1]
        tot[1] += s[1]
        tot[2] += o[2]
        tot[3] += s[2]
        rows.append([spell.get(code, code), where, int(o[0]), o[1], s[1],
                     round(s[1] - o[1], 2), round(waiting.get(code, 0.0), 2),
                     round(o[2], 2), round(s[2], 2), round(s[2] - o[2], 2)])

    print(f'\n{"":<24}{"shipped orders":>18}{"online sales":>18}{"difference":>16}')
    print(f'  {"units":<22}{tot[0]:>18,.0f}{tot[1]:>18,.0f}'
          f'{tot[1] - tot[0]:>+16,.0f}')
    print(f'  {"amount":<22}{tot[2]:>18,.0f}{tot[3]:>18,.0f}'
          f'{tot[3] - tot[2]:>+16,.0f}')
    if tot[0]:
        print(f'  {"units matched":<22}{tot[1] / tot[0] * 100:>17,.1f}%')
    if tot[2]:
        print(f'  {"amount ratio":<22}{tot[3] / tot[2]:>18,.3f}'
              '   (the two count money differently; a steady ratio is a basis,'
              ' not a gap)')

    print(f'\n{len(codes):,} product code(s): '
          + ', '.join(f'{n:,} {k}' for k, n in buckets.items() if n)
          + f'  (equal within {args.tolerance:g} unit(s))')

    # The codes that do not line up are the whole point, so lead with them.
    def show(title, picked, key):
        if not picked:
            return
        print(f'\n{title} ({len(picked):,}):')
        print(f'  {"product":<26}{"shipped":>9}{"sales":>9}{"diff":>9}'
              f'{"waiting":>9}{"order $":>13}{"sales $":>13}')
        for row in sorted(picked, key=key)[:args.top]:
            print(f'  {str(row[0])[:26]:<26}{row[3]:>9,.0f}{row[4]:>9,.0f}'
                  f'{row[5]:>+9,.0f}{row[6]:>9,.0f}{row[7]:>13,.0f}'
                  f'{row[8]:>13,.0f}')
        if len(picked) > args.top:
            print(f'  ... and {len(picked) - args.top:,} more in the csv')

    show('shipped but not in the profit file',
         [r for r in rows if r[1] == 'orders only'], lambda r: -r[3])
    show('in the profit file but not in the shipped orders',
         [r for r in rows if r[1] == 'profit only'], lambda r: -r[4])
    show('in both, but the units disagree',
         [r for r in rows if r[1] == 'differ'], lambda r: -abs(r[5]))
    # The reverse error: more units sold than shipped means the profit file
    # counted something the order file says is still waiting.
    over = [r for r in rows if r[5] > args.tolerance]
    if over:
        covered = sum(1 for r in over if r[6] >= r[5] - args.tolerance)
        print(f'\n{len(over):,} product(s) show more units sold than shipped. '
              f'For {covered:,} of them the excess is no larger than what is '
              'still waiting to ship, so the profit file counted orders the '
              'order file has not shipped yet.')

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'reconcile_sku.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Product', 'Where', 'Order lines', 'Shipped units',
                    'Sales units', 'Units difference', 'Units still to ship',
                    'Order amount', 'Sales amount', 'Amount difference'])
        w.writerows(sorted(rows, key=lambda r: -abs(r[5])))
    print(f'\n-> {path.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

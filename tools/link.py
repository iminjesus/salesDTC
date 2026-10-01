#!/usr/bin/env python3
"""Join the store's orders to SAP's, so the despatch date can be read.

    py tools\\link.py                      # -> docs/link_2609.csv
    py tools\\link.py --sample 12          # show matched and unmatched examples

Everything the cohort test does is inference: no export said when a unit
shipped, so the month it belonged to had to be argued from a status. The SAP
sales-order export says it outright - `Goods Issue Date` is the despatch - and
it carries the store's own order number in `Customer Reference (Header)`.

    26 DTC Sep   Order Code              46262020
    orders_2609  Customer Reference      AU260930-46262020
                 Goods Issue Date        1/10/2026   <- the answer, not a guess

So the two are joined on that reference with the date prefix taken off. The
prefix is a date the store stamped on the order and it is not always the day
SAP created the document, which is exactly why it is dropped rather than
matched on. Within a month the number behind it is unique, and the run says so
rather than assuming it.

The reference shape also separates the business: an order placed in the DTC
store carries one, and Amazon, Myer, MyDeal and eBay do not. Which rows are the
store's is therefore read off the data rather than configured.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                         # noqa: E402
from rawdata import (find, key_norm, master, month_before,      # noqa: E402
                     month_name, month_of, norm_stem, parse_number,
                     pick_file, pick_series, read_any)
from reconcile import P_CUST, P_QTY, P_SKU                      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# SAP's sales-order export.
S_REF = ('Customer Reference (Header)', 'Customer Reference', 'Purchase Order',
         'PO Number', 'Customer PO')
S_DOC = ('Sales Document', 'Sales Order', 'Document Number', 'Order Number')
S_SKU = ('Material', 'Material Number', 'Product Code', 'SKU')
S_QTY = ('Confirmed Quantity (Item)', 'Order Quantity (Item)', 'Quantity',
         'Order Quantity')
S_AMT = ('Net Value (Item)', 'Net Value', 'Net Price')
S_GI = ('Goods Issue Date', 'Actual GI Date', 'Despatch Date')
S_DEL = ('Delivery Date', 'Requested Delivery Date')
S_MADE = ('Created On', 'Creation Date', 'Entered On')
S_WHO = ('Sold-To Party Name', 'Sold-to Party Name', 'Customer Name')
S_STATUS = ('Overall Status Item Description', 'Overall Status')
S_DSTAT = ('Overall Delivery Status Item Description',
           'Overall Delivery Status (All Items)')
# SAP fills Goods Issue Date on every schedule line. On one that has gone it is
# the day it went; on one that has not it is the day it is meant to go. A date
# past the day the export was taken is a plan whatever the status says, and the
# two are never added together - see docs/DESPATCH.md.
DELIVERED = ('COMPLETED', 'DELIVERED', 'FULLY DELIVERED')

# The store's own export.
D_ORDER = ('Order Code', 'Order No', 'Order Number', 'Order ID', 'order_code')
D_SKU = ('Product Code', 'SKU', 'Material', 'Model Code', 'Product Number')
D_QTY = ('Quantity', 'Qty', 'Units')
D_STATUS = ('order_status', 'Order Status', 'Status')

# AU260930-46262020: two letters, a six-digit date, then the order's own number.
STAMPED = re.compile(r'^([A-Z]{2})(\d{6})-(\d+)$')


def order_key(v) -> str:
    """The order's own number, with the store's date stamp taken off.

    Loose on purpose, like every other key in these tools: case, spaces and
    punctuation are ignored, and the leading zeros SAP and a spreadsheet
    disagree about are stripped.
    """
    t = re.sub(r'\s+', '', str(v or '')).upper()
    m = STAMPED.match(t)
    if m:
        t = m.group(3)
    t = re.sub(r'[^A-Z0-9]', '', t)
    return t.lstrip('0') or t


def to_date(v):
    for f in ('%d/%m/%Y', '%Y-%m-%d', '%d-%b-%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(str(v or '').strip(), f).date()
        except ValueError:
            pass
    return None


def cell(r, i):
    return (r[i].strip() if i is not None and i < len(r) else '')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--sap', default=None, metavar='NAME',
                    help="one SAP sales-order export instead of every orders_* "
                         'in the folder')
    ap.add_argument('--dtc', default=None, metavar='NAME',
                    help="the store's export (default: the one named for the "
                         "same month, e.g. 26 DTC Sep)")
    ap.add_argument('--profit', default=None, metavar='NAME',
                    help='the month to check the despatches against (default: '
                         'every profit_* the despatches can reach)')
    ap.add_argument('--online', default=CUST.ONLINE, metavar='NAME',
                    help=f'the channel the profit side is kept to '
                         f'(default {CUST.ONLINE})')
    ap.add_argument('--skip-sku', metavar='PREFIX', default='',
                    help='product-code prefixes to leave out, e.g. SMC-AU-')
    ap.add_argument('--sample', type=int, default=6,
                    help='how many examples of each kind to print')
    ap.add_argument('--out', default=None,
                    help='default: docs/link_<month>.csv')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    # One export per month, csv ahead of the workbook.
    months, seen = [], {}
    for cand in ([pick_file(folder, args.sap)] if args.sap
                 else pick_series(folder, 'orders')):
        if cand is None:
            continue
        key = norm_stem(cand.stem)
        seen.setdefault(key, []).append(cand)
    for key, cands in seen.items():
        months.append(cands)
    if not months:
        print(f'no SAP order export in {folder.resolve()}', file=sys.stderr)
        return 2

    done = []
    for cands in months:
        got = one(folder, cands, args)
        if got:
            done.append(got)
    if not done:
        return 1
    return settle(folder, args, done)


def one(folder, want, args):
    # The same export is often in the folder twice, as a csv and as a workbook,
    # and a spreadsheet round-trip renames headers. So the candidates are tried
    # in turn and the first one that actually carries the columns is used,
    # rather than the newest name winning and the run failing on it.
    print('reading:')
    sp = s_head = s_body = S = None
    for cand in want:
        rows, info = read_any(cand)
        head = [h.strip() for h in rows[0]]
        got = {k: find(head, *v) for k, v in
               {'ref': S_REF, 'doc': S_DOC, 'sku': S_SKU, 'qty': S_QTY,
                'amt': S_AMT, 'gi': S_GI, 'del': S_DEL, 'made': S_MADE,
                'who': S_WHO, 'status': S_STATUS, 'dstat': S_DSTAT}.items()}
        missing = [k for k in ('ref', 'gi', 'made') if got[k] is None]
        print(f'  {cand.name}: {info["format"]}, {len(rows) - 1:,} rows, '
              f'{len(head)} columns'
              + ('' if not missing else
                 f'   - no {", ".join(missing)}, so another candidate is tried'))
        if missing:
            continue
        sp, s_head, s_body, S = cand, head, rows[1:], got
        break
    if sp is None:
        print('\nNone of those exports carries both a customer reference and a '
              'goods issue date.\nWithout the reference there is nothing to join '
              'on; without the date there is\nnothing worth joining for. Name '
              'one with --sap.', file=sys.stderr)
        return None
    for what in ('ref', 'doc', 'sku', 'qty', 'gi', 'made'):
        i = S[what]
        print(f'    {what:<6} ' + (repr(s_head[i]) if i is not None
                                   else '-- not found --'))

    # The month: from Created On, which is the only date in this export that
    # means "when did SAP record this" - Document Date is copied from whatever
    # document a return or credit was raised against.
    made = [to_date(cell(r, S['made'])) for r in s_body]
    made = [d for d in made if d]
    ym = (max(collections.Counter(d.year * 100 + d.month for d in made).items(),
              key=lambda kv: kv[1])[0] if made
          else month_of(s_head, s_body, sp.stem, say=lambda *a: None))
    # The day the export was taken, which is the line between what happened and
    # what is only scheduled. The last order it recorded is the best proxy.
    asof = max(made) if made else None
    if made:
        print(f'  created {min(made)} .. {max(made)}  -> the {ym} export, '
              f'taken on or about {asof}')

    dp = pick_file(folder, args.dtc or (month_name(ym) if ym else ''))
    if dp is None:
        print(f'\nno store export named like '
              f'{args.dtc or (month_name(ym) if ym else "?")!r}; nothing to join '
              'to.', file=sys.stderr)
        return None
    d_rows, d_info = read_any(dp)
    d_head = [h.strip() for h in d_rows[0]]
    d_body = d_rows[1:]
    print(f'  {dp.name}: {d_info["format"]}, {len(d_body):,} rows')
    D = {k: find(d_head, *v) for k, v in
         {'order': D_ORDER, 'sku': D_SKU, 'qty': D_QTY,
          'status': D_STATUS}.items()}
    for what in ('order', 'sku', 'qty', 'status'):
        i = D[what]
        print(f'    {what:<6} ' + (repr(d_head[i]) if i is not None
                                   else '-- not found --'))
    if D['order'] is None:
        print('\nThe store export carries no order number this build recognises, '
              'so the two\ncannot be joined. Columns: '
              + ', '.join(d_head[:20]), file=sys.stderr)
        return None

    # ── what shape is the reference in? ────────────────────────────────────
    stamped = plain = 0
    sap_by_key: dict[str, list] = collections.defaultdict(list)
    whose = collections.Counter()
    for r in s_body:
        raw = cell(r, S['ref'])
        if STAMPED.match(raw.upper()):
            stamped += 1
            whose[cell(r, S['who'])] += 1
        elif raw:
            plain += 1
        if raw:
            sap_by_key[order_key(raw)].append(r)
    print(f'\n{stamped:,} of {len(s_body):,} SAP line(s) carry a store-stamped '
          f'reference like AU260930-46262020;\n  {plain:,} carry something else.')
    if whose:
        print('  the stamped ones belong to: '
              + ', '.join(f'{k} ({n:,})' for k, n in whose.most_common(4)))
    other = collections.Counter(cell(r, S['who']) for r in s_body
                                if cell(r, S['ref'])
                                and not STAMPED.match(cell(r, S['ref']).upper()))
    if other:
        print('  the rest belong to: '
              + ', '.join(f'{k} ({n:,})' for k, n in other.most_common(4))
              + '\n  - marketplaces rather than the store, so the shape of the '
              'reference is what\n  separates the two, with nothing to configure.')

    # Dropping the date is only safe while the number behind it is unique.
    tails: dict[str, set] = collections.defaultdict(set)
    for r in s_body:
        raw = cell(r, S['ref']).upper()
        m = STAMPED.match(raw)
        if m:
            tails[m.group(3)].add(raw)
        clash = None
    clash = {t: v for t, v in tails.items() if len(v) > 1}
    print(f'  dropping the date stamp: {len(tails):,} distinct number(s), '
          + (f'{len(clash):,} of them under more than one stamp - '
             f'e.g. {sorted(next(iter(clash.values())))[:2]}'
             if clash else 'none of them under more than one stamp, so the '
             'number alone is a safe key'))

    # ── the join ───────────────────────────────────────────────────────────
    hit = collections.Counter()
    rows_out = []
    seen_sap = set()
    for r in d_body:
        key = order_key(cell(r, D['order']))
        qty = parse_number(cell(r, D['qty'])) or 0.0
        sap = sap_by_key.get(key) or []
        sku = cell(r, D['sku'])
        # One store order can become several SAP documents - a split delivery -
        # so the line is matched on the product within the order where it can be.
        mine = [x for x in sap
                if order_key(cell(x, S['sku'])) == order_key(sku)] or sap
        if not sap:
            hit['no SAP document'] += 1
            rows_out.append((cell(r, D['order']), sku, qty, '', '', '',
                             'no SAP document', ''))
            continue
        hit['matched' if mine is not sap else 'matched, product differs'] += 1
        for x in mine[:1]:
            seen_sap.add(id(x))
            gi = to_date(cell(x, S['gi']))
            left = bool(gi) and cell(x, S['dstat']).upper() in DELIVERED \
                and (not asof or gi <= asof)
            rows_out.append((cell(r, D['order']), sku, qty,
                             cell(x, S['doc']), cell(x, S['gi']),
                             gi.strftime('%Y-%m') if gi else '',
                             'left' if left else 'due' if gi else 'no date',
                             cell(x, S['status'])))
    total = sum(hit.values())
    print(f'\njoined {dp.name} -> {sp.name}')
    for k, n in hit.most_common():
        print(f'  {k:<28} {n:>8,}  {n / total * 100:>5.1f}%')
    unmatched_sap = sum(1 for r in s_body
                        if STAMPED.match(cell(r, S['ref']).upper())
                        and id(r) not in seen_sap)
    print(f'  {"SAP lines never matched":<28} {unmatched_sap:>8,}  '
          '(a store order the export does not cover, or a split this join '
          'kept once)')

    # ── the payoff: which month did it actually leave in? ──────────────────
    went = collections.Counter()
    due = collections.Counter()
    nothing = 0.0
    for _, _, qty, _, _, m, state, _ in rows_out:
        if state == 'left':
            went[m] += qty
        elif state == 'due':
            due[m] += qty
        else:
            nothing += qty
    print('\nwhen the store\'s orders left, read off Goods Issue Date')
    print(f'  (a date after {asof} is when a line is meant to go, not when it '
          'went - counted apart)')
    print(f'  {"":<12} {"left":>12} {"due to leave":>14}')
    for m in sorted(set(went) | set(due)):
        own = ym and m == f'{ym // 100}-{ym % 100:02d}'
        print(f'  {m:<12} {went.get(m, 0):>12,.0f} {due.get(m, 0):>14,.0f}'
              + ('   <- the month they were ordered' if own else ''))
    if nothing:
        print(f'  {"no date":<12} {"":>12} {nothing:>14,.0f}')
    own = went.get(f'{ym // 100}-{ym % 100:02d}', 0.0) if ym else 0.0
    tot = sum(went.values()) + sum(due.values()) + nothing
    if tot:
        later = sum(v for k, v in went.items()
                    if ym and k > f'{ym // 100}-{ym % 100:02d}')
        print(f'\n  {own / tot * 100:.0f}% of these orders had left by {asof}, '
              'in the month they were ordered.')
        if later:
            print(f'  {later / tot * 100:.0f}% had already left in a later one.')
        print(f'  {(sum(due.values()) + nothing) / tot * 100:.0f}% had not left '
              'yet. This is the carry-over the cohort\n  test had to infer - '
              'part of it measured, the rest still only scheduled.')

    if args.sample:
        print(f'\nmatched, first {args.sample}:')
        print(f'  {"store order":<22} {"product":<18} {"SAP doc":<12} '
              f'{"goods issue":<12} {"":<8} SAP status')
        for row in [r for r in rows_out if r[3]][:args.sample]:
            print(f'  {row[0][:22]:<22} {row[1][:18]:<18} {row[3]:<12} '
                  f'{row[4]:<12} {row[6]:<8} {row[7]}')
        miss = [r for r in rows_out if not r[3]]
        if miss:
            print(f'\nunmatched, first {args.sample}:')
            for row in miss[:args.sample]:
                print(f'  {row[0][:22]:<22} {row[1][:18]:<18} '
                      f'(key {order_key(row[0])!r})')

    out = Path(args.out) if args.out else ROOT / 'docs' / f'link_{ym or "x"}.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['store order', 'product', 'units', 'sap document',
                    'goods issue date', 'goods issue month',
                    'left or due', 'sap status'])
        w.writerows(rows_out)
    print(f'  -> {out.resolve()}')
    return {'ym': ym, 'rows': rows_out, 'asof': asof,
            'sap': sp.name, 'dtc': dp.name}



def settle(folder, args, done):
    """Which month did each unit's revenue fall in, and does the month agree?

    Nothing here is inferred. A unit belongs to the month its goods issue fell
    in, whatever month it was ordered in and whatever the store's status column
    says - so the months are pooled across every export read, and the total for
    each is put beside what the profit file reports for it.

    A month can only be checked where the exports can see all of it. September's
    own export, taken on 30 September, knows nothing of what left in October, so
    a month is only scored when every export that could hold its despatches has
    been read.
    """
    drop = tuple(t.strip().upper() for t in args.skip_sku.split(',') if t.strip())

    def skipped(code):
        return bool(drop) and str(code).upper().startswith(drop)

    # Two buckets per month, kept apart. An export taken at the end of its own
    # month records next month's despatches as scheduled, because they have not
    # happened yet - so a month's revenue is what left in it plus what was due
    # to leave in it, and only the first of those is a measurement.
    by_month: dict[str, dict] = {}
    due_by_month: dict[str, dict] = {}
    for got in done:
        for order, sku, qty, doc, gid, m, state, status in got['rows']:
            if not m or skipped(sku) or state not in ('left', 'due'):
                continue
            into = by_month if state == 'left' else due_by_month
            into.setdefault(m, {})
            k = key_norm(sku)
            into[m][k] = into[m].get(k, 0.0) + qty
    due_month = {m: sum(v.values()) for m, v in due_by_month.items()}

    print('\n' + '=' * 72)
    print('revenue by the month the goods actually left, pooled over '
          + ', '.join(g['sap'] for g in done))
    print(f'  {"":<10} {"left":>12} {"still only due":>16} {"both":>12}')
    for m in sorted(set(by_month) | set(due_month)):
        a = sum(by_month.get(m, {}).values())
        b = due_month.get(m, 0)
        print(f'  {m:<10} {a:>12,.0f} {b:>16,.0f} {a + b:>12,.0f}')

    # A month is only accounted for when the exports cover the orders that could
    # ship into it: its own, and the month before's. Nothing here reaches back
    # further, so a month whose predecessor is missing will come up short by
    # whatever that month was still shipping.
    have = {g['ym'] for g in done if g['ym']}
    covered = {ym for ym in have if month_before(ym) in have}
    if have:
        print('\n  order exports read: '
              + ', '.join(str(y) for y in sorted(have)))
        print('  months whose carry-in is also covered: '
              + (', '.join(str(y) for y in sorted(covered)) if covered else 'none')
              + '\n  - a month needs its own export and the one before it. '
              'Without the earlier one\n  it is short by whatever that month '
              'was still shipping into it.')

    # A month is complete only if an export exists that was taken after it ended.
    asofs = [g['asof'] for g in done if g['asof']]
    latest = max(asofs) if asofs else None
    print(f'\n  the latest export was taken {latest}, so a month ending after '
          'that\n  cannot have all of its despatches in hand yet.')

    # ── against the profit file ────────────────────────────────────────────
    cust, cp = {}, None
    for cand in pick_series(folder, 'customer'):
        try:
            cust = master(cand, ('Sold-To', 'sold To', 'sold_to'),
                          {'account': CUST.ACCOUNT_NAMES}, say=lambda *a: None)
        except (ValueError, OSError) as e:
            print(f'  {cand.name}: {e} - trying the next customer export')
            continue
        if cust:
            cp = cand
            break
    print(f'  customer master: {cp.name}, {len(cust):,} accounts' if cp else
          '  no customer master could be read, so the channel is not filtered')

    wanted = ([pick_file(folder, args.profit)] if args.profit
              else pick_series(folder, 'profit'))
    checked = set()
    for pp in [x for x in wanted if x]:
        rows, info = read_any(pp)
        head = [h.strip() for h in rows[0]]
        body = rows[1:]
        ym = month_of(head, body, pp.stem, say=lambda *a: None)
        m = f'{ym // 100}-{ym % 100:02d}' if ym else None
        if not m or m in checked:
            continue
        checked.add(m)
        i = {k: find(head, *v) for k, v in
             {'sku': P_SKU, 'cust': P_CUST, 'qty': P_QTY}.items()}
        if i['sku'] is None or i['qty'] is None:
            continue
        sold: dict[str, float] = {}
        for r in body:
            q = parse_number(cell(r, i['qty'])) or 0.0
            if cust and args.online:
                c = cust.get(key_norm(cell(r, i['cust'])))
                if (CUST.channel_of(c['account']) if c
                        else CUST.NO_MATCH) != args.online:
                    continue
            code = key_norm(cell(r, i['sku']))
            if skipped(code):
                continue
            sold[code] = sold.get(code, 0.0) + q
        actual = sum(sold.values())
        if not actual:
            continue
        both = {}
        for src in (by_month.get(m, {}), due_by_month.get(m, {})):
            for k, v in src.items():
                both[k] = both.get(k, 0.0) + v

        def score(pred):
            return (sum(pred.values()),
                    sum(abs(pred.get(k, 0.0) - sold.get(k, 0.0))
                        for k in set(pred) | set(sold)))

        gone_u, gone_e = score(by_month.get(m, {}))
        both_u, both_e = score(both)
        print(f'\n{pp.name} - {m}, {args.online or "every channel"}: '
              f'{actual:,.0f} units over {len(sold):,} product(s)')
        print(f'  {"goods issue in " + m:<34} {"units":>10} {"vs sales":>9} '
              f'{"per-product err":>16}')
        print(f'  {"left - measured":<34} {gone_u:>10,.0f} '
              f'{gone_u / actual * 100:>8.1f}% {gone_e / actual * 100:>15.1f}%')
        if both_u != gone_u:
            print(f'  {"left + due to leave":<34} {both_u:>10,.0f} '
                  f'{both_u / actual * 100:>8.1f}% '
                  f'{both_e / actual * 100:>15.1f}%')
        print('  No status was read and no carry-over was inferred: a unit is in '
              'the month its\n  goods issue fell in. Compare with '
              "docs/COHORT.md's figures for the same month.")
        if ym and month_before(ym) not in have:
            print(f'  This month is short its carry-in: there is no '
                  f'{month_before(ym)} order export, so\n  whatever that month '
                  'was still shipping into this one is missing from both rows.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

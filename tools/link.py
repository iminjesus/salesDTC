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
from rawdata import (find, month_name, month_of, parse_number,  # noqa: E402
                     pick_file, pick_series, read_any)

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
S_STATUS = ('Overall Status Item Description', 'Overall Status',
            'Overall Delivery Status Item Description')

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
                    help="SAP's sales-order export (default: the latest orders_*)")
    ap.add_argument('--dtc', default=None, metavar='NAME',
                    help="the store's export (default: the one named for the "
                         "same month, e.g. 26 DTC Sep)")
    ap.add_argument('--sample', type=int, default=6,
                    help='how many examples of each kind to print')
    ap.add_argument('--out', default=None,
                    help='default: docs/link_<month>.csv')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    want = ([pick_file(folder, args.sap)] if args.sap
            else pick_series(folder, 'orders'))
    want = [p for p in want if p]
    if not want:
        print(f'no SAP order export in {folder.resolve()} - looked for '
              f'{args.sap or "orders_*"}', file=sys.stderr)
        return 2

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
                'who': S_WHO, 'status': S_STATUS}.items()}
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
        return 1
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
    if made:
        print(f'  created {min(made)} .. {max(made)}  -> the {ym} export')

    dp = pick_file(folder, args.dtc or (month_name(ym) if ym else ''))
    if dp is None:
        print(f'\nno store export named like '
              f'{args.dtc or (month_name(ym) if ym else "?")!r}; nothing to join '
              'to.', file=sys.stderr)
        return 2
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
        return 1

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
            rows_out.append((cell(r, D['order']), sku, qty, '', '', '', ''))
            continue
        hit['matched' if mine is not sap else 'matched, product differs'] += 1
        for x in mine[:1]:
            seen_sap.add(id(x))
            gi = to_date(cell(x, S['gi']))
            rows_out.append((cell(r, D['order']), sku, qty,
                             cell(x, S['doc']), cell(x, S['gi']),
                             gi.strftime('%Y-%m') if gi else '',
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
    by_month = collections.Counter()
    units = collections.Counter()
    for _, _, qty, _, _, m, _ in rows_out:
        by_month[m or '(not despatched / unmatched)'] += 1
        units[m or '(not despatched / unmatched)'] += qty
    print('\nwhen the store\'s orders actually left, read off Goods Issue Date:')
    for m, n in sorted(by_month.items()):
        print(f'  {m:<28} {n:>8,} line(s) {units[m]:>10,.0f} units')
    own = units.get(f'{ym // 100}-{ym % 100:02d}', 0.0) if ym else 0.0
    tot = sum(units.values())
    if tot:
        print(f'\n  {own:,.0f} of {tot:,.0f} units ({own / tot * 100:.0f}%) left '
              'in the month they were ordered.')
        print('  The rest is the carry-over the cohort test had to infer. This '
              'is it measured.')

    if args.sample:
        print(f'\nmatched, first {args.sample}:')
        print(f'  {"store order":<22} {"product":<18} {"SAP doc":<12} '
              f'{"goods issue":<12} status')
        for row in [r for r in rows_out if r[3]][:args.sample]:
            print(f'  {row[0][:22]:<22} {row[1][:18]:<18} {row[3]:<12} '
                  f'{row[4]:<12} {row[6]}')
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
                    'goods issue date', 'goods issue month', 'sap status'])
        w.writerows(rows_out)
    print(f'\n-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""How long an order takes to leave, measured rather than argued.

    py tools\\despatch.py                  # every orders_* export in the folder
    py tools\\despatch.py --file orders_2605

The cohort test had to infer which month a unit belonged to, because no export
said. SAP's sales-order export says: `Created On` is when the order arrived and
`Goods Issue Date` is when it left. The difference is the whole question, and it
needs no store export and no join to answer.

Two readings come out of that:

  **where a month's orders land** - what it despatches itself and what it hands
  on. This is the carry-over the cohort test argued about, counted.

  **how long the wait is** - the share despatched within N days. An older export
  can show the whole tail; a recent one cannot, because the despatches that have
  not happened yet are missing rather than late. The run says which months are
  old enough to be read that way.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import (find, norm_stem, parse_number,             # noqa: E402
                     pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

C_MADE = ('Created On', 'Creation Date', 'Entered On')
C_GI = ('Goods Issue Date', 'Actual GI Date', 'Despatch Date')
C_DEL = ('Delivery Date', 'Requested Delivery Date')
C_QTY = ('Confirmed Quantity (Item)', 'Order Quantity (Item)', 'Quantity')
C_AMT = ('Net Value (Item)', 'Net Value')
C_WHO = ('Sold-To Party Name', 'Sold-to Party Name', 'Customer Name')
C_REF = ('Customer Reference (Header)', 'Customer Reference')
C_REJECT = ('Reason for Rejection', 'Rejection Reason')
C_DSTAT = ('Overall Delivery Status Item Description',
           'Overall Delivery Status (All Items)')

# SAP fills Goods Issue Date on every schedule line, delivered or not. On a line
# that has gone it is the day it went; on one that has not it is the day it is
# meant to go. They are not the same kind of fact and the run never adds them
# together: a date later than the day the export was taken is a plan, whatever
# the status column says.
DELIVERED = ('COMPLETED', 'DELIVERED', 'FULLY DELIVERED')

# Days from arriving to leaving. The first bands are tight because most of the
# business lives there and a day matters; the last is open because what sits in
# it is not late, it is stuck.
BANDS = ((0, 0, 'same day'), (1, 1, '1 day'), (2, 3, '2-3 days'),
         (4, 7, '4-7 days'), (8, 14, '8-14 days'), (15, 30, '15-30 days'),
         (31, 60, '31-60 days'), (61, 10_000, '61+ days'))


def to_date(v):
    for f in ('%d/%m/%Y', '%Y-%m-%d', '%d-%b-%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(str(v or '').strip(), f).date()
        except ValueError:
            pass
    return None


def band(days):
    for lo, hi, label in BANDS:
        if lo <= days <= hi:
            return label
    return BANDS[-1][2]


def read_one(path, say=print):
    rows, info = read_any(path)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    i = {k: find(head, *v) for k, v in
         {'made': C_MADE, 'gi': C_GI, 'del': C_DEL, 'qty': C_QTY, 'amt': C_AMT,
          'who': C_WHO, 'ref': C_REF, 'reject': C_REJECT,
          'dstat': C_DSTAT}.items()}
    say(f'  {path.name}: {info["format"]}, {len(body):,} rows')
    if i['made'] is None or i['gi'] is None:
        say('    no creation date or no goods issue date, so it cannot say how '
            'long anything took')
        return None

    def cell(r, n):
        return (r[n].strip() if n is not None and n < len(r) else '')

    out = []
    for r in body:
        made, gi = to_date(cell(r, i['made'])), to_date(cell(r, i['gi']))
        qty = parse_number(cell(r, i['qty'])) or 0.0
        out.append({'made': made, 'gi': gi, 'qty': qty,
                    'amt': parse_number(cell(r, i['amt'])) or 0.0,
                    'who': cell(r, i['who']), 'ref': cell(r, i['ref']),
                    'rejected': bool(cell(r, i['reject'])),
                    'delivered': cell(r, i['dstat']).upper() in DELIVERED})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--file', default=None, metavar='NAME',
                    help='one export instead of every orders_* in the folder')
    ap.add_argument('--prefix', default='orders', metavar='STEM',
                    help='how the SAP exports are named (default: orders)')
    ap.add_argument('--as-of', metavar='YYYY-MM-DD',
                    help='treat this as today when deciding which months have '
                         'had long enough to finish (default: the latest '
                         'despatch in any export)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'despatch.csv'))
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    if args.file:
        want = [p for p in folder.iterdir()
                if p.is_file() and norm_stem(p.stem) == norm_stem(args.file)]
    else:
        # One export per month. The same one often sits in the folder twice, as
        # a csv and as a workbook, and a spreadsheet round-trip renames headers
        # - so the csv wins and the duplicate is named rather than read.
        want, seen = [], {}
        for cand in pick_series(folder, args.prefix):   # best format first
            key = norm_stem(cand.stem)
            if key in seen:
                print(f'  {cand.name}: the same export as {seen[key].name}, '
                      'skipped')
                continue
            seen[key] = cand
            want.append(cand)
        want.reverse()                                  # oldest month first
    if not want:
        print(f'no export named like {args.file or args.prefix + "_*"!r} in '
              f'{folder.resolve()}', file=sys.stderr)
        return 2

    print('reading:')
    months = {}
    for p in want:
        lines = read_one(p)
        if lines:
            months[p.name] = lines
    if not months:
        print('\nnothing could be read.', file=sys.stderr)
        return 1

    # The day the export was taken, which is the line between what happened and
    # what is merely scheduled. The last order it recorded is the best proxy.
    latest_made = max((l['made'] for lines in months.values() for l in lines
                       if l['made']), default=None)
    asof = to_date(args.as_of) or latest_made
    latest_gi = max((l['gi'] for lines in months.values() for l in lines
                     if l['gi']), default=None)
    print(f'\ntaken on or about {asof} - the last order it recorded.')
    if latest_gi and asof and latest_gi > asof:
        print(f'  Goods issue dates run to {latest_gi}, past that. SAP fills the '
              'field on every\n  schedule line, so anything after '
              f'{asof} is when a line is *meant* to go,\n  not when it went. '
              'The two are counted apart below and never added up.')

    def gone(l):
        """Did this line actually leave, as far as the export can know?"""
        return bool(l['gi']) and l['delivered'] and (not asof or l['gi'] <= asof)

    # ── where each month's orders land ─────────────────────────────────────
    rows_out = []
    for name, lines in months.items():
        made = [l['made'] for l in lines if l['made']]
        if not made:
            continue
        ym = collections.Counter(d.year * 100 + d.month for d in made).most_common(1)[0][0]
        own = f'{ym // 100}-{ym % 100:02d}'
        went = collections.Counter()
        due = collections.Counter()
        stuck = 0.0
        for l in lines:
            if l['rejected'] and not gone(l):
                stuck += 0.0            # rejected lines are no month's revenue
                continue
            if gone(l):
                went[l['gi'].strftime('%Y-%m')] += l['qty']
            elif l['gi']:
                due[l['gi'].strftime('%Y-%m')] += l['qty']
            else:
                stuck += l['qty']
        total = sum(went.values()) + sum(due.values()) + stuck
        print(f'\n{name} - orders created in {own}, {total:,.0f} unit(s)')
        print(f'  {"":<22} {"left":>10} {"due to leave":>13}')
        for k in sorted(set(went) | set(due)):
            flag = '   <- its own month' if k == own else ''
            print(f'  {k:<22} {went.get(k, 0):>10,.0f} {due.get(k, 0):>13,.0f}'
                  + flag)
        if stuck:
            print(f'  {"no date at all":<22} {"":>10} {stuck:>13,.0f}')
        kept = went.get(own, 0.0)
        later_gone = sum(v for k, v in went.items() if k > own)
        later_due = sum(v for k, v in due.items() if k > own)
        print(f'  {kept / total * 100:.0f}% of the month\'s orders had left by '
              f'{asof}, in the month they were ordered.')
        if later_gone:
            print(f'  {later_gone / total * 100:.0f}% had already left in a '
                  'later month.')
        if later_due + stuck:
            print(f'  {(later_due + stuck) / total * 100:.0f}% had not left yet '
                  '- scheduled, not measured. Next month\'s export\n  is what '
                  'turns that into a number.')
        rows_out.append([name, own, round(total), round(kept), round(later_gone),
                         round(later_due), round(stuck)])

    # ── how long the wait is ───────────────────────────────────────────────
    # A month is only worth reading a tail off once it has had the time. One
    # exported in its own month cannot show a 60-day wait: those despatches
    # have not happened, which is not the same as being late.
    print('\nhow long an order waited, by the month it arrived in')
    print('  (a month needs about two months of runway before its tail is real)')
    mature = []
    for name, lines in months.items():
        made = [l['made'] for l in lines if l['made']]
        if not made:
            continue
        ym = max(made)
        runway = (asof - ym).days if asof else 0
        tag = 'mature' if runway >= 60 else f'only {runway} day(s) of runway'
        mature.append((name, runway))
        pairs = [(l, (l['gi'] - l['made']).days)
                 for l in lines if gone(l) and l['made']]
        if not pairs:
            continue
        tot = sum(l['qty'] for l, _ in pairs)
        waiting = sum(l['qty'] for l in lines
                      if not gone(l) and not l['rejected'])
        by = collections.Counter()
        for l, n in pairs:
            by[band(n)] += l['qty']
        print(f'\n  {name}  ({tag})')
        run = 0.0
        for _, _, label in BANDS:
            if not by.get(label):
                continue
            run += by[label]
            print(f'    {label:<12} {by[label]:>9,.0f} units   '
                  f'{run / (tot + waiting) * 100:>5.1f}% cumulative')
        if waiting:
            print(f'    {"not gone yet":<12} {waiting:>9,.0f} units   '
                  f'{waiting / (tot + waiting) * 100:>5.1f}%')

    if any(r < 60 for _, r in mature):
        print('\n  A month exported days after it ended cannot show its own '
              'tail: the despatches\n  that have not happened are missing from '
              'it, not late in it. Those cumulative\n  shares are of what has '
              'gone so far, and they will only fall as the rest goes.\n  An '
              'export of the same month taken two months later is what settles '
              'it.')

    # ── the carry-over ladder ──────────────────────────────────────────────
    # One row per month an order arrived in, one column per month it left in.
    # Everything on the diagonal is a month earning its own demand; everything
    # to the right of it is that month handing revenue forward, and everything
    # below the diagonal in a column is a month being handed it.
    grid: dict[tuple, float] = collections.Counter()
    store_only = []
    for name, lines in months.items():
        for l in lines:
            if l['rejected'] and not gone(l):
                continue
            if not l['made']:
                continue
            m = l['made'].strftime('%Y-%m')
            g = l['gi'].strftime('%Y-%m') if l['gi'] else None
            grid[(m, g or 'no date', gone(l))] += l['qty']
    made_months = sorted({k[0] for k in grid})
    gi_months = sorted({k[1] for k in grid if k[1] != 'no date'})
    if made_months and gi_months:
        print('\nthe carry-over ladder - ordered down the side, despatched '
              'across the top')
        print('  (a date past the day an export was taken is a schedule, '
              'shown in brackets)')
        head = ''.join(f'{g[-5:]:>18}' for g in gi_months)
        print(f'  {"ordered in":<12}{head}{"open":>12}')
        for m in made_months:
            cells = []
            for g in gi_months:
                left = grid.get((m, g, True), 0.0)
                due = grid.get((m, g, False), 0.0)
                cells.append(f'{left:,.0f}' + (f' ({due:,.0f})' if due else '')
                             if left or due else '-')
            open_u = grid.get((m, 'no date', False), 0.0) \
                + grid.get((m, 'no date', True), 0.0)
            print(f'  {m:<12}' + ''.join(f'{c:>18}' for c in cells)
                  + f'{open_u:>12,.0f}')

        print(f'\n  {"month":<10} {"own demand":>12} {"carried in":>12} '
              f'{"carried out":>13} {"net":>10}')
        for m in made_months:
            own = sum(v for k, v in grid.items() if k[0] == m and k[1] == m)
            out_u = sum(v for k, v in grid.items()
                        if k[0] == m and k[1] != 'no date' and k[1] > m)
            in_u = sum(v for k, v in grid.items()
                       if k[1] == m and k[0] < m)
            net = in_u - out_u
            print(f'  {m:<10} {own:>12,.0f} {in_u:>12,.0f} {out_u:>13,.0f} '
                  f'{net:>+10,.0f}')
        print('  own demand is what a month both ordered and despatched; '
              'carried in is what an\n  earlier month despatched into it, and '
              'carried out what it despatches later.\n  A month that takes in '
              'more than it hands on has revenue flattered by the net.')
        print('  A month whose predecessor is not in the folder reads as '
              'nothing carried in -\n  that is the export missing, not the '
              'carry-over being nil.')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['export', 'orders created in', 'units', 'left same month',
                    'left in a later month', 'due to leave later',
                    'no date at all'])
        w.writerows(rows_out)
    print(f'\n-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

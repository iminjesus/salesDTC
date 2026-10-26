#!/usr/bin/env python3
"""What a month's revenue was ordered in - line by line, off SAP's own dates.

    py tools\\order_lag.py --month 2607
    py tools\\order_lag.py --month 2607 --campaign "S26 Launch" --out docs\\lag.csv

The profit page bands a line by the day it was **ordered** and sits it in the
month it **left**, so a campaign that closed in April keeps a row in the months
after it. That is the rule; whether a four-month tail is really in the data is
a different question, and this is the one that answers it.

Every SAP sales-order line that left in the chosen month is read and grouped by
the month it was ordered in. What comes out says, in units and in money, how
much of the month was ordered inside it, how much was carried in from each
earlier month, and - where a plan is there - which campaign the carried-in
lines came in on.

The same filters the page uses, so the figures are the page's: only lines
carrying a store-stamped reference, nothing rejected.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo_match as PM                                       # noqa: E402
import sap as SAP                                              # noqa: E402
from rawdata import (find, parse_number, pick_series, read_any)  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def plan_bander(folder: Path, stems, say=print):
    """(sku, day) -> the campaign names live for it that day, or None.

    The same walk the page's promotion split makes - PM.plan_state over the
    plan lines whose window covers the day - so a line banded here and the
    same line banded on the page cannot disagree.
    """
    try:
        plan, meta = PM.load_plans(Path(folder), list(stems), say=say)
    except Exception as e:
        say(f'  no plan read ({e}), so the lines come back without a campaign')
        return None
    if not meta or not plan.rows:
        return None
    canon = PM.canon_campaigns(plan.rows, say=lambda *a: None)

    cache: dict = {}

    def band(sku, day):
        if day is None:
            return ('', '', '')
        k = (PM.code_norm(sku), day)
        hit = cache.get(k)
        if hit is None:
            live, nat, dtc = PM.plan_state(plan, k[0], day)
            hit = cache[k] = (
                'both' if (dtc and nat) else 'dtc' if dtc else 'nat' if nat
                else 'none' if live else 'gap',
                PM.campaign_names(live, canon, 1),
                PM.campaign_names(live, canon, 2))
        return hit

    return band


def months_between(a: int, b: int) -> int:
    """How many months from a to b, both as YYYYMM."""
    return (b // 100 - a // 100) * 12 + (b % 100 - a % 100)


def read_lines(folder: Path, stem: str, month: int, bander, say=print) -> list:
    out = []
    files = pick_series(folder, stem)
    if not files:
        say(f'no SAP export named like {stem!r} in {folder}')
        return out
    for path in files:
        try:
            rows, info = read_any(path)
        except (ValueError, OSError) as e:
            say(f'  {path.name}: {e} - skipped')
            continue
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        col = {k: find(head, *v) for k, v in
               (('ref', SAP.S_REF), ('payer', SAP.S_PAYER), ('sku', SAP.S_SKU),
                ('qty', SAP.S_QTY), ('gi', SAP.S_GI), ('made', SAP.S_MADE),
                ('dstat', SAP.S_DSTAT), ('reject', SAP.S_REJECT))}
        amt_i, _ = SAP.pick_amount(head, SAP.S_AMT, None)
        missing = [k for k in ('ref', 'sku', 'qty', 'gi', 'made') if col[k] is None]
        if missing:
            say(f'  {path.name}: no {", ".join(missing)} - skipped')
            continue
        say(f'  {path.name}: {info["format"]}, {len(rows) - 1:,} rows')
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
        for r in rows[1:]:
            if not SAP.STAMPED.match(cell(r, col['ref']).upper()):
                continue
            if cell(r, col['reject']):
                continue
            gi = SAP.to_date(cell(r, col['gi']))
            made = SAP.to_date(cell(r, col['made']))
            if SAP.month_of_date(gi) != month:
                continue
            band = bander(cell(r, col['sku']), made) if bander else None
            out.append({
                'ref': cell(r, col['ref']), 'sku': cell(r, col['sku']),
                'payer': cell(r, col['payer']),
                'made': made, 'gi': gi,
                'made_m': SAP.month_of_date(made),
                'qty': parse_number(cell(r, col['qty'])) or 0.0,
                'amt': (parse_number(cell(r, amt_i)) or 0.0)
                       if amt_i is not None else 0.0,
                'status': cell(r, col['dstat']),
                'band': (band or ('', '', ''))[0],
                'camp1': (band or ('', '', ''))[1],
                'camp2': (band or ('', '', ''))[2],
                'lag': (months_between(SAP.month_of_date(made), month)
                        if made else None),
            })
    return out


def by_order_month(lines: list, month: int, say=print) -> None:
    g: dict = collections.defaultdict(lambda: [0.0, 0.0, 0])
    for x in lines:
        v = g[x['made_m']]
        v[0] += x['qty']; v[1] += x['amt']; v[2] += 1
    units = sum(v[0] for v in g.values()) or 1
    say(f'\nwhat left in {month}, by the month it was ordered')
    say(f'  {"ordered":<10}{"lag":>5}{"lines":>8}{"units":>12}{"share":>9}'
        f'{"amount":>16}')
    for m in sorted(g, key=lambda m: (m is None, m)):
        v = g[m]
        lag = '' if m is None else f'{months_between(m, month):>5}'
        say(f'  {str(m or "(no date)"):<10}{lag}{v[2]:>8,}{v[0]:>12,.0f}'
            f'{v[0] / units * 100:>8.1f}%{v[1]:>16,.0f}')


def tail(lines: list, month: int, least: int, say=print) -> list:
    out = [x for x in lines if x['lag'] is not None and x['lag'] >= least]
    if not out:
        say(f'\nnothing left in {month} that was ordered {least}+ month(s) '
            f'earlier - the tail the page draws is not late despatch')
        return out
    units = sum(x['qty'] for x in out)
    amt = sum(x['amt'] for x in out)
    say(f'\nordered {least}+ month(s) before it left: {len(out):,} line(s), '
        f'{units:,.0f} unit(s), {amt:,.0f}')
    g = collections.Counter()
    for x in out:
        g[(x['camp1'] or '(no campaign)', x['band'] or '')] += x['qty']
    say('  by campaign:')
    for (c1, band), u in g.most_common(10):
        say(f'    {c1[:34]:<36}{band:<8}{u:>10,.0f} unit(s)')
    say('  the longest-waiting lines:')
    say(f'    {"order":<22}{"sku":<18}{"ordered":<12}{"left":<12}'
        f'{"units":>8}  campaign')
    for x in sorted(out, key=lambda x: (-x['lag'], -x['qty']))[:12]:
        say(f'    {x["ref"][:22]:<22}{x["sku"][:18]:<18}'
            f'{str(x["made"]):<12}{str(x["gi"]):<12}{x["qty"]:>8,.0f}  '
            f'{(x["camp1"] or "-")[:30]}')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, required=True, metavar='YYMM',
                    help='the month to take apart, as 2607 or 202607')
    ap.add_argument('--sap', default='orders', metavar='STEM',
                    help="how the SAP exports are named (default: orders)")
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM')
    ap.add_argument('--least', type=int, default=2, metavar='N',
                    help='how many months a line has to have waited to count '
                         'as a tail (default 2 - a month of lag is ordinary)')
    ap.add_argument('--campaign', metavar='NAME',
                    help='only the lines whose campaign contains this')
    ap.add_argument('--out', metavar='FILE', help='write the lines read')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    # 2607 and 202607 are the same month; the flags take the short one.
    month = (args.month if args.month > 9999
             else (2000 + args.month // 100) * 100 + args.month % 100)
    print(f'reading {folder} for what left in {month}')
    bander = plan_bander(folder, args.plan)

    lines = read_lines(folder, args.sap, month, bander)
    if not lines:
        print('no line left in that month - check --sap and --month')
        return 1
    if args.campaign:
        want = args.campaign.lower()
        lines = [x for x in lines
                 if want in (x['camp1'] or '').lower()
                 or want in (x['camp2'] or '').lower()]
        print(f'  {len(lines):,} line(s) whose campaign contains '
              f'{args.campaign!r}')
    by_order_month(lines, month)
    late = tail(lines, month, args.least)
    if args.out:
        with open(args.out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['order', 'sku', 'payer', 'ordered', 'left', 'lag months',
                        'units', 'amount', 'delivery status', 'band',
                        'campaign 1', 'campaign 2'])
            for x in sorted(lines, key=lambda x: (-(x['lag'] or 0), x['ref'])):
                w.writerow([x['ref'], x['sku'], x['payer'], x['made'], x['gi'],
                            x['lag'], x['qty'], x['amt'], x['status'],
                            x['band'], x['camp1'], x['camp2']])
        print(f'\n-> {args.out}  ({len(lines):,} line(s), '
              f'{len(late):,} of them a tail)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

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
import calendar
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import sap as SAP                                              # noqa: E402
from rawdata import (find, key_norm, master, month_before,    # noqa: E402
                     month_of, parse_number, pick_series, read_any)

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


def measure(folder: Path, ym: int, cust: dict, prod: dict, at: int,
            skip_sku=(), online: bool = False, sap: str = 'orders',
            blank: dict | None = None, late: dict | None = None,
            say=print) -> tuple:
    """({division: Pot}, Pot, asof) for the orders placed in `ym`.

    Every export from the month onward is read: a September order that left in
    October is on October's file, and leaving it out is what makes a lead time
    look shorter than it is.
    """
    files = sorted(pick_series(folder, sap), key=lambda q: q.name)
    seen: set = set()
    files = [f for f in files
             if not (f.stem.lower() in seen or seen.add(f.stem.lower()))]
    files = [f for f in files
             if (month_of([], [], f.stem, say=lambda *a: None) or 0) >= ym]
    if not files:
        say(f'no {sap}_* export for {ym} or later in the folder')
        return {}, Pot(), None
    say(f'  orders: {", ".join(f.name for f in files)}')
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
                ('reject', SAP.S_REJECT), ('amt', SAP.S_AMT))}
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
            if online:
                c = cust.get(key_norm(cell(r, col['payer']))) or {}
                if CUST.channel_of(c.get('account'), bool(c)) != CUST.ONLINE:
                    continue
            p = prod.get(key_norm(sku)) or {}
            if not p and at < len(PRODUCT) - 1:
                skipped += 1
            # What the page cannot place. Two different cases, and the
            # difference decides what to do about them: a code the master has
            # never heard of is dropped from the page entirely, while a code
            # it has but left a level empty on is drawn under a placeholder.
            if blank is not None:
                missing = [n for n, slot, _ in PRODUCT[:4]
                           if not (p.get(slot) or '').strip()]
                if missing:
                    b = blank.setdefault(sku.upper(), {
                        'units': 0.0, 'amt': 0.0, 'known': not not p,
                        'missing': missing,
                        'has': {n: (p.get(slot) or '').strip()
                                for n, slot, _ in PRODUCT[:4]
                                if (p.get(slot) or '').strip()}})
                    b['units'] += parse_number(cell(r, col['qty'])) or 0.0
                    b['amt'] += parse_number(cell(r, col['amt'])) or 0.0
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
    # The lines that will not be this month's revenue: a despatch date in a
    # later month, or none at all. Collected here rather than in the loop
    # above because the duplicates have to collapse first - a line open on one
    # export and shipped on the next is not two lines.
    if late is not None:
        end = date(ym // 100, ym % 100,
                   calendar.monthrange(ym // 100, ym % 100)[1])
        for gi, made, qty, name in rec.values():
            if gi is not None and gi <= end:
                continue
            d = late.setdefault(made.isoformat(),
                                {'made': made, 'first': None, 'last': None,
                                 'divs': {}})
            v = d['divs'].setdefault(name, {'sched': 0.0, 'open': 0.0})
            if gi is None:
                v['open'] += qty
            else:
                v['sched'] += qty
                d['first'] = gi if d['first'] is None else min(d['first'], gi)
                d['last'] = gi if d['last'] is None else max(d['last'], gi)

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
    say(f'  {len(rec):,} line(s) ordered in {ym}'
        + (f'; {dupes:,} seen on more than one export' if dupes else '')
        + (f'; {skipped:,} had no product master row' if skipped else ''))
    return pots, whole, asof


def average_days(folder: Path, ym: int, cust: dict, prod: dict,
                 by: str = 'div1', online: bool = False, sap: str = 'orders',
                 say=print) -> dict:
    """{division: average days from order to despatch} for the month's orders.

    What it is for is predicting whether an order placed near a month end will
    leave inside it, so a division with nothing measured gets no entry and the
    caller falls back to the figure over everything.
    """
    at = AT.get(by.lower().replace(' ', ''), 1)
    pots, whole, _ = measure(folder, ym, cust, prod, at, online=online,
                             sap=sap, say=say)
    out = {k: p.mean for k, p in pots.items() if p.mean is not None}
    if whole.mean is not None:
        out['\0all'] = whole.mean
    return out


def sweep_blank(folder: Path, prod: dict, sap: str = 'orders',
                skip_sku=(), say=print) -> dict:
    """Every code in every order export that the product master cannot place.

    One month answers "what did this month lose"; the master is a standing
    thing and the question it raises is "what has it never known", so this
    reads the lot. A line on two exports is one line, by its own reference.
    """
    files = sorted(pick_series(folder, sap), key=lambda q: q.name)
    seen: set = set()
    files = [f for f in files
             if not (f.stem.lower() in seen or seen.add(f.stem.lower()))]
    if not files:
        say(f'no {sap}_* export in the folder')
        return {}
    say(f'  reading {len(files)} export(s): '
        + ', '.join(f.name for f in files))
    rec: dict = {}
    lines = 0
    for f in files:
        rows, _ = read_any(f)
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        col = {k: find(head, *names) for k, names in
               (('ref', SAP.S_REF), ('sku', SAP.S_SKU), ('qty', SAP.S_QTY),
                ('made', SAP.S_MADE), ('reject', SAP.S_REJECT),
                ('amt', SAP.S_AMT))}
        if col['ref'] is None or col['sku'] is None or col['made'] is None:
            say(f'  {f.name}: not an order export - skipped')
            continue
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r)
                             else '')
        for r in rows[1:]:
            if not SAP.STAMPED.match(cell(r, col['ref']).upper()):
                continue
            if cell(r, col['reject']):
                continue
            made = SAP.to_date(cell(r, col['made']))
            sku = cell(r, col['sku'])
            if made is None or not sku:
                continue
            if skip_sku and sku.upper().startswith(skip_sku):
                continue
            qty = parse_number(cell(r, col['qty'])) or 0.0
            amt = parse_number(cell(r, col['amt'])) or 0.0
            rec[(cell(r, col['ref']).upper(), sku.upper(), qty, made)] = (
                sku, qty, amt, made)
            lines += 1
    out: dict = {}
    for sku, qty, amt, made in rec.values():
        p = prod.get(key_norm(sku)) or {}
        missing = [n for n, slot, _ in PRODUCT[:4]
                   if not (p.get(slot) or '').strip()]
        if not missing:
            continue
        b = out.setdefault(sku.upper(), {
            'units': 0.0, 'amt': 0.0, 'known': not not p, 'missing': missing,
            'months': set(), 'first': made, 'last': made,
            'has': {n: (p.get(slot) or '').strip()
                    for n, slot, _ in PRODUCT[:4] if (p.get(slot) or '').strip()}})
        b['units'] += qty
        b['amt'] += amt
        b['months'].add(made.year * 100 + made.month)
        b['first'] = min(b['first'], made)
        b['last'] = max(b['last'], made)
    say(f'  {lines:,} line(s) read, {len(rec):,} after collapsing the ones on '
        f'more than one export')
    return out


def say_late(late: dict, ym: int, lead: dict, end, say=print) -> int:
    """Ordered in the month, not gone yet - and whether the page counts it.

    The chart draws some of this as a hatched band and the question it raises
    is always the same one: an order placed on the first of the month, still
    not gone? Three different things are in here and only two are the band:

        scheduled   SAP carries a despatch date in a later month. Not "still
                    not gone" - gone on a date already set, and next month's
                    revenue. The page hatches it.
        late        no despatch date, and its division's measured lead time
                    does not fit in what is left of the month. Hatched too,
                    and a prediction rather than a fact.
        in time     no despatch date, but the lead time says it still fits.
                    Counted on the page, and the part that would hurt if the
                    lead time is optimistic.
    """
    if not late:
        say(f'\neverything ordered in {ym} has left or is scheduled inside it')
        return 0
    rest = lead.get('\0all')
    say(f'\n{ym}: ordered in the month and not gone yet, by the day ordered')
    say(f'  {"ordered":<12}{"scheduled":>11}{"late":>9}{"in time":>9}'
        f'{"leaves":>26}   the divisions')
    tot = {'sched': 0.0, 'late': 0.0, 'fits': 0.0}
    for day in sorted(late):
        d = late[day]
        row = {'sched': 0.0, 'late': 0.0, 'fits': 0.0}
        shown = {}
        for name, v in d['divs'].items():
            row['sched'] += v['sched']
            days = lead.get(name, rest)
            over = (days is not None and end is not None
                    and d['made'] + timedelta(days=round(days)) > end)
            row['late' if over else 'fits'] += v['open']
            shown[name] = v['sched'] + v['open']
        for k in tot:
            tot[k] += row[k]
        when = ('-' if d['first'] is None
                else d['first'].isoformat() if d['first'] == d['last']
                else f'{d["first"].isoformat()} .. {d["last"].isoformat()}')
        divs = ', '.join(f'{k} {n:,.0f}' for k, n in
                         sorted(shown.items(), key=lambda kv: -kv[1])[:3])
        say(f'  {day:<12}{row["sched"]:>11,.0f}{row["late"]:>9,.0f}'
            f'{row["fits"]:>9,.0f}{when:>26}   {divs}')
    say(f'  {"-" * 67}')
    say(f'  {f"{len(late)} day(s)":<12}{tot["sched"]:>11,.0f}'
        f'{tot["late"]:>9,.0f}{tot["fits"]:>9,.0f}')
    say(f'\n  scheduled + late is the hatched band: {tot["sched"] + tot["late"]:,.0f} '
        'unit(s), out of the\n  month\'s figures and out of its achievement.')
    say(f'  in time is {tot["fits"]:,.0f} unit(s) the page is counting on the '
        'lead time for.')
    if not lead:
        say('  (no previous month to measure a lead time from, so nothing is '
            'called late)')
    return 0


def say_blank(blank: dict, ym, out=None, say=print) -> int:
    """The codes the product master cannot place, and what they are worth.

    Split by what is actually wrong with them, because the two have different
    consequences: a code with no master row at all has every level empty, so
    the page drops it with --drop Biz=(blank) and its money is on no chart and
    in no achievement. A code the master knows but left a level empty on keeps
    its Biz, so it stays on the page and lands under a placeholder further
    down - visible, but not where anyone is looking for it.
    """
    what = f'{ym}' if ym else 'every order export'
    if not blank:
        say(f'\nevery line of {what} places on the product master')
        return 0
    gone = {k: v for k, v in blank.items() if not v['known']}
    part = {k: v for k, v in blank.items() if v['known']}
    top = 60
    for title, rows, tag in (
            ('no row in the product master - the page drops these', gone,
             'dropped'),
            ('a row, but a level left empty - drawn under a placeholder',
             part, 'placed under a placeholder')):
        if not rows:
            continue
        tot_u = sum(v['units'] for v in rows.values())
        tot_a = sum(v['amt'] for v in rows.values())
        say(f'\n{what}: {title}')
        wide = 'months' in next(iter(rows.values()))
        say(f'  {"code":<20}{"units":>10}{"value":>15}'
            + (f'{"months":>8}{"first":>13}{"last":>13}' if wide else '')
            + '   what the master does have')
        for k, v in sorted(rows.items(), key=lambda kv: -kv[1]['amt'])[:top]:
            has = ', '.join(f'{n}={x}' for n, x in v['has'].items()) or '-'
            say(f'  {k[:20]:<20}{v["units"]:>10,.0f}{v["amt"]:>15,.0f}'
                + (f'{len(v["months"]):>8}{v["first"].isoformat():>13}'
                   f'{v["last"].isoformat():>13}' if wide else '')
                + f'   {has}')
        if len(rows) > top:
            say(f'  ... and {len(rows) - top:,} more'
                + (f' - --out has them all' if out else ''))
        say('  ' + '-' * (45 + (34 if wide else 0)))
        say(f'  {f"{len(rows):,} code(s)":<20}{tot_u:>10,.0f}{tot_a:>15,.0f}'
            f'   {tag}')
    if out:
        with open(out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['code', 'in the master', 'levels missing', 'units',
                        'value', 'months', 'first order', 'last order',
                        'what the master has'])
            for k, v in sorted(blank.items(), key=lambda kv: -kv[1]['amt']):
                w.writerow([k, 'yes' if v['known'] else 'no',
                            ' '.join(v['missing']), round(v['units']),
                            round(v['amt']),
                            len(v.get('months', ())) or '',
                            v['first'].isoformat() if v.get('first') else '',
                            v['last'].isoformat() if v.get('last') else '',
                            '; '.join(f'{n}={x}' for n, x in v['has'].items())])
        say(f'\n-> {out}  ({len(blank):,} code(s))')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM',
                    help='the month whose orders are measured, as 2609. With '
                         '--blank it may be left off, and then every order '
                         'export in the folder is swept')
    ap.add_argument('--sap', default='orders', metavar='STEM')
    ap.add_argument('--by', default='div1', metavar='LEVEL',
                    help='biz, div1, div2, div3, range or sku (default div1)')
    ap.add_argument('--online', action='store_true',
                    help='the online business only, as the target is')
    ap.add_argument('--out', metavar='FILE',
                    help='write the --blank listing as a csv, every code')
    ap.add_argument('--late', action='store_true',
                    help='instead of the lead time, list what was ordered in '
                         'the month and does not leave inside it - the '
                         "chart's hatched band, by the day it was ordered")
    ap.add_argument('--blank', action='store_true',
                    help='instead of the lead time, list the codes the '
                         'product master cannot place - what the page drops '
                         'or draws under a placeholder, and what it is worth')
    ap.add_argument('--skip-sku', default='', metavar='PREFIX',
                    help='leave out codes starting with this, comma-separated')
    args = ap.parse_args()
    skip_sku = tuple(t.strip().upper()
                     for t in args.skip_sku.split(',') if t.strip())

    at = AT.get(args.by.lower().replace(' ', ''))
    if at is None:
        raise SystemExit('--by ' + args.by + ' is not one of '
                         + ', '.join(sorted(AT)))
    if args.month is None and not args.blank:
        raise SystemExit('--month is needed, as 2609')
    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    # 2609 and 202609 are both in use. 202000 + 2609 is the year 2046, which
    # is the shape of bug that reads as "no export in the folder".
    m = args.month
    ym = None if m is None else (m if m > 9999
                                 else (2000 + m // 100) * 100 + m % 100)

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

    if args.blank and ym is None:
        # The master is a standing thing, so the question is what it has never
        # known - every export, not one month of them.
        return say_blank(sweep_blank(folder, prod, args.sap, skip_sku),
                         None, args.out)
    blank: dict = {} if args.blank else None
    late: dict = {} if args.late else None
    pots, whole, asof = measure(folder, ym, cust, prod, at,
                                skip_sku=skip_sku, online=args.online,
                                sap=args.sap, blank=blank, late=late)
    if args.late:
        lead = average_days(folder, month_before(ym), cust, prod,
                            online=args.online, sap=args.sap,
                            say=lambda *a: None)
        end = date(ym // 100, ym % 100,
                   calendar.monthrange(ym // 100, ym % 100)[1])
        return say_late(late, ym, lead, end)
    if args.blank:
        return say_blank(blank, ym, args.out)

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

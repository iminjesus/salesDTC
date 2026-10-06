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
import calendar
import collections
import csv
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import re                                                       # noqa: E402
from rawdata import (find, key_norm, master, month_name,        # noqa: E402
                     norm_stem, parse_number, pick_file, pick_series, read_any)
from link import order_key                                      # noqa: E402
from promo_match import MECHANIC                                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

C_MADE = ('Created On', 'Creation Date', 'Entered On')
C_GI = ('Goods Issue Date', 'Actual GI Date', 'Despatch Date')
C_DEL = ('Delivery Date', 'Requested Delivery Date')
C_QTY = ('Confirmed Quantity (Item)', 'Order Quantity (Item)', 'Quantity')
C_AMT = ('Net Value (Item)', 'Net Value')
C_WHO = ('Sold-To Party Name', 'Sold-to Party Name', 'Customer Name')
C_REF = ('Customer Reference (Header)', 'Customer Reference')
C_SKU = ('Material', 'Material Number', 'Product Code', 'SKU')
# The store's own export, which is the only place a promotion is written down.
D_ORDER = ('Order Code', 'Order No', 'Order Number', 'Order ID', 'order_code')
D_SKU = ('Product Code', 'SKU', 'Material', 'Model Code', 'Product Number')
D_RULE = ('promotion_rule', 'Promotion Rule', 'Promo Rule', 'Rule')
D_PROMO = ('Nationwide_Campaign', 'DTC_Campaign1', 'Promotion Name',
           'Promotion', 'Campaign')
D_PORTAL = ('Portal', 'Portal Name', 'Portal Group', 'Store Portal')
C_PROD = ('Material Description', 'Product Description', 'Material Text',
          'Product Name')
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


def cell(r, i):
    return (r[i].strip() if i is not None and i < len(r) else '')


def month_end(d):
    return calendar.monthrange(d.year, d.month)[1]


def wmedian(pairs):
    """The median of (value, weight) pairs, weighted by the units behind it.

    A line-level median would let one order of 1 unit count as much as one of
    400, and the whole report is in units.
    """
    s = sorted(pairs)
    total = sum(w for _, w in s)
    if total <= 0:
        return None
    run = 0.0
    for v, w in s:
        run += w
        if run >= total / 2:
            return v
    return s[-1][0]


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
          'who': C_WHO, 'ref': C_REF, 'reject': C_REJECT, 'sku': C_SKU,
          'prod': C_PROD, 'dstat': C_DSTAT}.items()}
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
                    'sku': cell(r, i['sku']) or '(no product code)',
                    'prod': cell(r, i['prod']),
                    'rejected': bool(cell(r, i['reject'])),
                    'delivered': cell(r, i['dstat']).upper() in DELIVERED})
    return out


# ── what the carry-over is made of ──────────────────────────────────────────
# The ladder says how much a month handed on. This says what it was made of,
# and the dimension comes from one of three places:
#
#   the SAP line itself    the product code, the customer
#   the product master     division, category, the product's name
#   the store export       the promotion, the portal - SAP carries no promotion,
#                          so these need the join on the stamped reference
#
# The run names where it got each one, and a dimension it could not source is
# reported rather than quietly coming out as one big blank bucket.
DIMS = {
    'sku':       ('product code', 'line'),
    'product':   ('product', 'master'),
    'division':  ('division', 'master'),
    'category':  ('category', 'master'),
    'customer':  ('customer', 'line'),
    'promotion': ('promotion', 'store'),
    'offer':     ('offer type', 'store'),
    'portal':    ('portal', 'store'),
}
UNKNOWN = '(not given)'
# Where a dimension lives on the line, when it is not called the same thing.
FIELD = {'customer': 'who'}


def store_month(folder: Path, ym: str, prefix: str):
    """The store's own export of a month, under either naming."""
    y, m = int(ym[:4]), int(ym[5:])
    digits = f'{str(y)[-2:]}{m:02d}'
    for cand in pick_series(folder, prefix):
        if digits in re.sub(r'\D', '', cand.stem):
            return cand
    return pick_file(folder, month_name(y * 100 + m))


def enrich(months, folder: Path, dims, args, say=print) -> set:
    """Hang a division and a promotion off the SAP lines that need one.

    Returns the dimensions that could actually be sourced. Everything here is a
    lookup onto lines that already exist - no line is added, dropped or
    reweighted, so the carry-over totals are the same whichever dimension is
    read.
    """
    got = {d for d in dims if DIMS[d][1] == 'line'}

    if any(DIMS[d][1] == 'master' for d in dims):
        want = {'product': ('Material Description', 'Product Description',
                            'Product Name', 'Model', 'Model Name'),
                'division': ('Product Division', 'Division', 'Div'),
                'category': ('Product Category', 'Category', 'Sub Category')}
        info, src = {}, None
        plans = [pick_file(folder, n) for n in ('MX_product', 'ce_product')]
        for cand in pick_series(folder, args.product) + [c for c in plans if c]:
            try:
                info = master(cand, ('SKU', 'Product Code', 'Material',
                                     'Product Number', 'Model Code'), want,
                             say=lambda *a: None)
            except (ValueError, OSError, IndexError) as e:
                say(f'  {cand.name}: {e} - trying the next one')
                continue
            if info:
                src = cand
                break
        if info:
            filled = {k: sum(1 for v in info.values() if v.get(k))
                      for k in want}
            say(f'  product master: {src.name}, {len(info):,} code(s) - '
                + ', '.join(f'{k} on {n:,}' for k, n in filled.items() if n))
            for lines in months.values():
                for l in lines:
                    row = info.get(key_norm(l['sku'])) or {}
                    for k in want:
                        l[k] = row.get(k) or ''
            got |= {d for d in dims if DIMS[d][1] == 'master'
                    and filled.get(d)}
        else:
            say('  no product master could be read, so division and category '
                'have no source')

    if any(DIMS[d][1] == 'store' for d in dims):
        # SAP has no promotion on it. The store export does, and the stamped
        # reference with its date taken off is what carries one to the other -
        # the same key tools/link.py is built on.
        total = hit = 0
        for name, lines in months.items():
            yms = sorted({l['made'].strftime('%Y-%m') for l in lines
                          if l['made']},
                         key=lambda y: -sum(1 for l in lines if l['made']
                                            and l['made'].strftime('%Y-%m') == y))
            sp = store_month(folder, yms[0], args.dtc) if yms else None
            if sp is None:
                say(f'  {name}: no store export for {yms[0] if yms else "?"}, '
                    'so its promotions are unknown')
                continue
            rows, _ = read_any(sp)
            head = [h.strip() for h in rows[0]]
            i = {k: find(head, *v) for k, v in
                 {'order': D_ORDER, 'rule': D_RULE, 'promo': D_PROMO,
                  'portal': D_PORTAL, 'sku': D_SKU}.items()}
            if i['order'] is None:
                say(f'  {sp.name}: no order number, so it cannot be joined')
                continue
            by_key = {}
            for r in rows[1:]:
                k = order_key(cell(r, i['order']))
                if not k:
                    continue
                raw = cell(r, i['rule']) or cell(r, i['promo'])
                by_key.setdefault(k, {
                    'promotion': raw or UNKNOWN,
                    'offer': offer_of(raw),
                    'portal': cell(r, i['portal']) or UNKNOWN})
            say(f'  {sp.name}: {len(by_key):,} order(s) with a promotion field '
                + (f'({head[i["rule"]]!r})' if i['rule'] is not None
                   else f'({head[i["promo"]]!r})' if i['promo'] is not None
                   else '- none found, so every line reads as not given'))
            for l in lines:
                total += 1
                row = by_key.get(order_key(l['ref']))
                if row:
                    hit += 1
                l.update(row or {k: UNKNOWN for k in
                                 ('promotion', 'offer', 'portal')})
        if total:
            say(f'  {hit:,} of {total:,} SAP line(s) ({hit / total * 100:.0f}%) '
                'found their order in the store export')
            got |= {d for d in dims if DIMS[d][1] == 'store'}
        if total and hit / total < 0.5:
            say('  under half joined, so a promotion split read off this is '
                'mostly the\n  unjoined bucket - treat it as a hint, not a '
                'measurement')
    return got


def offer_of(rule: str) -> str:
    """The mechanic a promotion rule names, where it names one."""
    if not rule:
        return UNKNOWN
    up = re.sub(r'[^A-Z]', ' ', rule.upper())
    for word in up.split():
        if word in MECHANIC:
            return MECHANIC[word]
    return 'Other'


def say_why(months, asof, gone, args, folder, say=print) -> None:
    """Why each month carried out what it did, and what the carry-out was.

    Two different things get called carry-over and they want different answers.
    An order that arrived on the 30th was never going to ship in the month - it
    carries out because the month ended, not because anything went wrong. An
    order that arrived on the 3rd and had not shipped by the 31st sat.

    The line between them is **the product's own** normal lead time, measured
    across every month off the lines that did go. A single month-wide median
    would be dominated by whatever sells fastest, and then a product that
    always takes six weeks would read as sitting every single month. A product
    with too little despatched to measure falls back to the overall median.

    Which makes three reasons, not two, and they want three different
    responses:

      never in month   the product's normal lead time is longer than the month
                       itself. It carries out whenever it is ordered - a
                       preorder, a made-to-order line, a container on the
                       water. Nothing about the month explains it and nothing
                       about the month will fix it.
      no time          the product could have shipped in the month, but this
                       order arrived with less than its lead time left. A
                       month-end promotion does this, and it is not a failure.
      sat              the order had its product's normal lead time available
                       and did not go. This is the only one that is a problem.
    """
    dims = [d for d in (x.strip().lower() for x in args.by.split(','))
            if d in DIMS] or ['sku']
    unknown = [x for x in (x.strip().lower() for x in args.by.split(','))
               if x and x not in DIMS]
    if unknown:
        say(f'\n--by {", ".join(unknown)}: no such dimension. There is '
            + ', '.join(DIMS))
    say('\nwhere the breakdown gets each dimension from:')
    got = enrich(months, folder, dims, args, say=say)

    # How long each product normally takes, measured over every month. This is
    # the yardstick the carry-out is judged against, so it is about the product
    # rather than the month - a month cannot be blamed for a preorder.
    by_sku = collections.defaultdict(list)
    overall = []
    for lines in months.values():
        for l in lines:
            if l['made'] and gone(l):
                pair = ((l['gi'] - l['made']).days, l['qty'])
                by_sku[key_norm(l['sku'])].append(pair)
                overall.append(pair)
    base_lead = wmedian(overall)
    norm_lead = {s: wmedian(v) for s, v in by_sku.items()
                 if sum(w for _, w in v) >= args.min_units}
    if base_lead is None:
        say('\nnothing in the folder has actually been despatched, so there is '
            'no lead time to\n  judge a carry-out against.')
        return
    say(f'\nnormal lead time: {base_lead:,.0f} day(s) across everything, '
        f'measured per product\n  on the {len(norm_lead):,} of {len(by_sku):,} '
        f'product(s) with at least {args.min_units} unit(s) despatched '
        '(--min-units)')

    def lead_of(l):
        return norm_lead.get(key_norm(l['sku']), base_lead)

    # One pass: every line onto its creating month, with what it did.
    per = {}
    for lines in months.values():
        for l in lines:
            if not l['made'] or (l['rejected'] and not gone(l)):
                continue
            m = l['made'].strftime('%Y-%m')
            w = per.setdefault(m, {'all': 0.0, 'out': 0.0, 'late': 0.0,
                                   'sat': 0.0, 'never': 0.0, 'last7': 0.0,
                                   'lead': [], 'held': [], 'by': {},
                                   'own': {}, 'why': {}})
            w['all'] += l['qty']
            if l['made'].day > month_end(l['made']) - 7:
                w['last7'] += l['qty']
            if gone(l):
                w['lead'].append(((l['gi'] - l['made']).days, l['qty']))
            g = l['gi'].strftime('%Y-%m') if l['gi'] else None
            if g is None or g > m:
                w['out'] += l['qty']
                days_left = month_end(l['made']) - l['made'].day
                lead = lead_of(l)
                w['held'].append(('never' if lead > month_end(l['made'])
                                  else 'sat' if days_left >= lead
                                  else 'late', l['qty']))
                why = w['held'][-1][0]
                for d in dims:
                    key = (l.get(FIELD.get(d, d)) or '').strip() or UNKNOWN
                    w['by'].setdefault(d, collections.Counter())[key] += l['qty']
                    w['why'].setdefault((d, key),
                                        collections.Counter())[why] += l['qty']
            for d in dims:
                key = (l.get(FIELD.get(d, d)) or '').strip() or UNKNOWN
                w['own'].setdefault(d, collections.Counter())[key] += l['qty']
    if not per:
        return

    say('\nwhy each month carried out what it did')
    say('  judged against each product\'s own normal lead time, not the '
        'month\'s:')
    say('    never   the product takes longer than a month, so it carries out '
        'whenever ordered')
    say('    no time this order arrived with less than that left in the month')
    say('    sat     it had that long available and did not go')
    say(f'\n  {"month":<9}{"ordered":>10}{"carried":>9}{"rate":>6}'
        f'{"never":>11}{"no time":>11}{"sat":>11}{"ordered late":>15}')
    for m in sorted(per):
        w = per[m]
        lead = wmedian(w['lead'])
        if lead is None:
            continue
        for why, q in w['held']:
            w[why] += q
        out = w['out'] or 1
        say(f'  {m:<9}{w["all"]:>10,.0f}{w["out"]:>9,.0f}'
            f'{w["out"] / (w["all"] or 1) * 100:>5.0f}%'
            f'{w["never"]:>8,.0f}{w["never"] / out * 100:>3.0f}%'
            f'{w["late"]:>8,.0f}{w["late"] / out * 100:>3.0f}%'
            f'{w["sat"]:>8,.0f}{w["sat"] / out * 100:>3.0f}%'
            f'{w["last7"]:>11,.0f}{w["last7"] / (w["all"] or 1) * 100:>4.0f}%')
    say('\n  "ordered late" is the share of the whole month\'s orders that '
        'arrived in its last\n  7 days, which is what drives the "no time" '
        'column beside it.')
    say('  A month whose carry-out is mostly "never" has a product mix '
        'problem, not a\n  fulfilment one, and the same share will come back '
        'every month it sells them.\n  Mostly "no time" means the demand '
        'arrived too late to bill - look at when the\n  promotions ran. '
        'Mostly "sat" is the only one that says something went wrong.')

    focus = [m.strip() for m in args.focus.split(',') if m.strip()] \
        if args.focus else [m for m in sorted(per, key=lambda m: -per[m]['out'])
                            if per[m]['out']][:args.top_months]
    focus = [m for m in sorted(per) if m in focus
             or m.replace('-', '')[-4:] in [f[-4:] for f in focus]]
    for m in focus:
        w = per[m]
        for d in dims:
            if d not in got:
                continue
            counts = w['by'].get(d) or {}
            if not counts:
                continue
            label, _ = DIMS[d]
            say(f'\n  {m} carried out {w["out"]:,.0f} unit(s) - by {label}')
            say(f'    {label:<34}{"carried out":>13}{"share":>7}'
                f'{"of its own orders":>19}')
            own = w['own'].get(d) or {}
            shown = 0.0
            for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:args.top]:
                base = own.get(k, 0.0)
                shown += v
                say(f'    {k[:34]:<34}{v:>13,.0f}'
                    f'{v / (w["out"] or 1) * 100:>6.0f}%'
                    + (f'{v / base * 100:>18.0f}%' if base else f'{"-":>19}'))
            rest = w['out'] - shown
            if rest > 0:
                say(f'    {f"and {len(counts) - args.top:,} more":<34}'
                    f'{rest:>13,.0f}{rest / (w["out"] or 1) * 100:>6.0f}%')
            say('    the last column is the share of what that '
                + label + ' ordered in the month that\n    carried out. A '
                'high share there is the thing itself being slow; a high\n'
                '    share of the carry-out with a low share of its own '
                'orders is just a big seller.')

    out = Path(args.by_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        wr = csv.writer(fh)
        wr.writerow(['ordered in', 'by', 'value', 'carried out units',
                     'units ordered in the month', 'share of its own orders',
                     'never in month', 'no time left', 'sat'])
        for m in sorted(per):
            w = per[m]
            for d in dims:
                if d not in got:
                    continue
                for k, v in sorted((w['by'].get(d) or {}).items(),
                                   key=lambda kv: -kv[1]):
                    base = (w['own'].get(d) or {}).get(k, 0.0)
                    r = w['why'].get((d, k)) or {}
                    wr.writerow([m, DIMS[d][0], k, round(v), round(base),
                                 f'{v / base:.4f}' if base else '',
                                 round(r.get('never', 0)),
                                 round(r.get('late', 0)),
                                 round(r.get('sat', 0))])
    say(f'\n-> {out.resolve()}')

    # A product that carries out every month is a different problem from one
    # that carried out once, and only looking across the months separates them.
    for d in dims:
        if d not in got or len(per) < 3:
            continue
        every = None
        for m in sorted(per):
            keys = {k for k, v in (per[m]['by'].get(d) or {}).items() if v > 0}
            every = keys if every is None else (every & keys)
        if every:
            rank = collections.Counter()
            for m in per:
                for k, v in (per[m]['by'].get(d) or {}).items():
                    if k in every:
                        rank[k] += v
            say(f'\n  carried out in every one of the {len(per)} months, '
                f'by {DIMS[d][0]}:')
            for k, v in rank.most_common(args.top):
                say(f'    {k[:40]:<40}{v:>13,.0f} unit(s) in all')
            say('    These are structural rather than a bad month - a thing '
                'that is always\n    ordered before it can ship.')


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
    ap.add_argument('--by', default='sku', metavar='LIST',
                    help='what to break the carry-over down by: '
                         + ', '.join(DIMS) + '. Several at once, comma '
                         'separated. division and category come off the '
                         'product master; promotion, offer and portal come off '
                         'the store export, joined on the stamped reference')
    ap.add_argument('--focus', default=None, metavar='LIST',
                    help='which months to break down, as 2602,2603 (default: '
                         'the ones that carried out the most)')
    ap.add_argument('--top-months', type=int, default=4, metavar='N',
                    help='how many months to break down when --focus is not '
                         'given')
    ap.add_argument('--top', type=int, default=12, metavar='N',
                    help='how many rows per breakdown')
    ap.add_argument('--min-units', type=int, default=20, metavar='N',
                    help='units a product must have despatched before its own '
                         'lead time is trusted over the overall one (default 20)')
    ap.add_argument('--product', default='product', metavar='STEM',
                    help='how the product master is named (default: product)')
    ap.add_argument('--dtc', default='dtc', metavar='STEM',
                    help="how the store's exports are named (default: dtc; "
                         "'26 DTC Aug' is also tried)")
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'despatch.csv'))
    ap.add_argument('--by-out', default=str(ROOT / 'docs' / 'carryout.csv'),
                    metavar='PATH',
                    help='every month x dimension x value of the carry-over, '
                         'with its three reasons - for pivoting')
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

    say_why(months, asof, gone, args, folder)

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

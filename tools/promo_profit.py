#!/usr/bin/env python3
"""What did each promotion earn?

    py tools\\promo_profit.py              # completed orders, online profit
    py tools\\promo_profit.py --status "COMPLETED,SHIPPED"

The profit file has no promotion on it. It has products, and the order file
says which promotion each product's units came in on - so the link between the
two is the product, and nothing more direct exists.

So each product's online profit is **allocated** across the promotions its
completed orders came in on, in proportion to the units they carry. A product
sold 70/30 between two promotions hands them 70/30 of its margin.

That is an allocation, not a measurement. It assumes every unit of a product
earns the same margin whichever promotion brought it in, which is exactly what
a discount does not do. What it is good for is ranking: which promotions carry
the volume, and which carry margin out of proportion to it. Where the plan
carries a promotion price and the profit file a cost, the margin those two
imply is reported beside the allocation as a check on it.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import promo_match as PM                                       # noqa: E402
# The despatch report already settled where a month's orders land: SAP's
# `Created On` is when an order arrived and `Goods Issue Date` is when it left,
# and the gap between them is the carry-over. Its column names and the key that
# joins a SAP line back to the store's order code are taken from there rather
# than written again here.
from despatch import C_GI, C_REF                                # noqa: E402
from link import order_key                                      # noqa: E402
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_file, pick_latest, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# How an order line is banded for the stack. Four answers, not two: the sketch
# this came from shows No promotion, DTC + Nation-wide and DTC promotion, and a
# nationwide campaign with no DTC campaign beside it is a real fourth that would
# otherwise have to be filed under one of the three it is not.
BANDS = [
    # key - reuses the page's existing colour slots, so no new CSS - and label
    ('plan',    'DTC promotion'),
    ('rule',    'DTC + Nation-wide'),
    ('voucher', 'Nation-wide only'),
    ('loose',   'promoted, but no campaign named'),
    ('none',    'No promotion'),
]
BAND_LABEL = dict(BANDS)

MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def band_of(plan, code: str, day, promoted: bool) -> str:
    """Which band an order line belongs in.

    Read the same way the simple match reads it: the plan lines for this
    product whose window covers this date, and which campaign columns they
    name. Not off the price-matched line - the price rejects lines the plan
    does cover, because a trade-in or a stacked voucher moves what was
    collected away from what the plan quotes, and a band decided that way would
    disagree with the DTC page about the same order.

    `promoted` says whether anything at all answered for the line. One a rule
    named but no plan line did is promoted with no campaign, which is not "no
    promotion" - saying so is the point of having that band.
    """
    cands, _ = plan.candidates(code)
    live = [c for c in cands
            if day is not None
            and (not c['start'] or day >= c['start'])
            and (not c['end'] or day <= c['end'])]
    nat = any((c.get('camp') or [''])[0] for c in live)
    dtc = any(any((c.get('camp') or ['', '', ''])[1:]) for c in live)
    if dtc and nat:
        return 'rule'
    if dtc:
        return 'plan'
    if nat:
        return 'voucher'
    return 'loose' if (promoted or live) else 'none'


def month_in_name(name: str):
    """(year, month) out of a file name like profit_2608 or 26 DTC Aug."""
    import re as _re
    m = _re.search(r'(?<!\d)(\d{2})(0[1-9]|1[0-2])(?!\d)', name)
    if m:
        return 2000 + int(m.group(1)), int(m.group(2))
    for i, mon in enumerate(MONTHS):
        if mon.lower() in name.lower():
            y = _re.match(r'\s*(\d{2})', name)
            return (2000 + int(y.group(1)) if y else 0), i + 1
    return None


def despatch_months(folder, prefix: str, say=print) -> tuple:
    """When each store order left, out of SAP's goods issue date.

    The store export says when an order was placed and nothing about when it
    shipped, so it cannot say on its own which month an order belongs to. SAP
    can. Keyed by the store's own order code, which is what SAP carries as the
    customer reference - the same join the despatch report uses.

    Where an order shipped over more than one day the earliest is kept: the
    month it first left is the month it started landing in.
    """
    for cand in pick_series(Path(folder), prefix):
        try:
            rows, _ = read_any(cand)
        except ValueError:
            continue
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        i_ref, i_gi = find(head, *C_REF), find(head, *C_GI)
        if i_ref is None or i_gi is None:
            continue
        out: dict[str, tuple] = {}
        for r in rows[1:]:
            k = order_key(r[i_ref] if i_ref < len(r) else '')
            d = PM.to_date(r[i_gi] if i_gi < len(r) else '')
            if not k or d is None:
                continue
            if k not in out or (d.year, d.month) < out[k]:
                out[k] = (d.year, d.month)
        if out:
            say(f'  {cand.name}: {len(out):,} order(s) with a goods issue date')
            return out, cand.name
    return {}, ''


def previous_stem(stem: str) -> str | None:
    """`26 DTC Aug` -> `26 DTC Jul`, and January steps the year back too.

    A promotion that ran in July is paid for in July's order file, but an order
    it brought in can complete in August and land in August's profit. Reading
    only this month's orders leaves that profit with no promotion against it.
    """
    for i, m in enumerate(MONTHS):
        if m.lower() not in stem.lower():
            continue
        cut = stem.lower().rindex(m.lower())
        prev = MONTHS[i - 1]
        out = stem[:cut] + prev + stem[cut + len(m):]
        if i == 0:
            # January's previous month is December of the year before, and the
            # year is in the stem as two digits.
            import re as _re
            yy = _re.match(r'\s*(\d{2})', out)
            if yy:
                out = (out[:yy.start(1)] + f'{int(yy.group(1)) - 1:02d}'
                       + out[yy.end(1):])
        return out
    return None


# The P&L figures worth carrying through, and the headers they arrive under.
FIGURES = [
    ('qty',    'Qty',           ('Quantity(Net)', 'Net Sales Qty', 'Qty')),
    ('net',    'Net Sales',     ('*Net Sales', 'Net Sales', 'Net Sales Amt')),
    ('cogs',   'COGS',          ('*Cost of Goods Sold', 'Cost of Goods Sold')),
    ('gm',     'Gross Margin',  ('*Gross Margin', 'Gross Margin')),
    ('opex',   'Operating Cost', ('*Operating Expense', 'Operating Expense')),
    ('profit', 'Op Profit',     ('*Operating Profit', 'Operating Profit',
                                 'Subsidiary Op.Profit')),
]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--orders', nargs='+', default=['26 DTC Aug'],
                    metavar='STEM',
                    help='the order export(s). The month before is added '
                         'automatically where its file exists, because an '
                         'order from last month\'s promotion completes this '
                         'month and its profit lands here; --no-previous '
                         'turns that off')
    ap.add_argument('--no-previous', action='store_true',
                    help='read only the order file(s) named')
    ap.add_argument('--sap', default='orders', metavar='STEM',
                    help='the SAP sales-order export that carries Goods Issue '
                         'Date, which is what says an order carried over '
                         '(default: orders)')
    ap.add_argument('--plan', nargs='+', metavar='STEM',
                    default=['MX_product', 'ce_product'],
                    help='the promotion plan(s), one per division, '
                         'read together (default: MX_product '
                         'ce_product)')
    ap.add_argument('--profit', default=None)
    ap.add_argument('--status', default='COMPLETED', metavar='LIST',
                    help='order statuses to count, comma separated '
                         '(default COMPLETED)')
    ap.add_argument('--online', default=CUST.ONLINE, metavar='NAME',
                    help=f'the profit channel to allocate (default {CUST.ONLINE}); '
                         '"" uses every channel')
    ap.add_argument('--account', metavar='NAME',
                    help='narrow the profit side to one account name exactly')
    ap.add_argument('--price-tolerance', type=float, default=3.0)
    ap.add_argument('--window-slack', type=int, default=0)
    ap.add_argument('--stem', type=int, default=0)
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--html', nargs='?', const='', metavar='PATH',
                    help='also write a page (default dashboard/promo_profit.html)')
    ap.add_argument('--cdn', action='store_true',
                    help='link Chart.js in the page instead of embedding it')
    ap.add_argument('--top', type=int, default=20)
    args = ap.parse_args()

    folder = Path(args.dir)
    # This month's orders, and the month before where it is on disk. A
    # promotion that ran in July is in July's export, and an order it brought
    # in can complete in August and be recognised in August's profit; without
    # the earlier file that profit has no promotion against it and falls into
    # "no promotion", which is the one answer it certainly is not.
    stems = list(args.orders)
    carried_from = set()
    if not args.no_previous:
        for st in list(stems):
            prev = previous_stem(st)
            if prev and prev not in stems and pick_file(folder, prev):
                stems.append(prev)
                carried_from.add(prev)
    # Paired, not two lists: dropping the stems that found no file while
    # keeping the rest would shift every later file onto the wrong stem, and
    # the carry-over flag along with it - a September run with no September
    # file read August as if it were September's own orders.
    found = [(st, pick_file(folder, st)) for st in stems]
    for st, f in found:
        if f is None:
            print(f'  no file named like {st!r} - left out')
    found = [(st, f) for st, f in found if f]
    ops = [f for _, f in found]
    pf = (pick_file(folder, args.profit) if args.profit
          else pick_latest(folder, 'profit'))
    if not ops:
        print(f'no order file matching {", ".join(stems)} in '
              f'{folder.resolve()}', file=sys.stderr)
        return 2
    if pf is None:
        print(f'no profit file in {folder.resolve()}', file=sys.stderr)
        return 2

    print('reading:')
    # Read together, with the header of the first. A later export can carry
    # extra columns; the ones this report reads are found by name on the first
    # file and a row that is short simply answers blank.
    o_head, o_body, from_prev = [], [], []
    for st, f in found:
        rows, _ = read_any(f)
        if not o_head:
            o_head = [h.strip() for h in rows[0]]
        body = rows[1:]
        (from_prev if st in carried_from else o_body).extend(body)
        print(f'  {f.name}: {len(body):,} rows'
              + ('  (last month - only what carried over is taken)'
                 if st in carried_from else ''))
    f_rows, _ = read_any(pf)
    f_head, f_body = [h.strip() for h in f_rows[0]], f_rows[1:]
    print(f'  {pf.name}: {len(f_body):,} rows')
    # Last month's file is not last month's orders. What belongs in this
    # month's profit is the part of it that carried over - placed last month,
    # shipped this month - and that is a fact only SAP's goods issue date
    # carries. Without it the whole of last month would be added to this one.
    if from_prev:
        want = month_in_name(pf.name) or month_in_name(args.orders[0])
        gi, gi_file = despatch_months(folder, args.sap)
        i_order = find(o_head, *PM.NAMES['order'])
        if not gi:
            print(f'  no {args.sap}_* export carries a goods issue date, so '
                  f'which of last month\'s\n  orders carried over cannot be '
                  f'told - last month is left out entirely rather than\n  '
                  f'added whole')
        elif want is None or i_order is None:
            print('  cannot tell which month the profit file is for, so last '
                  'month is left out')
        else:
            kept = unknown = 0
            for r in from_prev:
                k = order_key(r[i_order] if i_order < len(r) else '')
                when = gi.get(k)
                if when is None:
                    unknown += 1
                elif when == want:
                    o_body.append(r)
                    kept += 1
            print(f'  carried over from last month: {kept:,} line(s) left in '
                  f'{want[1]:02d}/{want[0]} by {gi_file}')
            if unknown:
                print(f'  {unknown:,} of last month\'s line(s) have no goods '
                      f'issue date to judge by and are left\n  with last '
                      f'month, where they were already counted')

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── the plan, as promo_match builds it ─────────────────────────────────
    # Built there and not here: which status was never live, which columns hold
    # a price and how a window is read are decisions this report has no business
    # making differently from the cross-check it is meant to agree with.
    plan, pmeta = PM.load_plans(folder, args.plan, stem=args.stem)
    if not pmeta:
        print(f'no plan file matching {", ".join(args.plan)} in '
              f'{folder.resolve()}', file=sys.stderr)
        return 2
    PM.plan_structure(pmeta)
    print(f'\nplan: {len(plan.rows):,} live line(s) over {len(plan.by_code):,} '
          f'product code(s)')

    # ── completed orders, attributed, rolled up per product ────────────────
    O = {k: find(o_head, *PM.NAMES[k]) for k in
         ('sku', 'date', 'qty', 'amount', 'rule', 'voucher', 'group', 'order')}
    O['status'] = find(o_head, 'order_status', 'Order Status', 'Status')
    keep = {s.strip().upper() for s in args.status.split(',') if s.strip()}
    units: dict[str, dict[tuple, float]] = {}
    counted = skipped = repeated = 0
    bands: dict[str, float] = {}
    # Two exports of neighbouring months overlap: a cut taken part-way through
    # a month turns up again in the next file. Counted once, by the order line
    # it is - double counting it would not change the totals, which come off
    # the profit file, but it would skew the share each promotion is allocated.
    seen: set = set()
    for r in o_body:
        if (cell(r, O['status']).upper() not in keep):
            skipped += 1
            continue
        fingerprint = (cell(r, O['order']), cell(r, O['sku']),
                       cell(r, O['date']), cell(r, O['qty']),
                       cell(r, O['amount']))
        if fingerprint in seen:
            repeated += 1
            continue
        seen.add(fingerprint)
        counted += 1
        code = key_norm(cell(r, O['sku']))
        qty = parse_number(cell(r, O['qty'])) or 0.0
        amount = parse_number(cell(r, O['amount']))
        order = {'code': PM.code_norm(cell(r, O['sku'])),
                 'date': PM.to_date(cell(r, O['date'])),
                 'price': None if amount is None or not qty
                 else amount / qty * 1.1}
        rules = [PM.parse_rule(t) for t in PM.split_rules(cell(r, O['rule']))]
        vouchers = [PM.code_norm(v)
                    for v in PM.split_rules(cell(r, O['voucher']))]
        v_hits = [p for v in vouchers for p in plan.by_voucher.get(v, [])]
        guess = PM.from_plan(order, plan, args.price_tolerance, args.window_slack)
        if rules:
            src = 'rule'
            kind, detail = PM.mechanic_of(rules)
        elif v_hits:
            src = 'voucher'
            kind = v_hits[0]['type'] or '(not named in the plan)'
            detail = v_hits[0]['detail'] or v_hits[0]['promo']
        elif guess['promo']:
            src = 'plan'
            kind = guess['type'] or '(not named in the plan)'
            detail = guess['detail'] or guess['promo']
        else:
            src = 'none'
            kind = detail = '(no promotion found)'
        # Which band the stack puts it in. The campaign comes off the plan line
        # that fitted, whichever source named the offer: the rule says what was
        # done to the price and the plan says which campaign it belonged to.
        band = band_of(plan, order['code'], order['date'], src != 'none')
        bands[band] = bands.get(band, 0.0) + qty
        share = units.setdefault(code, {})
        key = (src, band, kind, detail)
        share[key] = share.get(key, 0.0) + qty
    print(f'orders: {counted:,} line(s) counted, {skipped:,} left out by status '
          f'({", ".join(sorted(keep))})'
          + (f', {repeated:,} the same line seen twice across the exports'
             if repeated else ''))
    tot_u = sum(bands.values()) or 1.0
    print(f'\nthe stack - every counted unit in exactly one band')
    for key, label in BANDS:
        if bands.get(key):
            print(f'  {label:<34}{bands[key]:>10,.0f}{bands[key] / tot_u * 100:>7.1f}%')
    return allocate(args, folder, f_head, f_body, units, cell,
                    ' + '.join(f.name for f in ops),
                    month_in_name(pf.name) or month_in_name(args.orders[0]), pf.name)


def allocate(args, folder, f_head, f_body, units, cell, read: str = '',
             when=None, profit_name: str = '') -> int:
    """Split each product's online profit across the promotions it sold under."""
    F = {k: find(f_head, *names) for k, _, names in FIGURES}
    F['sku'] = find(f_head, 'Material', 'Product Number', 'SKU', 'Material Code')
    F['cust'] = find(f_head, 'Customer', 'Payer', 'sold To', 'Sold-To')
    print('\nprofit columns:')
    for key, label, _ in FIGURES:
        i = F[key]
        print(f'  {label:15} {f_head[i] if i is not None else "-- not found --"}')
    if F['sku'] is None or F['net'] is None:
        print('\nwithout a product code and a net sales column there is nothing '
              'to allocate', file=sys.stderr)
        return 1

    cust = {}
    cp = pick_latest(folder, 'customer')
    if cp and F['cust'] is not None and args.online:
        want = {slot: names for _, slot, names in CUST.LEVELS if names}
        want['account'] = CUST.ACCOUNT_NAMES
        want['who'] = ('Description', 'description', 'Account Name')
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'), want,
                      say=lambda *a: None)

    keys = [k for k, _, _ in FIGURES]
    # One bucket per product and per customer level, so the allocation can be
    # read by Type as well as by offer. The promotion split is the product's -
    # it comes from the order file, which has no payer on it - but the profit
    # being split knows whose it was.
    cells: dict[tuple, list[float]] = {}
    sku_totals: dict[str, list[float]] = {}
    online_rows = all_rows = 0
    for r in f_body:
        all_rows += 1
        c = cust.get(key_norm(cell(r, F['cust']))) if cust else None
        if args.online:
            if not c or CUST.channel_of(c['account']) != args.online:
                continue
            if args.account and (c['account'] or '').upper() != args.account.upper():
                continue
        online_rows += 1
        code = key_norm(cell(r, F['sku']))
        payer = cell(r, F['cust'])
        who = ((CUST.channel_of(c['account']) if c and c.get('account')
                else CUST.NO_MATCH),
               (c.get('type') if c else '') or '(master does not say)',
               (c.get('type2') if c else '') or '(master does not say)',
               (c.get('who') if c else '') or payer or '(blank)')
        v = cells.setdefault((code,) + who, [0.0] * len(keys))
        t = sku_totals.setdefault(code, [0.0] * len(keys))
        for j, k in enumerate(keys):
            n = parse_number(cell(r, F[k])) if F[k] is not None else None
            if n is not None:
                v[j] += n
                t[j] += n
    print(f'\nprofit: {online_rows:,} of {all_rows:,} row(s) are '
          f'{args.account or args.online or "every channel"}, over '
          f'{len(sku_totals):,} product code(s)')

    # ── how much of that profit the orders can speak for ───────────────────
    net_i = keys.index('net')
    profit_i = keys.index('profit') if 'profit' in keys else None
    covered = [c for c in sku_totals if c in units]
    cov_net = sum(sku_totals[c][net_i] for c in covered)
    all_net = sum(v[net_i] for v in sku_totals.values())
    print(f'  {len(covered):,} of them have completed orders to allocate by, '
          f'{cov_net / all_net * 100 if all_net else 0:,.1f}% of the net sales')
    if all_net and cov_net / all_net < 0.5:
        print('  under half - the allocation below describes that half, not the '
              'channel')

    # ── the allocation ─────────────────────────────────────────────────────
    out: dict[tuple, list[float]] = {}
    for cellkey, totals in cells.items():
        code, who = cellkey[0], cellkey[1:]
        share = units.get(code)
        if not share:
            key = ('none', 'none', '(sold with no completed order)',
                   '(sold with no completed order)') + who
            agg = out.setdefault(key, [0.0] * (len(keys) + 1))
            for j in range(len(keys)):
                agg[j] += totals[j]
            continue
        total_units = sum(share.values())
        for offer, u in share.items():
            w = (u / total_units) if total_units else 1.0 / len(share)
            agg = out.setdefault(offer + who, [0.0] * (len(keys) + 1))
            for j in range(len(keys)):
                agg[j] += totals[j] * w
            agg[-1] += u * w                   # the units that earned the share

    # Where each piece of the key now sits: source, band, offer type, offer
    # detail, then the four customer levels.
    AT = {'band': 1, 'type': 2, 'detail': 3,
          'channel': 4, 'ctype': 5, 'ctype2': 6, 'customer': 7}

    def table(cols, title: str) -> None:
        """One row per offer, whichever source answered for it.

        The source is how the promotion was identified, not a promotion of its
        own, so rolling up by it would list Discount once per source. It is
        reported as which source most of the row came from instead.
        """
        rolled: dict[tuple, list[float]] = {}
        origin: dict[tuple, dict[str, float]] = {}
        for key, v in out.items():
            k = tuple(key[i] for i in cols)
            agg = rolled.setdefault(k, [0.0] * len(v))
            for j in range(len(v)):
                agg[j] += v[j]
            seen = origin.setdefault(k, {})
            seen[key[0]] = seen.get(key[0], 0.0) + v[net_i]
        rows = sorted(rolled.items(), key=lambda kv: -kv[1][net_i])
        print(f'\n{title}')
        print(f'  {"":<32}{"units":>9}{"net sales":>13}{"op profit":>13}'
              f'{"op prof %":>10}{"share":>7}  from')
        tot_net = sum(v[net_i] for _, v in rows) or 1
        for k, v in rows[:args.top]:
            # The band is stored as its colour slot, so it is spelled out
            # wherever a person reads it.
            name = ' / '.join(BAND_LABEL.get(x, x) for x in k)
            margin = (v[profit_i] / v[net_i] * 100
                      if profit_i is not None and v[net_i] else None)
            src = max(origin[k], key=origin[k].get)
            print(f'  {name[:32]:<32}{v[keys.index("qty")]:>9,.0f}'
                  f'{v[net_i]:>13,.0f}'
                  f'{v[profit_i] if profit_i is not None else 0:>13,.0f}'
                  + (f'{margin:>7,.1f}%' if margin is not None else f'{"-":>8}')
                  + f'{v[net_i] / tot_net * 100:>6,.1f}%  {src}')
        if len(rows) > args.top:
            print(f'  ... and {len(rows) - args.top:,} more in the csv')

    table([AT['band']],
          'by promotion  (profit allocated by unit share, not measured)')
    table([AT['type']], 'by offer type')
    table([AT['type'], AT['detail']], 'by offer detail')
    table([AT['ctype']], 'by customer Type')
    table([AT['customer']], 'by customer')

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    # Named for the month it is about, read off the profit file rather than
    # written here. The page was called promo_profit.html and titled August
    # whatever month was fed to it, so a September run overwrote August's with
    # September's numbers under August's name - the one mistake a file name can
    # make that nobody catches, because the file is there and it opens.
    yymm = f'{when[0] % 100:02d}{when[1]:02d}' if when else ''
    path = outdir / f'promo_profit{("_" + yymm) if yymm else ""}.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Source', 'Promotion', 'Offer type', 'Offer detail',
                    'Channel', 'Type', 'Type2', 'Customer', 'Allocated units']
                   + [label for _, label, _ in FIGURES]
                   + ['Op profit %', 'Gross margin %'])
        for key, v in sorted(out.items(), key=lambda kv: -kv[1][net_i]):
            key = (key[0], BAND_LABEL.get(key[1], key[1])) + key[2:]
            margin = (v[profit_i] / v[net_i] * 100
                      if profit_i is not None and v[net_i] else '')
            gm = (v[keys.index('gm')] / v[net_i] * 100
                  if 'gm' in keys and v[net_i] else '')
            w.writerow(list(key) + [round(v[-1], 2)]
                       + [round(v[j], 2) for j in range(len(keys))]
                       + [round(margin, 2) if margin != '' else '',
                          round(gm, 2) if gm != '' else ''])
    print(f'\n-> {path.resolve()}')
    print('\nthe profit file carries no promotion, so this is each product\'s '
          'profit split by the units its completed orders came in on. It ranks '
          'promotions; it does not measure what a discount cost.')
    if args.html is not None:
        write_page(Path(args.html) if args.html
                   else ROOT / 'dashboard' /
                   f'promo_profit{("_" + yymm) if yymm else ""}.html',
                   args, out, keys, cov_net / all_net * 100 if all_net else 0.0,
                   read, when, profit_name)
    return 0


def write_page(path: Path, args, out: dict, keys: list, coverage: float,
               read: str = '', when=None, profit_name: str = '') -> None:
    """The allocation as one self-contained page.

    One row per source, per customer level and per offer - which is the finest
    grain the allocation has, so nothing is lost by rolling up to it.
    """
    import json

    # The drill is the one this page already had: the customer half off the
    # payer on the profit row, the offer half from the promotion, opening on
    # Offer type because that is the question the file answers. What changed is
    # only what the bars stack by - the promotion band instead of which source
    # identified it - so every bar carries the split and it holds down the
    # drill, at whatever level is being read.
    LEVELS = ['Channel', 'Type', 'Type2', 'Customer', 'Offer type',
              'Offer detail']
    sources: dict[str, int] = {}
    values: list[dict[str, int]] = [{} for _ in LEVELS]

    def idx(d, v):
        return d.setdefault(v, len(d))

    rows = []
    for key, v in out.items():
        src, band, kind, detail = key[0], key[1], key[2], key[3]
        order = key[4:8] + (kind, detail)
        # The stack is the band, not which source identified it: the question
        # the page is opened with is how much of the month ran on a promotion,
        # and the source is a property of how that was worked out.
        rows.append({'s': idx(sources, band),
                     'k': [idx(values[i], x) for i, x in enumerate(order)],
                     'v': [round(v[j], 2) for j in range(len(keys))]})
    payload = {
        'title': (f'{MONTHS[when[1] - 1]} {when[0]} Promotion profit'
                  if when else 'Promotion profit'),
        # The files actually read, not the one stem asked for: the month
        # before is added on its own, and a page that does not say so looks
        # like it is counting orders that are not in the file it names.
        'orders': read or ', '.join(args.orders),
        'profit': profit_name or args.profit or 'the latest profit export',
        'status': args.status,
        'channel': args.account or args.online or 'every channel',
        'coverage': round(coverage, 1),
        'sources': list(sources),
        # The bands, in the order they stack, and only those this run has.
        'sourceLabels': [[k, lbl] for k, lbl in BANDS if k in sources],
        'startDim': LEVELS.index('Offer type'),
        'custDepth': 4,
        'levels': [{'name': n, 'values': list(v)}
                   for n, v in zip(LEVELS, values)],
        'figures': {k: j for j, k in enumerate(keys)},
        'figureCount': len(keys),
        'rows': rows,
    }
    here = ROOT / 'dashboard'
    html = (here / 'promo_profit_template.html').read_text(encoding='utf-8')
    html = html.replace('/*__DATA__*/null',
                        json.dumps(payload, ensure_ascii=False,
                                   separators=(',', ':')))
    if not args.cdn:
        lib = here / 'vendor' / 'chart.umd.js'
        if lib.is_file():
            code = lib.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
            html = html.replace(
                '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>',
                f'<script>/* chart.umd.js */\n{code}\n</script>')
        else:
            print('vendor/chart.umd.js missing - the page will need a connection')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding='utf-8')
    print(f'-> {path.resolve()}  ({len(html.encode("utf-8")) / 1024:,.0f} KB)')


if __name__ == '__main__':
    sys.exit(main())

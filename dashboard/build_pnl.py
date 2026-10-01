#!/usr/bin/env python3
"""Draw the profit chart: what came in, where it went, what was left.

    py dashboard\\build_pnl.py                 # -> dashboard/pnl_<month>.html
    py dashboard\\build_pnl.py --open

One bar for gross sales, a stack beside it for sales deduction, cost of goods
sold and operating cost, and a line for operating profit over net sales - the
shape of the Sales Dashboard's profit chart, across the members of whichever
dimension is picked rather than across months.

Which column is which comes from tools/analyze_structure.py, which works the
relations out from the numbers; this only draws them. Run that first, or let
this recompute when the saved analysis does not match the export.

The numbers are embedded, so the page works with no server, no database and no
connection - it can be sent to someone and opened.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import analyze_structure as A                                  # noqa: E402
import customer as CUST                                        # noqa: E402
import orders as ORD                                           # noqa: E402
import sap as SAP                                              # noqa: E402
from rawdata import (MASTER_RAW as RAW, find, key_norm, master,  # noqa: E402
                     month_before, month_name, month_of, parse_number,
                     pick_file, pick_latest, pick_series, read_any)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


# The drill, top first: the account name only says online or offline, and the
# detail comes from the levels underneath it. Product sits alongside.
PRODUCT_LEVELS = [
    ('Division', 'division', ('Division', 'Division 2')),
    ('Category', 'category', ('Prod_group', 'Product Group', 'Category')),
    ('Range',    'range',    ('Range', 'product_range', 'Material Group')),
    # The SKU itself, so per-unit prices can be read down to one model. Taken
    # from the export rather than the master, so it works even unjoined.
    ('SKU',      'sku',      ()),
]
FILTERS = CUST.LEVELS + PRODUCT_LEVELS
CUST_DEPTH = len(CUST.LEVELS)

# The five figures the chart is made of, plus the denominator of the line. Each
# is looked up by header with the spellings the export has used, and the build
# prints what it matched.
SERIES = [
    ('gross',     'Gross Sales', ('*S.Gross Sales', '*Gross Sales', 'Gross Sales',
                                  'S.Gross Sales AMT', '*Net Sales', 'Net Sales')),
    ('deduction', 'Sales Deduction', ('*Sales Deduction', 'Sales Deduction',
                                      '*Delear Discount')),
    ('cogs',      'COGS', ('*Cost of Goods Sold', 'Cost of Goods Sold', 'COGS',
                           '*Ref. CoGS')),
    ('opex',      'Operating Cost', ('*Operating Expense', 'Operating Expense',
                                     'Operating Cost', '*Operating Cost',
                                     '*Other Expense')),
    ('profit',    'Operating Profit', ('*Operating Profit', 'Operating Profit',
                                       'Subsidiary Op.Profit')),
    # The denominator of the profit line, kept apart from the gross figure:
    # the line is profit over net sales, not over gross.
    ('net',       'Net Sales', ('*Net Sales', 'Net Sales', 'Net Sales Amt')),
    # And the denominator of every per-unit figure, ASP among them.
    ('qty',       'Qty', ('Quantity(Net)', 'Net Sales Qty', 'Qty', 'Quantity')),
]

# The order files' own figures, totalled onto the same key. They are counts of
# what was ordered, not a share of what was sold, so the basis never scales
# them - see ORDERED in the template.
#
# The month is modelled as: what its own orders booked, plus what the month
# before carried into it, less what it carries on. `tools/cohort.py` tested that
# reading against the month it claims to explain and it came back at 99% of the
# units, so it is the one the page runs on.
ORDER_SERIES = [
    ('oqty', 'Booked Qty (this month\'s orders)'),
    ('oamt', 'Booked (this month\'s orders)'),
    ('iqty', 'Carried-in Qty'),
    ('iamt', 'Carried in'),
    ('xqty', 'Carried-out Qty'),
    ('xamt', 'Carried out'),
]
N_ORDER = len(ORDER_SERIES)

MONTHS_LONG = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--file', default=None,
                    help='the export to draw (default: the highest-numbered '
                         'profit_* file in the folder)')
    # Both default to the month the export turns out to cover, so a new month
    # does not quietly overwrite the last one's page under the last one's name.
    ap.add_argument('--out', default=None,
                    help='default: dashboard/pnl_<month>.html')
    ap.add_argument('--title', default=None,
                    help="default: the export's month, e.g. September 2026 Profit")
    ap.add_argument('--structure', default=str(ROOT / 'docs' / 'structure.json'),
                    help='the analysis to read; recomputed if it does not match')
    ap.add_argument('--start-channel', metavar='NAME', default=CUST.ONLINE,
                    help=f'the channel the page opens on (default: {CUST.ONLINE}). '
                         'Pass "" to open on all of them.')
    ap.add_argument('--find', metavar='VALUE',
                    help='say where one code appears - which column of the export '
                         'holds it and what the masters have for it')
    ap.add_argument('--where', metavar='VALUE',
                    help='say where one filter value sits - which Channel, Type '
                         'and so on carry it, and how many rows. e.g. --where GOV')
    ap.add_argument('--cdn', action='store_true',
                    help='link Chart.js instead of embedding it: a smaller file '
                         'that then needs a connection')
    ap.add_argument('--orders', default=None, metavar='NAME',
                    help='the order export for the month the profit file covers. '
                         "By default the one named for that month, e.g. '26 DTC "
                         "Sep' for a September profit file")
    ap.add_argument('--orders-before', default=None, metavar='NAME',
                    help='the month before, whose unfinished orders became this '
                         "month's revenue. By default the one named for it. "
                         'Without it the page cannot say what was carried in')
    ap.add_argument('--sap', default='orders', metavar='STEM',
                    help="SAP's sales-order exports, which carry a despatch "
                         'date and so need no inference at all (default: the '
                         'orders_* files). This is the basis the page prefers')
    ap.add_argument('--no-sap', action='store_true',
                    help="fall back to the store export and its statuses, "
                         'which has to infer which month a unit belongs to')
    ap.add_argument('--any-month', action='store_true',
                    help='model the month with whatever order exports were '
                         'named, even when their dates say they are other '
                         'months. Off by default, because modelling a month '
                         'with the wrong orders is worse than not modelling it')
    ap.add_argument('--positive', default=','.join(ORD.POSITIVE), metavar='LIST',
                    help='order status(es) that book money this month '
                         f'(default {", ".join(ORD.POSITIVE)})')
    ap.add_argument('--negative', default=','.join(ORD.NEGATIVE), metavar='LIST',
                    help='status(es) that take money back this month. The '
                         'profit file counts quantity net of returns, so these '
                         'are subtracted rather than dropped (default '
                         f'{", ".join(ORD.NEGATIVE)})')
    ap.add_argument('--booked', default=None, metavar='LIST',
                    help='read the statuses the old way instead: these book, '
                         'cancelled and returned are dropped, the rest carry. '
                         'py tools\\cohort.py scores the two against the month '
                         'they claim to explain')
    ap.add_argument('--currency', metavar='CODE',
                    help='which money column to read from an order export that '
                         'carries several, e.g. USD. The unit figures - and the '
                         'basis, which is built on them - are unaffected')
    ap.add_argument('--skip-sku', metavar='PREFIX', default='',
                    help='product-code prefixes to leave out of the order side, '
                         'e.g. SMC-AU- for service plans that are ordered but '
                         'never reach the profit file')
    ap.add_argument('--no-orders', action='store_true',
                    help='draw sales only, even when an order export is there')
    ap.add_argument('--shipped', metavar='LIST',
                    help='comma-separated order statuses to count as shipped, '
                         'replacing the built-in list. Everything else is open')
    ap.add_argument('--agree', type=float, default=80.0, metavar='PCT',
                    help='how much of the accounts behind a portal group must '
                         'agree before a level is asserted for it (default 80)')
    ap.add_argument('--open', action='store_true')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    target = (pick_file(folder, args.file) if args.file
              else pick_latest(folder, 'profit'))
    if target is None:
        print(f'no profit export in {folder.resolve()}', file=sys.stderr)
        return 2

    print('reading:')
    rows, info = read_any(target)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    print(f'  {target.name}: {info["format"]}, {len(body):,} rows, {len(head)} columns')

    ym = month_of(head, body, target.stem)
    if ym:
        print(f'  the month it covers: {ym}')
    if args.title is None:
        args.title = (f'{MONTHS_LONG[(ym % 100) - 1]} {ym // 100} Profit' if ym
                      else 'Profit')
    if args.out is None:
        args.out = str(HERE / (f'pnl_{str(ym)[-4:]}.html' if ym
                               else f'pnl_{target.stem}.html'))

    cols = A.column_profile(head, body)
    measures = [c['pos'] for c in cols if A.is_measure(c, len(body))]
    print(f'  {len(measures)} amount column(s)')

    # ── the structure, so the five figures are named rather than guessed ───
    saved = None
    sp = Path(args.structure)
    if sp.is_file():
        try:
            saved = json.loads(sp.read_text(encoding='utf-8'))
        except ValueError:
            saved = None
    same = (saved and saved.get('file') == target.name
            and [c['header'] for c in saved.get('columns', [])] ==
            [c['header'] for c in cols])
    if same:
        nodes = saved['nodes']
        print(f'  structure: {len(nodes)} relation(s) from {sp}')
    else:
        if saved:
            print(f'  {sp.name} was built from a different export - redoing it')
        nodes = A.analyse(cols, measures, len(body))

    print('\nthe chart\'s figures:')
    series, pos_of = [], {}
    for key, label, names in SERIES:
        i = find(head, *names)
        print(f'  {label:17} {head[i] if i is not None else "-- not found --"}')
        if i is not None:
            pos_of[key] = i
            series.append({'key': key, 'label': label})
    if not {'gross', 'profit'} <= set(pos_of):
        print('\nWithout a gross figure and an operating profit there is nothing '
              'to draw.', file=sys.stderr)
        print('Headers seen:', ', '.join(head[:40]), file=sys.stderr)
        return 1

    # Say out loud whether the four bars actually account for the profit line.
    if {'deduction', 'cogs', 'opex'} <= set(pos_of):
        derived = {n['pos'] for n in nodes}
        print('  operating profit '
              + ('is a total the analysis broke down, so the bars and the line '
                 'come from one statement'
                 if pos_of['profit'] in derived else
                 'stands on its own in this export; the bars are not guaranteed '
                 'to account for it exactly'))

    # ── masters ────────────────────────────────────────────────────────────
    cust = prod = {}
    cp = pick_latest(folder, 'customer')
    if cp:
        want = {slot: names for _, slot, names in CUST.LEVELS if names}
        want['account'] = CUST.ACCOUNT_NAMES
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'), want)
        print(f'\ncustomer master: {len(cust):,} accounts')
    pp = pick_latest(folder, 'product')
    if pp:
        prod = master(pp, ('SKU', 'sku', 'Material'),
                      {slot: names for _, slot, names in PRODUCT_LEVELS})
        print(f'product master: {len(prod):,} products')

    c_key = find(head, 'Payer', 'sold To', 'Sold-To', 'Customer', 'Customer Code',
                 'Payer Code', 'Sold To Party')
    p_key = find(head, 'Material', 'SKU', 'Material Code', 'Product Number',
                 'Model', 'Model Code', 'Material No', 'Item', 'Product',
                 'Product Code')
    print('\njoining on:')
    for what, i in (('customer', c_key), ('product', p_key)):
        print(f'  {what:9} {head[i] if i is not None else "-- no such column --"}'
              + ('' if i is not None else
                 f'  (nothing will match {what}_2608)'))
    if c_key is None or p_key is None:
        print('  columns in the export: ' + ', '.join(head[:30])
              + (' ...' if len(head) > 30 else ''))
    acct_fb = find(head, *CUST.ACCOUNT_NAMES)
    fallback = [find(head, *names) if names else None for _, _, names in FILTERS]

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    if args.find:
        needle = key_norm(args.find)
        hits: dict[int, int] = {}
        for r in body:
            for i, v in enumerate(r):
                if key_norm(v) == needle:
                    hits[i] = hits.get(i, 0) + 1
        print(f'\nfind {args.find!r} in {target.name}:')
        if not hits:
            print('  not in any column - no row of this export carries it')
        for i, n in sorted(hits.items(), key=lambda kv: -kv[1]):
            tag = (' <- the column joined to the customer master' if i == c_key else
                   ' <- the column joined to the product master' if i == p_key else '')
            print(f'  column [{i}] {head[i]}: {n:,} row(s){tag}')
        for name, m in (('customer_2608', cust), ('product_2608', prod)):
            row = m.get(needle)
            print(f'  {name}: ' + (' / '.join(f'{k}={v or "(blank)"}'
                                              for k, v in row.items())
                                   if row else 'not listed'))
        # The levels are only part of what the master holds. Print the whole
        # row: a value that is plainly there but never reaches a filter is
        # sitting in a column no level reads, and this is where that shows.
        for fname, (mhead, mrows) in RAW.items():
            mkey = find(mhead, 'Sold-To', 'sold To', 'sold_to', 'SKU', 'Material')
            if mkey is None:
                continue
            for r in mrows:
                if key_norm(r[mkey] if mkey < len(r) else '') != needle:
                    continue
                print(f'  {fname}, every column of that row:')
                for i, h in enumerate(mhead):
                    v = r[i].strip() if i < len(r) else ''
                    if not v:
                        continue
                    where = [lbl for lbl, _, names in FILTERS
                             if names and find([h], *names) is not None]
                    if not where and find([h], *CUST.ACCOUNT_NAMES) is not None:
                        where = ['Channel (online or offline)']
                    print(f'    {h:22} {v}'
                          + (f'   -> {where[0]}' if where else
                             '   (no filter level reads this column)'))
                break

    # ── roll up: one row per combination of the filter values ──────────────
    keys = [k for k, _, _ in SERIES if k in pos_of]
    combos: dict[tuple, list[float]] = {}
    counts: dict[tuple, int] = {}
    matched_c = matched_p = 0
    from_master = [0] * len(FILTERS)
    from_export = [0] * len(FILTERS)
    for r in body:
        c = cust.get(key_norm(cell(r, c_key))) or {}
        p = prod.get(key_norm(cell(r, p_key))) or {}
        matched_c += bool(c)
        matched_p += bool(p)
        src = {**c, **p}
        sku = cell(r, p_key)
        key = [CUST.channel_of(c.get('account') or cell(r, acct_fb), bool(c))]
        from_master[0] += bool(c)
        from_export[0] += not c and bool(cell(r, acct_fb))
        for n, ((_, slot, _), fb) in enumerate(zip(FILTERS, fallback)):
            if n == 0:
                continue
            if slot == 'sku':
                from_export[n] += bool(sku)
                key.append(sku or CUST.BLANK)
                continue
            v = src.get(slot)
            if v:
                from_master[n] += 1
            else:
                v = cell(r, fb)
                from_export[n] += bool(v)
            key.append(v or CUST.BLANK)
        key = tuple(key)
        vals = combos.get(key)
        if vals is None:
            vals = combos[key] = [0.0] * len(keys)
        counts[key] = counts.get(key, 0) + 1
        for j, k in enumerate(keys):
            n = parse_number(cell(r, pos_of[k]))
            if n is not None:
                vals[j] += n
    print(f'\njoined: {matched_c:,} of {len(body):,} rows matched a customer, '
          f'{matched_p:,} matched a product')

    # A join that matches nothing is two codes that were never the same code.
    # Print both sides: the mismatch is usually obvious once they sit together.
    for what, n, i, m, mfile in (('customer', matched_c, c_key, cust, 'customer_2608'),
                                 ('product', matched_p, p_key, prod, 'product_2608')):
        if n or not m:
            continue
        keyed = f'{mfile} is keyed on ' + ', '.join(repr(k) for k in list(m)[:4])
        if i is None:
            print(f'  not one row matched {mfile}: the export has no column this '
                  f'build recognises as a {what} key. {keyed}')
            continue
        theirs = [key_norm(cell(r, i)) for r in body[:2000] if cell(r, i)]
        print(f'  not one row matched {mfile}. '
              + (f'{head[i]!r} holds e.g. ' + ', '.join(repr(k) for k in theirs[:4])
                 if theirs else f'{head[i]!r} is empty on every row')
              + f'; {keyed}')
    print(f'{len(combos):,} filter combination(s) from {len(body):,} rows')

    # ── the other half of the month: what was ordered ──────────────────────
    # The order export knows its portal group and its product; it does not know
    # the payer, so it cannot say which Type2 an order belongs to when the
    # accounts behind a group disagree. Keyed at full depth it would therefore
    # never meet the profit file at all.
    #
    # So an order is spread across the sales that are consistent with it - the
    # combinations that agree on every level the order does assert - in
    # proportion to the units each one sold. An order for 100 EPP units of a SKU
    # lands on the EPP rows of that SKU, in the shape those rows already have.
    # That is an allocation and nothing more; it says where an order could have
    # gone, in the proportions the month itself gives.
    n_measures = len(keys)

    def merge_orders(by_key, drop=()):
        """Add an order side onto the combinations, spreading only what has to be.

        A SAP key is already at full depth - it came from the payer and the
        material, the same two things the profit file is keyed on - so it lands
        on its own combination. A store-export key carries blanks where the
        portal group could not settle a level, and those are spread across the
        sales they are consistent with, in proportion to what each one sold.
        """
        nonlocal keys, series
        wanted = set(by_key)
        if drop:
            sku_at = len(FILTERS) - 1
            wanted = {k for k in wanted
                      if not str(k[sku_at]).upper().startswith(drop)}
        sold_keys = list(combos)
        qi = keys.index('qty') if 'qty' in keys else None
        for vals in combos.values():
            vals.extend([0.0] * N_ORDER)

        # One index per distinct set of levels a key asserts. There are only a
        # handful, and building them once beats walking every combination.
        index: dict[tuple, dict] = {}
        exact = spread_u = orphan_u = 0.0
        orphans = 0
        for ok in wanted:
            v = list(by_key[ok])
            units = v[0] + v[2] + v[4]
            known = tuple(j for j, x in enumerate(ok) if x != CUST.BLANK)
            idx = index.get(known)
            if idx is None:
                idx = index[known] = {}
                for ck in sold_keys:
                    idx.setdefault(tuple(ck[j] for j in known), []).append(ck)
            hits = idx.get(tuple(ok[j] for j in known)) or []
            if len(hits) == 1 and hits[0] == ok:
                exact += units
            if not hits:
                orphans += 1
                orphan_u += units
                combos[ok] = [0.0] * n_measures + v
                counts.setdefault(ok, 0)
                continue
            spread_u += units if len(hits) > 1 else 0
            weight = [abs(combos[ck][qi]) if qi is not None else 1.0
                      for ck in hits]
            total = sum(weight)
            if not total:
                weight = [1.0] * len(hits)
                total = float(len(hits))
            for ck, w in zip(hits, weight):
                share = w / total
                row = combos[ck]
                for m in range(N_ORDER):
                    row[n_measures + m] += v[m] * share

        keys = keys + [k for k, _ in ORDER_SERIES]
        series = series + [{'key': k, 'label': lbl} for k, lbl in ORDER_SERIES]
        print(f'\n  onto the sales: {exact:,.0f} unit(s) landed on one '
              f'combination exactly, {spread_u:,.0f} had to be\n  spread over '
              'the combinations they were consistent with')
        if orphans:
            print(f'  {orphans:,} combination(s) ({orphan_u:,.0f} units) have no '
                  'sale in the month at all -\n  they chart as orders, and a '
                  'basis other than Sales leaves them out, because there\n  is '
                  'no sale of theirs to take a per-unit cost from')


    # ── the measured basis, where SAP's exports are there ──────────────────
    # SAP carries a despatch date, so which month a unit earned in is read
    # rather than argued for, and it carries the payer, so the key comes out at
    # full depth with nothing spread. Both beat the store export, so it goes
    # first and the store export is the fallback.
    got_sap = None
    if not args.no_orders and not args.no_sap and ym:
        sap_files = pick_series(folder, args.sap)
        seen_stem = set()
        sap_files = [f for f in sap_files
                     if not (f.stem.lower() in seen_stem
                             or seen_stem.add(f.stem.lower()))]
        if sap_files:
            print('\nreading SAP orders:')
            got_sap = SAP.load(
                sap_files, month=ym, cust_levels=CUST.LEVELS,
                prod_levels=PRODUCT_LEVELS, customers=cust, products=prod,
                currency=args.currency,
                skip_sku=tuple(t.strip().upper()
                               for t in args.skip_sku.split(',') if t.strip()))
            if got_sap:
                SAP.report(got_sap, ym)
                if not any(f for f in sap_files
                           if month_before(ym) == month_of(
                               [], [], f.stem, say=lambda *a: None)):
                    print(f'  no {month_before(ym)} export, so what that month '
                          'carried into this one is missing')
                merge_orders(got_sap.by_key)
                oi = n_measures
                own = sum(v[oi] for k, v in combos.items())
                came = sum(v[oi + 2] for v in combos.values())
                sold = (abs(sum(v[keys.index('qty')] for k, v in combos.items()
                                if k[0] == CUST.ONLINE))
                        if 'qty' in keys else 0)
                model = own + came
                print(f'\n  the month off SAP: {own:,.0f} booked + {came:,.0f} '
                      f'carried in = {model:,.0f} units')
                if sold:
                    print(f'  the month as sold, {CUST.ONLINE} only: '
                          f'{sold:,.0f} units  ({model / sold * 100:.0f}% of it '
                          'accounted for)')
                    if abs(model - sold) > sold * 0.2:
                        print('  that is a wide gap - py tools\\link.py scores '
                              'the same figures product by product')

    # Which two exports model this month: the one named for it, and the one
    # named for the month before, unless both were named on the command line.
    want_now = args.orders or (month_name(ym) if ym else None)
    want_was = args.orders_before or (month_name(month_before(ym)) if ym else None)
    op = (None if args.no_orders or got_sap or not want_now
          else pick_file(folder, want_now))
    bp = (None if args.no_orders or got_sap or not want_was
          else pick_file(folder, want_was))
    if not args.no_orders and not got_sap and op is None and want_now:
        print(f'\nno order export named like {want_now!r}, so the page is sales '
              'only. Name one with --orders.')
        here = sorted(q.name for q in folder.iterdir()
                      if q.is_file() and 'dtc' in q.stem.lower())
        if here:
            print('  order-looking files in the folder: ' + ', '.join(here))
    if op is not None:
        print('\nreading orders:')
        drop = tuple(t.strip().upper() for t in args.skip_sku.split(',')
                     if t.strip())
        load = dict(cust_levels=CUST.LEVELS, prod_levels=PRODUCT_LEVELS,
                    customer_master=cp, products=prod, agree=args.agree,
                    currency=args.currency, signed=args.booked is None,
                    positive=tuple(t.strip().upper()
                                   for t in args.positive.split(',') if t.strip()),
                    negative=tuple(t.strip().upper()
                                   for t in args.negative.split(',') if t.strip()),
                    booked=({t.strip().upper() for t in args.booked.split(',')
                             if t.strip()} if args.booked else None))
        this = ORD.load(op, **load)
        before = ORD.load(bp, **load) if bp is not None else None
        if bp is None:
            print(f'  no file named like {want_was!r}, so the page cannot say '
                  'what was carried into this month')

        # Modelling a month with another month's orders is worse than not
        # modelling it, and nothing downstream would show that it happened.
        if ym and not args.any_month:
            for who, side, expect in (('orders', this, ym),
                                      ('orders-before', before, month_before(ym))):
                if side is None:
                    continue
                got = side.month()
                if got == expect:
                    continue
                lo, hi = side.span()
                print(f'\n  {side.path.name} is not the {expect} export: its '
                      + (f'orders run {lo} .. {hi}' if lo else
                         'order dates could not be read')
                      + f'.\n  The profit file covers {ym}, so --{who} wants '
                      f'the {expect} export. Nothing is modelled from orders '
                      'until they line up;\n  --any-month overrides this.')
                this = None
                break
        if this is not None:
            ORD.report(this)
            if before is not None:
                ORD.report(before)

            # Six slots per key: what this month's own orders booked, what the
            # month before carried in, and what this month carries on.
            by_key_store = {}
            for key in set(this.by_key) | (set(before.by_key) if before else set()):
                own = this.by_key.get(key) or [0.0] * 4
                came = ((before.by_key.get(key) or [0.0] * 4) if before
                        else [0.0] * 4)
                by_key_store[key] = [own[0], own[1], came[2], came[3],
                                     own[2], own[3]]
            merge_orders(by_key_store,
                         tuple(t.strip().upper()
                               for t in args.skip_sku.split(',') if t.strip()))
            # The month as the orders model it, beside the month as sold. A
            # wide gap between them means the booking rule does not describe
            # this export, and py tools\cohort.py is where to find out why.
            oi = n_measures
            own = sum(v[oi] for v in combos.values())
            came = sum(v[oi + 2] for v in combos.values())
            goes = sum(v[oi + 4] for v in combos.values())
            # The orders are the online store's, so the only sales they can
            # account for are the online ones. Comparing against the whole file
            # would charge them with the offline business as well.
            sold = abs(sum(v[qi] for k, v in combos.items()
                           if k[0] == CUST.ONLINE)) if qi is not None else 0
            model = own + came
            # The basis is built on units; money rides along for the tooltips
            # and the stacked chart, so where it comes from is worth saying.
            print(f'\n  units from the order exports, money from '
                  + (repr(this.amount_col) if this.amount_col else 'nowhere')
                  + f'; the profit side is {head[pos_of["qty"]]!r} and '
                  + (repr(head[pos_of['net']]) if 'net' in pos_of
                     else repr(head[pos_of['gross']])))
            print(f'  the month as the orders model it: {own:,.0f} booked on '
                  f'its own orders + {came:,.0f} carried in = {model:,.0f} units')
            if sold:
                print(f'  the month as sold, {CUST.ONLINE} only: {sold:,.0f} '
                      f'units  ({model / sold * 100:.0f}% of it modelled)')
                if abs(model - sold) > sold * 0.15:
                    print('  that is a wide gap. The booking rule may not '
                          'describe this export - run py tools\\cohort.py, '
                          'which scores it against the alternatives')
            print(f'  carried on to the month after: {goes:,.0f} units'
                  + (f'  ({goes / sold * 100:.0f}% of the month)' if sold else ''))

    # ── what the filters ended up holding ──────────────────────────────────
    levels = []
    print('\nfilter values:')
    for n, (label, slot, names) in enumerate(FILTERS):
        seen = sorted({k[n] for k in combos})
        levels.append({'name': label, 'values': seen})
        known = {v for m in (cust, prod) for row in m.values()
                 if (v := row.get(slot))} if n else set()
        missing = sorted(known - set(seen))
        src = []
        if from_master[n]:
            src.append(f'{from_master[n]:,} row(s) from the master')
        if from_export[n]:
            col = (head[fallback[n]] if fallback[n] is not None
                   else head[acct_fb] if n == 0 and acct_fb is not None
                   else head[p_key] if slot == 'sku' and p_key is not None
                   else None)
            src.append(f'{from_export[n]:,} from '
                       + (f'{col!r} in the export' if col else 'the export'))
        print(f'  {label}: {len(seen)} value(s)  ({"; ".join(src) or "nothing"})')
        print('    ' + ', '.join(seen[:14]) + (' ...' if len(seen) > 14 else ''))
        if missing:
            print('    not in this export, though the master lists them: '
                  + ', '.join(missing[:10]) + (' ...' if len(missing) > 10 else ''))

    # ── where does one filter value sit? ───────────────────────────────────
    # The page's selects cascade, so a value under a channel or type that is
    # narrowed away is simply not listed - which reads like it is not in the
    # file at all. This says which paths actually carry it.
    if args.where:
        want = args.where.strip().upper()
        print(f'\nwhere {args.where!r} sits:')
        found = False
        for n, lv in enumerate(levels):
            hits = {k[:n]: 0 for k in combos if k[n].strip().upper() == want}
            if not hits:
                continue
            found = True
            for k in combos:
                if k[n].strip().upper() == want:
                    hits[k[:n]] += counts[k]
            total = sum(hits.values())
            print(f'  as a {lv["name"]}: {total:,} row(s) over {len(hits)} path(s)')
            for path, n_rows in sorted(hits.items(), key=lambda kv: -kv[1])[:8]:
                trail = ' / '.join(path) if path else '(top level)'
                print(f'    {trail}: {n_rows:,} row(s)')
            if len(hits) > 8:
                print(f'    ... and {len(hits) - 8} more path(s)')
        if not found:
            print('  no filter level carries it')
        # A value can be perfectly real and still never reach a filter, because
        # it sits in a column no level reads. Name the column rather than leave
        # "not there" to mean two different things.
        wired = {n for _, _, names in FILTERS + [('', '', CUST.ACCOUNT_NAMES)]
                 for n in names}
        for name, (mhead, mrows) in RAW.items():
            for i, h in enumerate(mhead):
                n = sum(1 for r in mrows
                        if i < len(r) and r[i].strip().upper() == want)
                if not n:
                    continue
                read = any(find([h], alias) is not None for alias in wired)
                print(f'  {name} column {h!r}: {n:,} row(s)'
                      + ('' if read else
                         '   <- no filter level reads this column'))

    index = {lv['name']: {v: i for i, v in enumerate(lv['values'])} for lv in levels}
    start = args.start_channel or ''
    if start and start not in levels[0]['values']:
        print(f'\n--start-channel {start!r} is not a channel in the data; opening '
              f'on all of them. Seen: {", ".join(levels[0]["values"])}')
        start = ''
    elif start:
        print(f'\nopens on: {start}  (set Channel to All to bring '
              f'{", ".join(v for v in levels[0]["values"] if v != start)} back in)')

    payload = {
        'title': args.title,
        'file': target.name,
        'rows': len(body),
        'custDepth': CUST_DEPTH,
        'levels': levels,
        'series': series,
        'start': index[levels[0]['name']].get(start, -1) if start else -1,
        # Rounded to whole units: the chart is drawn in millions and the table
        # in whole amounts, so cents would only make the file bigger.
        'combos': [{'k': [index[lv['name']][k[n]] for n, lv in enumerate(levels)],
                    'n': counts[k], 'v': [round(x) for x in v]}
                   for k, v in combos.items()],
    }

    template = (HERE / 'pnl_template.html').read_text(encoding='utf-8')
    html = template.replace('/*__DATA__*/null',
                            json.dumps(payload, ensure_ascii=False,
                                       separators=(',', ':')))
    if not args.cdn:
        f = HERE / 'vendor' / 'chart.umd.js'
        if f.is_file():
            code = f.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
            html = html.replace(
                '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>',
                f'<script>/* chart.umd.js */\n{code}\n</script>')
        else:
            print('vendor/chart.umd.js missing - the page will need a connection')

    out = Path(args.out)
    out.write_text(html, encoding='utf-8')
    print(f'\n-> {out.resolve()}  ({len(html.encode("utf-8")) / 1024:,.0f} KB'
          f'{", needs a connection" if args.cdn else ", works offline"})')
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == '__main__':
    sys.exit(main())

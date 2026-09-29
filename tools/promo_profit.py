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
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_file, pick_latest, read_any)

ROOT = Path(__file__).resolve().parent.parent

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
    ap.add_argument('--orders', default='26 DTC Aug')
    ap.add_argument('--plan', default='MX_product')
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
    op = pick_file(folder, args.orders)
    pl = pick_file(folder, args.plan)
    pf = (pick_file(folder, args.profit) if args.profit
          else pick_latest(folder, 'profit'))
    for what, p in (('order', op), ('plan', pl), ('profit', pf)):
        if p is None:
            print(f'no {what} file in {folder.resolve()}', file=sys.stderr)
            return 2

    print('reading:')
    o_rows, _ = read_any(op)
    p_rows, _ = read_any(pl)
    f_rows, _ = read_any(pf)
    o_head, o_body = [h.strip() for h in o_rows[0]], o_rows[1:]
    p_head, p_body = [h.strip() for h in p_rows[0]], p_rows[1:]
    f_head, f_body = [h.strip() for h in f_rows[0]], f_rows[1:]
    for f, b in ((op, o_body), (pl, p_body), (pf, f_body)):
        print(f'  {f.name}: {len(b):,} rows')

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── the plan, as promo_match builds it ─────────────────────────────────
    P = {k: find(p_head, *PM.NAMES[k]) for k in
         ('sku', 'promo', 'promo2', 'type', 'start', 'end', 'status', 'voucher')}
    P['detail'] = find(p_head, 'Offer_Detail', 'Offer Detail')
    price_cols = [(c, find(p_head, c)) for c in PM.PRICE_COLS]
    price_cols = [(c, i) for c, i in price_cols if i is not None]
    plan_rows = []
    for r in p_body:
        code = PM.code_norm(cell(r, P['sku']))
        if not code or cell(r, P['status']).lower() in PM.DEAD:
            continue
        plan_rows.append({
            'code': code, 'type': cell(r, P['type']),
            'detail': cell(r, P['detail']) or cell(r, P['promo2']),
            'promo': ' / '.join(x for x in (cell(r, P['promo']),
                                            cell(r, P['type'])) if x and x != '-')
                     or '(unnamed plan line)',
            'start': PM.to_date(cell(r, P['start'])),
            'end': PM.to_date(cell(r, P['end'])),
            'vouchers': [PM.code_norm(v)
                         for v in PM.split_rules(cell(r, P['voucher']))],
            'prices': {c: v for c, i in price_cols
                       if (v := parse_number(cell(r, i))) is not None},
        })
    plan = PM.Plan(plan_rows, args.stem)
    print(f'\nplan: {len(plan_rows):,} live line(s) over {len(plan.by_code):,} '
          f'product code(s)')

    # ── completed orders, attributed, rolled up per product ────────────────
    O = {k: find(o_head, *PM.NAMES[k]) for k in
         ('sku', 'date', 'qty', 'amount', 'rule', 'voucher', 'group')}
    O['status'] = find(o_head, 'order_status', 'Order Status', 'Status')
    keep = {s.strip().upper() for s in args.status.split(',') if s.strip()}
    units: dict[str, dict[tuple, float]] = {}
    counted = skipped = 0
    for r in o_body:
        if (cell(r, O['status']).upper() not in keep):
            skipped += 1
            continue
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
        share = units.setdefault(code, {})
        key = (src, kind, detail)
        share[key] = share.get(key, 0.0) + qty
    print(f'orders: {counted:,} line(s) counted, {skipped:,} left out by status '
          f'({", ".join(sorted(keep))})')
    return allocate(args, folder, f_head, f_body, units, cell)


def allocate(args, folder, f_head, f_body, units, cell) -> int:
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
    cp = pick_file(folder, 'customer_2608')
    if cp and F['cust'] is not None and args.online:
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'),
                      {'account': CUST.ACCOUNT_NAMES}, say=lambda *a: None)

    keys = [k for k, _, _ in FIGURES]
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
        v = sku_totals.setdefault(code, [0.0] * len(keys))
        for j, k in enumerate(keys):
            n = parse_number(cell(r, F[k])) if F[k] is not None else None
            if n is not None:
                v[j] += n
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
    unallocated = [0.0] * len(keys)
    for code, totals in sku_totals.items():
        share = units.get(code)
        if not share:
            for j in range(len(keys)):
                unallocated[j] += totals[j]
            continue
        total_units = sum(share.values())
        for key, u in share.items():
            w = (u / total_units) if total_units else 1.0 / len(share)
            agg = out.setdefault(key, [0.0] * (len(keys) + 1))
            for j in range(len(keys)):
                agg[j] += totals[j] * w
            agg[-1] += u                       # the units that earned the share
    if any(unallocated):
        out[('none', '(sold with no completed order)',
             '(sold with no completed order)')] = unallocated + [0.0]

    def table(depth: int, title: str) -> None:
        """One row per offer, whichever source answered for it.

        The source is how the promotion was identified, not a promotion of its
        own, so rolling up by it would list Discount once per source. It is
        reported as which source most of the row came from instead.
        """
        rolled: dict[tuple, list[float]] = {}
        origin: dict[tuple, dict[str, float]] = {}
        for key, v in out.items():
            k = key[1:1 + depth]
            agg = rolled.setdefault(k, [0.0] * len(v))
            for j in range(len(v)):
                agg[j] += v[j]
            seen = origin.setdefault(k, {})
            seen[key[0]] = seen.get(key[0], 0.0) + v[net_i]
        rows = sorted(rolled.items(), key=lambda kv: -kv[1][net_i])
        print(f'\n{title}')
        print(f'  {"":<32}{"units":>9}{"net sales":>13}{"op profit":>13}'
              f'{"margin":>8}{"share":>7}  from')
        tot_net = sum(v[net_i] for _, v in rows) or 1
        for k, v in rows[:args.top]:
            name = ' / '.join(k)
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

    table(1, 'by offer type  (profit allocated by unit share, not measured)')
    table(2, 'by offer detail')

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'promo_profit.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Source', 'Offer type', 'Offer detail', 'Order units']
                   + [label for _, label, _ in FIGURES] + ['Margin %'])
        for key, v in sorted(out.items(), key=lambda kv: -kv[1][net_i]):
            margin = (v[profit_i] / v[net_i] * 100
                      if profit_i is not None and v[net_i] else '')
            w.writerow(list(key) + [round(v[-1], 2)]
                       + [round(v[j], 2) for j in range(len(keys))]
                       + [round(margin, 2) if margin != '' else ''])
    print(f'\n-> {path.resolve()}')
    print('\nthe profit file carries no promotion, so this is each product\'s '
          'profit split by the units its completed orders came in on. It ranks '
          'promotions; it does not measure what a discount cost.')
    if args.html is not None:
        write_page(Path(args.html) if args.html
                   else ROOT / 'dashboard' / 'promo_profit.html',
                   args, out, keys, cov_net / all_net * 100 if all_net else 0.0)
    return 0


def write_page(path: Path, args, out: dict, keys: list, coverage: float) -> None:
    """The allocation as one self-contained page.

    Rolled up to one row per source and offer, which is all the page charts -
    the allocation has no finer grain than that, so nothing is lost by it.
    """
    import json

    sources: dict[str, int] = {}
    types: dict[str, int] = {}
    details: dict[str, int] = {}

    def idx(d, v):
        return d.setdefault(v, len(d))

    rows = []
    for (src, kind, detail), v in out.items():
        rows.append({'s': idx(sources, src),
                     'k': [idx(types, kind), idx(details, detail)],
                     'v': [round(v[j], 2) for j in range(len(keys))]})
    payload = {
        'title': 'August 2026 Promotion profit',
        'orders': args.orders, 'profit': args.profit or 'profit_2608_*',
        'status': args.status,
        'channel': args.account or args.online or 'every channel',
        'coverage': round(coverage, 1),
        'sources': list(sources),
        'levels': [{'name': 'Offer type', 'values': list(types)},
                   {'name': 'Offer detail', 'values': list(details)}],
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

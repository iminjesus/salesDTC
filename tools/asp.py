#!/usr/bin/env python3
"""Average selling price, per SKU and per product grouping.

    py tools\\asp.py                       # -> docs/asp_sku.csv, docs/asp_category.csv
    py tools\\asp.py --by Division Range   # any product levels you want
    py tools\\asp.py --split Channel       # and the same split by customer channel

ASP is net sales over net quantity, taken as one weighted figure per group -
the totals divided, never the average of the rows' own prices, which would let
a single unit weigh as much as a pallet.

Returns are already netted off both sides by the export, so a group whose
returns outweigh its sales can end up with a negative or a zero quantity. Those
are reported rather than divided: a price of "minus four hundred" is not a
price, and an infinity in a spreadsheet is worse.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_file, pick_latest, read_any)

ROOT = Path(__file__).resolve().parent.parent

# What ASP is made of. Net first: that is the price actually realised.
QTY_NET = ('Quantity(Net)', 'Net Sales Qty', 'Qty', 'Quantity')
QTY_GROSS = ('Quantity(Gross)', 'Gross Qty')
AMT_NET = ('*Net Sales', 'Net Sales', 'Net Sales Amt')
AMT_GROSS = ('*S.Gross Sales', '*Gross Sales', 'Gross Sales', 'S.Gross Sales AMT')

PRODUCT_COLS = {
    'division': ('Division',),
    'category': ('Category',),
    'range':    ('Range', 'product_range'),
    'series':   ('Series',),
    'desc':     ('Description', 'description'),
}
PRODUCT_KEYS = ('Material', 'SKU', 'Material Code', 'Product Number', 'Model',
                'Model Code', 'Material No', 'Item', 'Product', 'Product Code')
CUSTOMER_KEYS = ('Payer', 'sold To', 'Sold-To', 'Customer', 'Customer Code',
                 'Payer Code', 'Sold To Party')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--file', default=None,
                    help='the export to read (default: the highest-numbered '
                         'profit_* file)')
    ap.add_argument('--by', nargs='*', default=['Category'], metavar='LEVEL',
                    help='product levels to group by, each written to its own '
                         'csv: Division, Category, Range, Series (default: Category)')
    ap.add_argument('--split', nargs='*', default=[], metavar='DIM',
                    help='also break every grouping down by these: Channel, '
                         'Type, Portal Group, Type2')
    ap.add_argument('--out', default=str(ROOT / 'docs'),
                    help='folder for the csvs (default: docs/)')
    ap.add_argument('--top', type=int, default=15, help='rows to print per group')
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

    q_net, a_net = find(head, *QTY_NET), find(head, *AMT_NET)
    q_gross, a_gross = find(head, *QTY_GROSS), find(head, *AMT_GROSS)
    print('\ncolumns:')
    for what, i in (('net quantity', q_net), ('net sales', a_net),
                    ('gross quantity', q_gross), ('gross sales', a_gross)):
        print(f'  {what:15} {head[i] if i is not None else "-- not found --"}')
    if q_net is None or a_net is None:
        print('\nASP needs a net quantity and a net sales column.', file=sys.stderr)
        print('Headers seen:', ', '.join(head[:40]), file=sys.stderr)
        return 1
    gross_ok = q_gross is not None and a_gross is not None

    p_key = find(head, *PRODUCT_KEYS)
    c_key = find(head, *CUSTOMER_KEYS)
    print(f'  {"product key":15} '
          f'{head[p_key] if p_key is not None else "-- not found --"}')

    prod = {}
    pp = pick_latest(folder, 'product')
    if pp:
        prod = master(pp, PRODUCT_KEYS, PRODUCT_COLS)
        print(f'\nproduct master: {len(prod):,} products')
    cust = {}
    if args.split:
        cp = pick_latest(folder, 'customer')
        if cp:
            want = {slot: names for _, slot, names in CUST.LEVELS if names}
            want['account'] = CUST.ACCOUNT_NAMES
            cust = master(cp, ('Sold-To', 'sold To', 'sold_to'), want)
            print(f'customer master: {len(cust):,} accounts')

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── one pass, accumulating totals per SKU ──────────────────────────────
    slot_of = {lbl: slot for lbl, slot, _ in CUST.LEVELS}
    split_slots = []
    for name in args.split:
        slot = slot_of.get(name) or slot_of.get(name.title())
        if slot is None:
            print(f'\nno such customer level: {name!r}. '
                  f'Known: {", ".join(slot_of)}', file=sys.stderr)
            return 2
        split_slots.append((name, slot))

    sku_rows: dict[tuple, list[float]] = {}
    matched = 0
    for r in body:
        sku = cell(r, p_key)
        p = prod.get(key_norm(sku)) or {}
        matched += bool(p)
        c = cust.get(key_norm(cell(r, c_key))) or {} if cust else {}
        split = tuple(
            (CUST.channel_of(c.get('account'), bool(c)) if slot == 'channel'
             else c.get(slot) or CUST.BLANK)
            for _, slot in split_slots)
        key = (sku or '(blank)',
               p.get('division') or '(blank)', p.get('category') or '(blank)',
               p.get('range') or '(blank)', p.get('series') or '(blank)',
               p.get('desc') or '') + split
        v = sku_rows.get(key)
        if v is None:
            v = sku_rows[key] = [0.0, 0.0, 0.0, 0.0, 0.0]
        v[4] += 1
        for j, i in enumerate((q_net, a_net, q_gross, a_gross)):
            n = parse_number(cell(r, i)) if i is not None else None
            if n is not None:
                v[j] += n
    print(f'\n{matched:,} of {len(body):,} rows matched a product; '
          f'{len(sku_rows):,} SKU rows')
    if not matched and prod:
        keyed = ', '.join(repr(k) for k in list(prod)[:4])
        if p_key is None:
            print('  the export has no column this build recognises as a product '
                  f'key, so nothing could match. product_2608 is keyed on {keyed}')
            print('  columns in the export: ' + ', '.join(head[:30])
                  + (' ...' if len(head) > 30 else ''))
        else:
            theirs = [key_norm(cell(r, p_key)) for r in body[:2000] if cell(r, p_key)]
            print(f'  {head[p_key]!r} holds e.g. '
                  + ', '.join(repr(k) for k in theirs[:4])
                  + f'; product_2608 is keyed on {keyed}. Every grouping below '
                  'will read (blank).')

    LEVELS = ['SKU', 'Division', 'Category', 'Range', 'Series']
    SPLIT_AT = len(LEVELS) + 1          # description sits between them

    def group_by(level: str) -> dict:
        """Totals for one product level, keeping any customer split."""
        out: dict[tuple, list[float]] = {}
        at = LEVELS.index(level)
        for k, v in sku_rows.items():
            name = (k[0], k[SPLIT_AT - 1]) if at == 0 else (k[at],)
            g = out.setdefault(name + k[SPLIT_AT:], [0.0, 0.0, 0.0, 0.0, 0.0])
            for j in range(5):
                g[j] += v[j]
        return out

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    wanted = ['SKU'] + [b.title() if b.lower() in
                        {'division', 'category', 'range', 'series'} else b
                        for b in args.by]
    for level in dict.fromkeys(wanted):
        if level not in LEVELS:
            print(f'\nno such product level: {level!r}. '
                  f'Known: {", ".join(LEVELS[1:])}', file=sys.stderr)
            return 2
        data = group_by(level)
        cols = ([level, 'Description'] if level == 'SKU' else [level]) \
            + [n for n, _ in split_slots] \
            + ['Rows', 'Qty (net)', 'Net Sales', 'ASP'] \
            + (['Qty (gross)', 'Gross Sales', 'ASP (gross)'] if gross_ok else [])
        table = []
        odd = 0
        for name, v in data.items():
            qn, an, qg, ag, n = v
            asp = an / qn if qn else None
            odd += asp is None
            row = list(name) + [int(n), round(qn, 2), round(an, 2),
                                round(asp, 2) if asp is not None else '']
            if gross_ok:
                row += [round(qg, 2), round(ag, 2),
                        round(ag / qg, 2) if qg else '']
            table.append((row, asp if asp is not None else float('-inf'), an))
        table.sort(key=lambda t: -t[2])          # biggest sellers first
        path = outdir / f'asp_{level.lower()}.csv'
        with path.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(row for row, _, _ in table)
        print(f'\n{level}: {len(table):,} group(s) -> {path}')
        if odd:
            print(f'  {odd:,} of them have no net quantity to divide by '
                  '(returns cancelling sales, or a sale booked with no units); '
                  'their ASP is left blank')
        # The name of a group is every column before the figures - with a split
        # that is more than one, and printing only the first would put two
        # different groups on screen under the same name.
        n_names = len(cols) - (7 if gross_ok else 4)
        shown = [(' / '.join(str(x) for x in row[:n_names] if str(x)), row)
                 for row, _, _ in table[:args.top]]
        wide = min(48, max((len(n) for n, _ in shown), default=8))
        print(f'  {"":<{wide}} {"Qty":>12} {"Net Sales":>16} {"ASP":>12}')
        for name, row in shown:
            print(f'  {name[:48]:<{wide}} {row[n_names + 1]:>12,.0f} '
                  f'{row[n_names + 2]:>16,.0f} '
                  + (f'{row[n_names + 3]:>12,.2f}' if row[n_names + 3] != ''
                     else f'{"-":>12}'))
    return 0


if __name__ == '__main__':
    sys.exit(main())

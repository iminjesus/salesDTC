#!/usr/bin/env python3
"""Build the August profit dashboard from the files in rawdata/.

    py dashboard\\build_dashboard.py
    py dashboard\\build_dashboard.py --open        # and open it in the browser

Reads profit_2608_1, customer_2608 and product_2608 (any of the formats
tools/rawdata.py handles), joins the two masters onto the profit rows, rolls the
result up to the finest combination the two hierarchies need, and writes a single
self-contained HTML file. No server, no database, and the data never leaves the
machine - it is embedded in the page.

Columns are found by header name rather than position, and the script prints what
it matched, so a renamed export shows up as a missing measure instead of a wrong
number.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
from rawdata import read_any                                   # noqa: E402

HERE = Path(__file__).resolve().parent


def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def find(headers: list[str], *candidates: str) -> int | None:
    """Index of the first header matching one of the candidates."""
    lookup = {norm(h): i for i, h in enumerate(headers)}
    for c in candidates:
        if norm(c) in lookup:
            return lookup[norm(c)]
    return None


def to_num(v: str) -> float:
    t = str(v or '').strip().replace(',', '').replace('$', '')
    if not t or t in ('-', '#N/A', 'N/A'):
        return 0.0
    if t.startswith('(') and t.endswith(')'):
        t = '-' + t[1:-1]
    try:
        return float(t)
    except ValueError:
        return 0.0


def load(path: Path) -> tuple[list[str], list[list[str]]]:
    rows, info = read_any(path)
    if not rows:
        raise SystemExit(f'{path.name} is empty')
    print(f"  {path.name}: {info['format']}, {info['encoding']}, "
          f"{len(rows) - 1:,} rows")
    return [h.strip() for h in rows[0]], rows[1:]


def pick_file(folder: Path, *stems: str) -> Path:
    for stem in stems:
        hits = sorted(p for p in folder.iterdir()
                      if p.is_file() and norm(p.stem) == norm(stem))
        if hits:
            return hits[0]
    for stem in stems:                              # prefix match, e.g. profit_2608_1x
        hits = sorted(p for p in folder.iterdir()
                      if p.is_file() and norm(p.stem).startswith(norm(stem)))
        if hits:
            return hits[0]
    raise SystemExit(f'none of {stems} found in {folder.resolve()}')


# ── the measures the chart needs, and the headers they may arrive under ─────
MEASURES = {
    'gross':  ('*S.Gross Sales', 'S.Gross Sales AMT', 'Gross Sales', 'Gross'),
    'sd':     ('*Sales Deduction', 'Sales Deduction', 'S.Sales Deduction'),
    'cogs':   ('*Cost of Goods Sold', 'Cost of Goods Sold', 'COGS'),
    'opex':   ('*Operating Expense', 'Operating Expense', 'Op Cost', 'OPEX'),
    'profit': ('*Operating Profit', 'Operating Profit', 'Op Profit U$', 'Profit'),
}

# Dimension columns taken off the profit file itself.
PROFIT_DIMS = {
    'sold_to':        ('sold To', 'Sold-To', 'sold_to', 'Customer'),
    'sku':            ('SKU', 'Material', 'Material Code'),
    'material_group': ('Material Group', 'material_group'),
    'division2':      ('Division 2', 'division2'),
    'prod_group':     ('Prod_group', 'Prod Group', 'prod_group'),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata', help='folder holding the files')
    ap.add_argument('--out', default=str(HERE / 'profit_2608.html'))
    ap.add_argument('--title', default='August 2026 Profit')
    ap.add_argument('--period', help='keep only this period/month, e.g. 2026.008 or Aug')
    ap.add_argument('--open', action='store_true', help='open the result')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    print('reading:')
    p_head, p_rows = load(pick_file(folder, 'profit_2608_1', 'profit_2608'))
    c_head, c_rows = load(pick_file(folder, 'customer_2608'))
    d_head, d_rows = load(pick_file(folder, 'product_2608'))

    # ── locate the measures ────────────────────────────────────────────────
    m_idx = {k: find(p_head, *names) for k, names in MEASURES.items()}
    print('\nmeasures:')
    for k, i in m_idx.items():
        print(f'  {k:7} {p_head[i] if i is not None else "-- not found --"}')
    if m_idx['gross'] is None and m_idx['profit'] is None:
        print('\nNeither a gross sales nor an operating profit column was found.',
              file=sys.stderr)
        print('Headers seen:', ', '.join(p_head[:40]), file=sys.stderr)
        return 1

    d_idx = {k: find(p_head, *names) for k, names in PROFIT_DIMS.items()}

    # The file is named for one month, but say so out loud if it holds several -
    # otherwise a mixed export would quietly be reported as August.
    per_i = find(p_head, 'Period', 'Month', 'Fiscal Period')
    if per_i is not None:
        periods = sorted({(r[per_i].strip() if per_i < len(r) else '') for r in p_rows} - {''})
        if args.period:
            p_rows = [r for r in p_rows
                      if per_i < len(r) and r[per_i].strip() == args.period]
            print(f'\nperiod: kept {len(p_rows):,} rows for {args.period}')
        elif len(periods) > 1:
            print(f'\nWARNING: {p_head[per_i]} holds {len(periods)} values '
                  f'({", ".join(periods[:8])}{"..." if len(periods) > 8 else ""}).')
            print('         All of them are being charted together. Use --period to '
                  'pick one.')
        elif periods:
            print(f'\nperiod: {periods[0]}')

    # ── masters ────────────────────────────────────────────────────────────
    c_key = find(c_head, 'Sold-To', 'sold To', 'sold_to')
    cust = {}
    if c_key is not None:
        cols = {k: find(c_head, *v) for k, v in {
            'account':  ('Account Name', 'account_name'),
            'account_desc': ('Description', 'description'),
            'cust_type': ('Type', 'customer_type'),
            'portal':   ('Portal Group', 'portal_group'),
            'neilson':  ('Neilson Type', 'neilson_type'),
        }.items()}
        for r in c_rows:
            key = (r[c_key] if c_key < len(r) else '').strip()
            if key:
                cust[key] = {k: (r[i].strip() if i is not None and i < len(r) else '')
                             for k, i in cols.items()}

    d_key = find(d_head, 'SKU', 'sku')
    prod = {}
    if d_key is not None:
        cols = {k: find(d_head, *v) for k, v in {
            'division': ('Division', 'division'),
            'category': ('Category', 'category'),
            'range':    ('Range', 'product_range'),
            'series':   ('Series', 'series'),
            'prod_desc': ('Description', 'description'),
        }.items()}
        for r in d_rows:
            key = (r[d_key] if d_key < len(r) else '').strip()
            if key:
                prod[key] = {k: (r[i].strip() if i is not None and i < len(r) else '')
                             for k, i in cols.items()}

    # ── roll up ────────────────────────────────────────────────────────────
    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    buckets: dict[tuple, list[float]] = {}
    matched_cust = matched_prod = 0
    for r in p_rows:
        sold_to = cell(r, d_idx['sold_to'])
        sku = cell(r, d_idx['sku'])
        c = cust.get(sold_to)
        p = prod.get(sku)
        matched_cust += bool(c)
        matched_prod += bool(p)
        c = c or {}
        p = p or {}
        key = (
            c.get('cust_type') or cell(r, d_idx['division2']) or 'Unknown',
            c.get('portal') or 'Unknown',
            c.get('account_desc') or c.get('account') or sold_to or 'Unknown',
            p.get('division') or cell(r, d_idx['division2']) or 'Unknown',
            p.get('category') or cell(r, d_idx['prod_group']) or 'Unknown',
            p.get('range') or cell(r, d_idx['material_group']) or 'Unknown',
            p.get('prod_desc') or sku or cell(r, d_idx['material_group']) or 'Unknown',
        )
        vals = buckets.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
        for j, m in enumerate(('gross', 'sd', 'cogs', 'opex', 'profit')):
            i = m_idx[m]
            if i is not None:
                vals[j] += to_num(cell(r, i))

    print(f'\njoined: {matched_cust:,} of {len(p_rows):,} rows matched a customer, '
          f'{matched_prod:,} matched a product')
    if not matched_cust and cust:
        print('  (no customer matched - check that the profit file carries Sold-To)')

    records = [{'c': list(k[:3]), 'p': list(k[3:]),
                'g': round(v[0], 2), 's': round(v[1], 2), 'o': round(v[2], 2),
                'x': round(v[3], 2), 'f': round(v[4], 2)}
               for k, v in buckets.items()]
    # If the file has no operating-profit column, derive it.
    if m_idx['profit'] is None:
        for rec in records:
            rec['f'] = round(rec['g'] - rec['s'] - rec['o'] - rec['x'], 2)

    payload = {
        'title': args.title,
        'levels': {
            'customer': ['Type', 'Portal Group', 'Account'],
            'product': ['Division', 'Category', 'Range', 'Product'],
        },
        'records': records,
    }
    template = (HERE / 'template.html').read_text(encoding='utf-8')
    html = template.replace('/*__DATA__*/null',
                            json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    out = Path(args.out)
    out.write_text(html, encoding='utf-8')
    total = sum(r['f'] for r in records)
    print(f'\n{len(records):,} aggregated rows, operating profit {total:,.0f}')
    print(f'-> {out.resolve()}')
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == '__main__':
    sys.exit(main())

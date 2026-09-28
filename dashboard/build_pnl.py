#!/usr/bin/env python3
"""Draw the P&L as a bar chart you can drill, from the structure analysis.

    py dashboard\\build_pnl.py                 # -> dashboard/pnl_2608.html
    py dashboard\\build_pnl.py --open

tools/analyze_structure.py works out which figures are sums of which. This turns
that into one self-contained page: the bars are the lines a total is made of,
clicking one opens its own lines, and the filter row narrows every figure to a
slice of the business without recomputing anything.

The numbers are embedded, so the file works with no server, no database and no
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
from rawdata import parse_number, pick_file, pick_latest, read_any  # noqa: E402
import analyze_structure as A                                  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def find(headers: list[str], *candidates: str) -> int | None:
    lookup = {re.sub(r'[^a-z0-9]', '', h.lower()): i for i, h in enumerate(headers)}
    for c in candidates:
        key = re.sub(r'[^a-z0-9]', '', c.lower())
        if key in lookup:
            return lookup[key]
    return None


def key_norm(v: str) -> str:
    """Match keys across exports that disagree about padding and case."""
    t = str(v or '').strip().upper()
    if t.endswith('.0') and t[:-2].isdigit():
        t = t[:-2]
    if t.isdigit():
        t = t.lstrip('0') or '0'
    return t


def master(path: Path, key_names: tuple, wanted: dict) -> dict:
    rows, _ = read_any(path)
    head = [h.strip() for h in rows[0]]
    k = find(head, *key_names)
    if k is None:
        return {}
    cols = {slot: find(head, *names) for slot, names in wanted.items()}
    out = {}
    for r in rows[1:]:
        key = key_norm(r[k] if k < len(r) else '')
        if key:
            out[key] = {s: (r[i].strip() if i is not None and i < len(r) else '')
                        for s, i in cols.items()}
    return out


# The four things the filter row narrows by: two from the customer master, two
# from the product master, each falling back to a column of the export itself.
FILTERS = [
    ('Account Name', 'account', ('Cus_group', 'Customer Group')),
    ('Type',         'type',    ('Type', 'Record Type')),
    ('Division',     'division', ('Division', 'Division 2')),
    ('Category',     'category', ('Prod_group', 'Product Group', 'Category')),
]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--file', default=None,
                    help='the export to draw (default: the highest-numbered '
                         'profit_* file in the folder)')
    ap.add_argument('--out', default=str(HERE / 'pnl_2608.html'))
    ap.add_argument('--title', default='August 2026 P&L')
    ap.add_argument('--structure', default=str(ROOT / 'docs' / 'structure.json'),
                    help='the analysis to draw; recomputed if it does not match')
    ap.add_argument('--cdn', action='store_true',
                    help='link Chart.js instead of embedding it: a smaller file '
                         'that then needs a connection')
    ap.add_argument('--find', metavar='VALUE',
                    help='say where one code appears - which column of the export '
                         'holds it and what the masters have for it')
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

    cols = A.column_profile(head, body)
    measures = [c['pos'] for c in cols if A.is_measure(c, len(body))]
    print(f'  {len(measures)} amount column(s)')

    # ── the structure: reuse the analysis if it is the one for this file ────
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

    # ── dimensions ──────────────────────────────────────────────────────────
    cust = prod = {}
    cp = pick_file(folder, 'customer_2608')
    if cp:
        cust = master(cp, ('Sold-To', 'sold To', 'sold_to'),
                      {'account': ('Account Name', 'account_name'),
                       'type': ('Type', 'customer_type')})
        print(f'  customer master: {len(cust):,} accounts')
    pp = pick_file(folder, 'product_2608')
    if pp:
        prod = master(pp, ('SKU', 'sku', 'Material'),
                      {'division': ('Division',), 'category': ('Category',)})
        print(f'  product master: {len(prod):,} products')

    c_key = find(head, 'Payer', 'sold To', 'Sold-To', 'Customer')
    p_key = find(head, 'Material', 'SKU', 'Material Code')
    fallback = [find(head, *names) for _, _, names in FILTERS]

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

    # ── roll up: one row per combination of the four filter values ─────────
    slot_of = {pos: n for n, pos in enumerate(measures)}
    combos: dict[tuple, list[float]] = {}
    counts: dict[tuple, int] = {}
    matched_c = matched_p = 0
    # Where each filter value came from. A value that quietly fell back to a
    # column of the export itself is the reason a name from the master can go
    # missing from the filter without anything looking wrong.
    from_master = [0] * len(FILTERS)
    from_export = [0] * len(FILTERS)
    for r in body:
        c = cust.get(key_norm(cell(r, c_key))) or {}
        p = prod.get(key_norm(cell(r, p_key))) or {}
        matched_c += bool(c)
        matched_p += bool(p)
        src = {**c, **p}
        key = []
        for n, ((_, slot, _), fb) in enumerate(zip(FILTERS, fallback)):
            v = src.get(slot)
            if v:
                from_master[n] += 1
            else:
                v = cell(r, fb)
                from_export[n] += bool(v)
            key.append(v or '(blank)')
        key = tuple(key)
        vals = combos.get(key)
        if vals is None:
            vals = combos[key] = [0.0] * len(measures)
        counts[key] = counts.get(key, 0) + 1
        for pos in measures:
            n = parse_number(cell(r, pos))
            if n is not None:
                vals[slot_of[pos]] += n
    print(f'\njoined: {matched_c:,} of {len(body):,} rows matched a customer, '
          f'{matched_p:,} matched a product')
    print(f'{len(combos):,} filter combination(s)')

    # ── what the filters ended up holding ──────────────────────────────────
    # "Is EPP really not there?" is two different questions - whether the master
    # knows the name, and whether any row in this export carries it - so both
    # are answered here.
    print('\nfilter values:')
    for n, (label, slot, names) in enumerate(FILTERS):
        seen = sorted({k[n] for k in combos})
        known = {v for m in (cust, prod) for row in m.values()
                 if (v := row.get(slot))}
        missing = sorted(known - set(seen))
        src = []
        if from_master[n]:
            src.append(f'{from_master[n]:,} row(s) from the master')
        if from_export[n]:
            src.append(f'{from_export[n]:,} from {head[fallback[n]]!r} in the export'
                       if fallback[n] is not None else
                       f'{from_export[n]:,} from the export')
        print(f'  {label}: {len(seen)} value(s)  ({"; ".join(src) or "nothing"})')
        print('    ' + ', '.join(seen[:14]) + (' ...' if len(seen) > 14 else ''))
        if missing:
            print(f'    not in this export, though the master lists them: '
                  + ', '.join(missing[:10])
                  + (' ...' if len(missing) > 10 else ''))

    # ── payload ────────────────────────────────────────────────────────────
    levels = []
    for n, (label, _, _) in enumerate(FILTERS):
        seen = sorted({k[n] for k in combos})
        levels.append({'name': label, 'values': seen})
    index = {lv['name']: {v: i for i, v in enumerate(lv['values'])} for lv in levels}

    node_map = {}
    for nd in nodes:
        if nd['pos'] in slot_of and all(k in slot_of for k in nd['children']):
            node_map[slot_of[nd['pos']]] = {
                'k': [slot_of[k] for k in nd['children']], 's': nd['signs']}
    claimed = {k for v in node_map.values() for k in v['k']}

    def reach(slot: int, seen=None) -> int:
        seen = seen if seen is not None else set()
        for k in (node_map.get(slot) or {'k': ()})['k']:
            if k not in seen:
                seen.add(k)
                reach(k, seen)
        return len(seen)

    # The page opens on the fullest tree - the bottom line rather than whichever
    # subtotal happens to sit leftmost in the export.
    roots = sorted((s for s in node_map if s not in claimed),
                   key=lambda s: (-reach(s), -abs(cols[measures[s]]['total'] or 0)))
    if not roots:
        roots = sorted(range(len(measures)),
                       key=lambda s: -abs(cols[measures[s]]['total'] or 0))[:12]

    payload = {
        'title': args.title,
        'file': target.name,
        'rows': len(body),
        'measures': [cols[p]['header'] for p in measures],
        'nodes': node_map,
        'roots': roots,
        'levels': levels,
        'combos': [{'k': [index[lv['name']][k[n]] for n, lv in enumerate(levels)],
                    'n': counts[k],
                    'v': [round(x, 2) for x in v]}
                   for k, v in combos.items()],
    }

    template = (HERE / 'pnl_template.html').read_text(encoding='utf-8')
    html = template.replace('/*__DATA__*/null',
                            json.dumps(payload, ensure_ascii=False,
                                       separators=(',', ':')))
    if not args.cdn:
        vendor = HERE / 'vendor'
        libs = [('https://cdn.jsdelivr.net/npm/chart.js@4', 'chart.umd.js')]
        for url, name in libs:
            f = vendor / name
            if f.is_file():
                code = f.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
                html = html.replace(f'<script src="{url}"></script>',
                                    f'<script>/* {name} */\n{code}\n</script>')
            else:
                print(f'vendor/{name} missing - the page will need a connection')

    out = Path(args.out)
    out.write_text(html, encoding='utf-8')
    print(f'\n{len(roots)} headline figure(s): '
          + ', '.join(payload['measures'][s] for s in roots[:6])
          + (' ...' if len(roots) > 6 else ''))
    print(f'-> {out.resolve()}  ({len(html.encode("utf-8")) / 1024:,.0f} KB'
          f'{", needs a connection" if args.cdn else ", works offline"})')
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == '__main__':
    sys.exit(main())

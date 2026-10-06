#!/usr/bin/env python3
"""Average selling price over several months, as two Excel workbooks.

    py tools\\asp_xlsx.py --months 2607 2608 2609

Writes exactly two files:

    Material.xlsx     every material, all channels
    Online ASP.xlsx   every material, the online channel only

ASP is **net sales over net quantity**, and over a span it is the span's totals
divided - not the average of each month's own ASP. Three monthly prices
averaged flat would let a month that sold forty units weigh as much as one that
sold four thousand, which is how a quiet month comes to set the price of a busy
one. The monthly columns are there to be read; the ASP column is weighted.

Returns are netted off both sides by the export, so a material whose returns
outweigh its sales can end up at zero or below. Those are left blank and
counted rather than divided: a price of minus four hundred is not a price, and
a division by zero in a spreadsheet is worse than a gap.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from asp import (AMT_NET, CUSTOMER_KEYS, PRODUCT_COLS,         # noqa: E402
                 PRODUCT_KEYS, QTY_NET)
import xlsx as XL                                            # noqa: E402
from rawdata import (find, key_norm, master, parse_number,     # noqa: E402
                     pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def month_label(yymm: str) -> str:
    """2607 -> Jul 2026."""
    s = ''.join(ch for ch in yymm if ch.isdigit())[-4:]
    if len(s) != 4:
        return yymm
    y, m = int(s[:2]), int(s[2:])
    return f'{MONTHS[m - 1]} 20{y:02d}' if 1 <= m <= 12 else yymm


def cell(r, i):
    return (r[i].strip() if i is not None and i < len(r) else '')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--months', nargs='+', default=['2607', '2608', '2609'],
                    metavar='YYMM', help='the months to read (default: '
                                         '2607 2608 2609)')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME',
                    help=f'which channel the second workbook keeps '
                         f'(default: {CUST.ONLINE})')
    ap.add_argument('--out', default=str(ROOT / 'docs'),
                    help='where the two workbooks go (default: docs/)')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    # One export per month asked for, by the digits in its name.
    want = []
    for ym in args.months:
        digits = ''.join(ch for ch in ym if ch.isdigit())[-4:]
        hit = [p for p in pick_series(folder, 'profit')
               if digits in ''.join(ch for ch in p.stem if ch.isdigit())]
        if not hit:
            print(f'no profit export for {ym} in {folder.resolve()}',
                  file=sys.stderr)
            return 2
        want.append((digits, hit[0]))

    def read_master(prefix, keys, want):
        """The first candidate that can actually be read.

        One unreadable workbook used to end a whole run after all the reading
        was done, so a master that will not open is reported and the next
        spelling of it is tried instead.
        """
        for cand in pick_series(folder, prefix):
            try:
                got = master(cand, keys, want, say=lambda *a: None)
            except (ValueError, OSError, IndexError, KeyError) as e:
                print(f'  {cand.name}: {e} - trying the next one')
                continue
            if got:
                return cand, got
        return None, {}

    pp, prod = read_master('product', PRODUCT_KEYS, PRODUCT_COLS)
    print(f'product master: {pp.name}, {len(prod):,} material(s)' if pp
          else 'no product master could be read - the description, division, '
               'category and range columns will be blank')
    wantc = {slot: names for _, slot, names in CUST.LEVELS if names}
    wantc['account'] = CUST.ACCOUNT_NAMES
    cp, cust = read_master('customer', ('Sold-To', 'sold To', 'sold_to'), wantc)
    print(f'customer master: {cp.name}, {len(cust):,} account(s)' if cp
          else 'no customer master could be read - without it no row can be '
               'placed in a channel, so "Online ASP" would come out empty')
    if not cust:
        print('  stopping rather than writing an empty Online ASP workbook',
              file=sys.stderr)
        return 1

    # material -> {'qty': {month: n}, 'amt': {month: n}, 'on_qty': .., 'on_amt': ..}
    rows: dict[str, dict] = {}
    print('\nreading:')
    for digits, path in want:
        raw, info = read_any(path)
        head = [h.strip() for h in raw[0]]
        q_i, a_i = find(head, *QTY_NET), find(head, *AMT_NET)
        p_i, c_i = find(head, *PRODUCT_KEYS), find(head, *CUSTOMER_KEYS)
        print(f'  {path.name}: {info["format"]}, {len(raw) - 1:,} rows')
        if q_i is None or a_i is None or p_i is None:
            print('    needs a net quantity, a net sales and a product column'
                  ' - skipped', file=sys.stderr)
            return 1
        for r in raw[1:]:
            sku = cell(r, p_i)
            if not sku:
                continue
            v = rows.setdefault(sku, {'qty': {}, 'amt': {},
                                      'on_qty': {}, 'on_amt': {}})
            q = parse_number(cell(r, q_i)) or 0.0
            a = parse_number(cell(r, a_i)) or 0.0
            v['qty'][digits] = v['qty'].get(digits, 0.0) + q
            v['amt'][digits] = v['amt'].get(digits, 0.0) + a
            c = cust.get(key_norm(cell(r, c_i))) or {}
            if CUST.channel_of(c.get('account'), bool(c)) == args.channel:
                v['on_qty'][digits] = v['on_qty'].get(digits, 0.0) + q
                v['on_amt'][digits] = v['on_amt'].get(digits, 0.0) + a

    if not rows:
        print('\nnothing to write.', file=sys.stderr)
        return 1

    months = [d for d, _ in want]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for name, qk, ak in (('Material', 'qty', 'amt'),
                         ('Online ASP', 'on_qty', 'on_amt')):
        path = out / f'{name}.xlsx'
        n, blank, q, a = write_book(path, name, rows, months, qk, ak, prod, args)
        made.append((path, n, blank, q, a))

    print()
    for path, n, blank, q, a in made:
        print(f'-> {path.name}  {n:,} material code(s), {q:,.0f} net unit(s), '
              f'{a:,.0f} net sales'
              + (f', {blank:,} with no price' if blank else ''))
        print(f'   {path.resolve()}')
    return 0


def write_book(path, title, rows, months, qk, ak, prod, args):
    """One workbook: a row per material code, the months beside, ASP weighted."""
    span = f'{month_label(months[0])} - {month_label(months[-1])}'
    head = ['Material code', 'Description', 'Division', 'Category', 'Range']
    for m in months:
        head += [f'{month_label(m)} qty', f'{month_label(m)} net sales']
    head += [f'{span} qty', f'{span} net sales', f'ASP ({span})']

    body = []
    for sku, v in rows.items():
        q = sum(v[qk].get(m, 0.0) for m in months)
        a = sum(v[ak].get(m, 0.0) for m in months)
        if not q and not a:
            continue                   # this material is not in this workbook
        body.append((sku, prod.get(key_norm(sku)) or {}, v, q, a))
    # Biggest first, so the sheet opens on what matters. Sorted here because a
    # spreadsheet cannot sort itself without a volatile array formula.
    body.sort(key=lambda t: -abs(t[4]))

    n_m = len(months)
    # The month columns, named one by one. A SUMPRODUCT over every other column
    # would do the same and nobody opening the sheet could check it; =F2+H2+J2
    # is read at a glance and is right or wrong on sight.
    q_cells = [XL.col_letter(6 + 2 * k) for k in range(n_m)]
    a_cells = [XL.col_letter(7 + 2 * k) for k in range(n_m)]
    qcol, acol = XL.col_letter(6 + 2 * n_m), XL.col_letter(7 + 2 * n_m)

    out, blank, tot_q, tot_a = [head], 0, 0.0, 0.0
    for i, (sku, p, v, q, a) in enumerate(body, start=2):
        r = [sku, p.get('desc', ''), p.get('division', ''),
             p.get('category', ''), p.get('range', '')]
        for m in months:
            r += [v[qk].get(m, 0.0), v[ak].get(m, 0.0)]
        # The span totals and the ASP are formulas, not numbers I worked out:
        # edit or delete a month's column and the sheet still adds up.
        r += [XL.Formula('+'.join(f'{c}{i}' for c in q_cells), q),
              XL.Formula('+'.join(f'{c}{i}' for c in a_cells), a),
              # Weighted over the span, and blank rather than wrong where the
              # returns outweigh the sales - minus four hundred is not a price.
              XL.Formula(f'IF({qcol}{i}>0,{acol}{i}/{qcol}{i},"")',
                         round(a / q, 2) if q > 0 else '')]
        out.append(r)
        tot_q += q
        tot_a += a
        if q <= 0:
            blank += 1

    out.append([])
    out.append([f'{title}: ASP is net sales over net quantity for {span} taken '
                'together - the span\'s totals divided, not the average of the '
                'three months\' own prices, which would let a quiet month weigh '
                'as much as a busy one. A material code whose returns outweigh '
                'its sales has no price and is left blank.'])
    out.append(['Source: ' + ', '.join(month_label(m) for m in months)
                + ' profit exports'
                + ('' if title == 'Material' else f'; {args.channel} only')
                + f'. {len(body):,} material code(s), {tot_q:,.0f} net unit(s), '
                + f'{tot_a:,.0f} net sales.'])

    styles = [XL.PLAIN] * 5 + [XL.INT] * (2 * n_m) + [XL.INT, XL.INT, XL.MONEY]
    widths = [16, 30, 12, 16, 16] + [14] * (2 * n_m) + [14, 16, 14]
    XL.write(path, 'ASP', out, widths=widths, styles=styles, freeze='B2')
    return len(body), blank, tot_q, tot_a


if __name__ == '__main__':
    sys.exit(main())

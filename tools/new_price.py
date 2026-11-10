#!/usr/bin/env python3
"""Write the re-priced month into the GSCM sheet as one more column.

    py tools\\new_price.py
    py tools\\new_price.py --month 2610 --back 6
    py tools\\new_price.py --out rawdata\\GSCM_Oct_new.xlsx

The dashboard already draws a re-priced price beside the planned one: what the
month could have been planned at, from the promotion plan's list price and the
discount the same campaign has been selling at over the months behind it. The
card shows it; this writes the same number into the sheet, so the rest can be
done in Excel.

It is the **same** number, from the same call `dashboard/build_pnl.py` makes -
`tools/reprice.py` reading `rawdata` - so the column and the card cannot
disagree. `docs/REPRICE.md` has the method.

One column and nothing else: the predicted price. Nothing about actuals is
written, because a SUMIFS against the order export does that better than a
pasted number can - this is the one figure the sheet cannot work out for
itself.

It goes straight after `<Mon> Price(AUD)`, the price it is there to be
compared with, and every other column keeps its contents and its order. The
sheet is one row per material **per account** - E-STORE, E-STORE_B2B - and
the price is the material's, so each of its rows carries the same number.

A material the sheet prices and the re-price never saw is left blank. A
material it saw and could not re-price - no list price in the promotion plan
and no history to read a discount from - comes back carrying the GSCM price
unchanged, which is what the card shows and what the run counts as `kept`.
That is a number the sheet already had, not a prediction, and in a bare
column the two look alike: `--blank-kept` leaves those blank instead, which
is usually what a simulation wants.

Formatting is kept where `openpyxl` is installed. Without it the sheet is
rewritten with the repo's own writer, which keeps every value and loses the
colours - the run says which of the two happened.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo_match as PM                                        # noqa: E402
import reprice as RP                                            # noqa: E402
import xlsx as XL                                               # noqa: E402
from rawdata import MONTHS, parse_number, read_any             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CODE = ('Item', 'Material', 'Material Code', 'SKU', 'Model')
OUT_MARK = '_new_price'
# What a row gets when the sheet lists the material but October does not plan
# it - no quantity and no amount in the month's own columns, so there is
# nothing to re-price and nothing went wrong. An empty cell would say the
# same thing and say it ambiguously, and a column of unexplained blanks is a
# question every reader has to ask once.
NO_PLAN = 'no Oct price'


def priced_but_unplanned(src, mon):
    """{code: Oct price} for rows the month prices and does not plan.

    The sheet carries three months side by side. A material planned for
    November and December has no October quantity and no October amount, so
    `plan_price` leaves it out of the month - but its row still quotes an
    October price, and a product that sells without a plan line is exactly
    the one somebody wants a predicted price for. It goes through the same
    ladder as everything else, at nought planned units.
    """
    import plan_price as PP
    rows, _ = read_any(src)
    if not rows:
        return {}
    head = [str(h or '').strip() for h in rows[0]]
    ym = 2600 + (MONTHS.index(mon) + 1)
    at = PP.columns(head, ym)
    item = column_at(head, *CODE)
    if item is None or at['aud'] is None:
        return {}
    keep = set(PP.read_plan(src, ym, say=lambda *a: None)['items'])
    out = {}
    for r in rows[1:]:
        code = (r[item] or '').strip() if item < len(r) else ''
        if not code or code.upper() in keep or code in keep:
            continue
        px = parse_number(r[at['aud']]) if at['aud'] < len(r) else None
        if px and px > 0:
            out[code.upper()] = px
    return out


def find_sheet(folder: Path, stem: str):
    """The GSCM workbook. An .xlsx is wanted here, not the .csv beside it.

    What this writes is also a gscm*.xlsx sitting in the same folder, and it
    sorts after the one it came from. Picking that up on the next run put a
    second column in beside the first, so the tool's own output is skipped
    by name.
    """
    # Unless the stem names one of them on purpose, in which case it is
    # read and its column rewritten in place.
    skip = OUT_MARK not in stem.lower()
    hits = [p for p in sorted(folder.iterdir())
            if p.is_file() and p.name.lower().startswith(stem.lower())
            and p.suffix.lower() in ('.xlsx', '.xlsm')
            and not (skip and OUT_MARK in p.stem.lower())]
    return hits[-1] if hits else None


def column_at(head: list, *names):
    low = [str(h or '').strip().lower() for h in head]
    for n in names:
        if n.lower() in low:
            return low.index(n.lower())
    return None


def heads_for(label, basis=False):
    """What goes in, in order.

    One column by default. A sheet people have already built pivots and
    lookups over is a layout, and widening it moves every column after the
    insert - so the extras are asked for rather than assumed. The same two
    facts are in `docs/reprice_<month>.csv` for anyone who would rather look
    them up than carry them.
    """
    return [label, 'Basis', 'Nearest SKU'] if basis else [label]


def places(head: list, mon: str, label: str, basis=False):
    """(material column, column to sit after, the column already there).

    All 0-based. A sheet that already carries the column is rewritten in
    place rather than given a second one, so running this twice over the
    same file leaves one column, not two.
    """
    item = column_at(head, *CODE)
    after = column_at(head, f'{mon} Price(AUD)', f'{mon} Price (AUD)')
    if item is None or after is None:
        return None, None, None
    return item, after, column_at(head, label)


def with_openpyxl(src, dst, price, basis, near, mon, label, say,
                  extras=False):
    """Insert the column and keep the workbook otherwise exactly as it is."""
    import copy
    import openpyxl
    wb = openpyxl.load_workbook(src)
    ws = wb['GSCM'] if 'GSCM' in wb.sheetnames else wb.worksheets[0]
    item, after, have = places([c.value for c in ws[1]], mon, label)
    if item is None:
        return None
    cols = heads_for(label, extras)
    if have is None:
        new = after + 2
        for n, name in enumerate(cols):
            ws.insert_cols(new + n)
            ws.cell(row=1, column=new + n, value=name)
            ws.cell(row=1, column=new + n).font = copy.copy(
                ws.cell(row=1, column=after + 1).font)
    else:
        new = have + 1
        say('  the sheet already had the column - it was rewritten, '
            'not added again')
        for r in range(2, ws.max_row + 1):
            for n in range(len(cols)):
                ws.cell(row=r, column=new + n, value=None)
    fmt = ws.cell(row=2, column=after + 1).number_format
    hit = 0
    for r in range(2, ws.max_row + 1):
        k = PM.code_norm(ws.cell(row=r, column=item + 1).value)
        p = price.get(k)
        if p is not None:
            ws.cell(row=r, column=new, value=round(p, 2)).number_format = fmt
            hit += 1
        if not extras:
            continue
        ws.cell(row=r, column=new + 1,
                value=basis.get(k) or (NO_PLAN.replace('Oct', mon)
                                       if k else None))
        if near.get(k):
            ws.cell(row=r, column=new + 2, value=near[k])
    wb.save(dst)
    say('  openpyxl: the workbook keeps its formatting')
    return hit, ws.max_row - 1


def with_stdlib(src, dst, price, basis, near, mon, label, say,
                extras=False):
    """No openpyxl: rewrite the sheet, every value kept, the colours not."""
    rows, _ = read_any(src)
    if not rows:
        return None
    head = rows[0]
    item, after, have = places(head, mon, label)
    if item is None:
        return None
    if have is not None:
        # Rewriting in place: drop the old ones and put them back where the
        # fresh ones go, so a second run cannot leave two of each.
        say('  the sheet already had the column - it was rewritten, '
            'not added again')
        gone = {column_at(head, n)
                for n in heads_for(label, True)} - {None}
        keep = [i for i in range(len(head)) if i not in gone]
        rows = [[r[i] if i < len(r) else '' for i in keep] for r in rows]
        head = rows[0]
        item, after, _ = places(head, mon, label)
        if item is None:
            return None

    def num(v):
        s = str(v or '').strip()
        if not s:
            return None
        try:
            return float(s) if ('.' in s or 'e' in s.lower()) else int(s)
        except ValueError:
            return s

    cols = heads_for(label, extras)
    out = [list(head[:after + 1]) + cols + list(head[after + 1:])]
    hit = 0
    for r in rows[1:]:
        r = list(r) + [''] * (len(head) - len(r))
        k = PM.code_norm(r[item] if item < len(r) else '')
        p = price.get(k)
        if p is not None:
            hit += 1
        body = [num(v) for v in r]
        add = [round(p, 2) if p is not None else None]
        if extras:
            add += [basis.get(k) or (NO_PLAN.replace('Oct', mon)
                                     if k else None),
                    near.get(k) or None]
        out.append(body[:after + 1] + add + body[after + 1:])
    styles = [XL.MONEY if i == after + 1 else XL.PLAIN
              for i in range(len(out[0]))]
    XL.write(dst, 'GSCM', out, styles=styles)
    say('  no openpyxl here, so the sheet was rewritten - every value is '
        'kept, the colours are not')
    return hit, len(rows) - 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--gscm', default='gscm', metavar='STEM',
                    help='the workbook, by name or prefix (default gscm)')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM')
    ap.add_argument('--back', type=int, default=6, metavar='N',
                    help='months of history the re-price reads (default 6)')
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM')
    ap.add_argument('--model', default='simple',
                    choices=('simple', 'campaign'),
                    help='simple: each product\u2019s own six-month ASP, '
                         'nudged by three group ratios. campaign: the older '
                         'per-product per-campaign discount off RRP')
    ap.add_argument('--scope', default='range', choices=RP.SCOPES,
                    help='how far a thin product may borrow a discount '
                         'from. Default range: its own model family, which '
                         'is close enough to be worth having. sku refuses '
                         'to borrow at all; div3 and wider are too coarse')
    ap.add_argument('--by-members', dest='by_units', action='store_false',
                    default=True,
                    help='a group answers with the average of its products '
                         'rather than of its units')
    ap.add_argument('--flat-days', action='store_true',
                    help='weight every day of the month alike instead of '
                         'by how hard each campaign sells')
    ap.add_argument('--no-mix', action='store_true',
                    help='ignore the plan\u2019s B2B share and price every '
                         'material at the mix the history happened to have')
    ap.add_argument('--new-cap', type=float, default=0.0, metavar='PCT',
                    help='the deepest discount a new SKU may inherit from '
                         'the product it is priced off (default 0: no cap)')
    ap.add_argument('--decay', type=float, default=0.0, metavar='MONTHS',
                    help='half-life: a line this much older counts half as '
                         'much (default 0, every month alike)')
    # The re-price's own switches, so a column can be written from any run
    # the dashboard can draw. `reprice.py --help` explains each.
    ap.add_argument('--asp-first', dest='promo_first',
                    action='store_false')
    ap.add_argument('--min-months', type=int, default=None, metavar='N')
    ap.add_argument('--quiet-list', action='store_true')
    ap.add_argument('--pooled-asp', dest='pooled', action='store_true')
    ap.add_argument('--keep-clearance', dest='clearance',
                    action='store_false')
    ap.add_argument('--explain', action='store_true')
    ap.add_argument('--campaigns', nargs='?', const='div3', default='',
                    choices=('range', 'div3', 'div1'))
    ap.add_argument('--why', nargs='+', default=(), metavar='CODE')
    ap.add_argument('--with-basis', action='store_true',
                    help='also write Basis and Nearest SKU. Off by default: '
                         'one column in keeps every other column where the '
                         'sheet already had it')
    ap.add_argument('--planned-only', action='store_true',
                    help='leave out the materials the month prices but does '
                         'not plan, instead of running them through the '
                         'same rules at nought planned units')
    ap.add_argument('--blank-kept', action='store_true',
                    help='leave a material blank where the re-price could '
                         'only hand the GSCM price back, instead of '
                         'repeating it')
    ap.add_argument('--out', default=None, metavar='FILE',
                    help='default <the sheet>_new_price.xlsx beside it')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        print(f'no such folder: {folder}')
        return 1
    src = find_sheet(folder, args.gscm)
    if src is None:
        print(f'no {args.gscm}*.xlsx in {folder} - this writes a workbook, '
              'so it needs one to write into')
        return 1

    ym = args.month
    if ym is None:
        import plan_price as PP
        body, _ = read_any(src)
        head = [str(h or '').strip() for h in (body[0] if body else [])]
        have = [i for i in range(1, 13)
                if PP.columns(head, 2600 + i)['aud'] is not None]
        if not have:
            print(f'  {src.name}: no month price column in it')
            return 1
        ym = 2600 + have[0]
    if ym >= 100000:
        ym %= 10000
    mon = MONTHS[(ym % 100) - 1]
    label = f'New Price {mon}'

    # The same call the dashboard makes, so the column and the card are the
    # same number. reprice walks real dates and wants the long month.
    print(f'{src.name}  ·  {mon} 20{ym // 100}\n')
    also = {} if args.planned_only else priced_but_unplanned(src, mon)
    if args.min_months:
        RP.set_min_months(args.min_months)
    priced = RP.reprice(folder, (2000 + ym // 100) * 100 + ym % 100,
                        args.back, args.plan,
                        scope=args.scope, decay=args.decay, also=also,
                        new_cap=args.new_cap / 100.0, no_mix=args.no_mix,
                        flat_days=args.flat_days, by_units=args.by_units,
                        model=args.model, promo_first=args.promo_first,
                        quiet_list=args.quiet_list, pooled=args.pooled,
                        clearance=args.clearance, explain=args.explain,
                        campaigns=args.campaigns, why=args.why)
    price = {PM.code_norm(k): v['price'] for k, v in priced.items()
             if v.get('price')
             and not (args.blank_kept and v.get('how') == 'kept')}
    # How each price was reached, and for a product the window never saw, the
    # one it was priced off. A new SKU priced off a neighbour is a judgement,
    # and a judgement belongs on the row where it can be overruled one line
    # at a time rather than buried in a log.
    basis = {PM.code_norm(k): v.get('how', '') for k, v in priced.items()}
    near = {PM.code_norm(k): v.get('near', '') for k, v in priced.items()}
    how: dict = {}
    for v in priced.values():
        how[v.get('how', '?')] = how.get(v.get('how', '?'), 0) + 1

    dst = Path(args.out) if args.out else src.with_name(
        src.stem + '_new_price.xlsx')
    if not dst.is_absolute():
        dst = ROOT / dst
    cols = heads_for(label, args.with_basis)
    print(f'\nwriting {", ".join(cols)} into the sheet '
          f'({len(cols)} column{"" if len(cols) == 1 else "s"}):')
    try:
        import openpyxl                                   # noqa: F401
        got = with_openpyxl(src, dst, price, basis, near, mon, label, print,
                            args.with_basis)
    except ImportError:
        got = with_stdlib(src, dst, price, basis, near, mon, label, print,
                          args.with_basis)
    if got is None:
        print(f'  {src.name}: no material column, or no {mon} Price(AUD) '
              '- nothing to put the column beside')
        return 1
    hit, rows = got
    print(f'  {hit:,} of {rows:,} row(s) carry a price, '
          f'{rows - hit:,} left blank')
    if rows > hit:
        # The commonest reason by far, and the one that looks like a fault
        # until it is named: the sheet carries three months and this is one
        # of them.
        print(f'  a row with no {mon} price at all has nothing to work '
              'from, and its Basis says so')
        print('  rather than being left empty')
    print('  ' + ', '.join(f'{n:,} {k}' for k, n in sorted(
        how.items(), key=lambda kv: -kv[1])))
    if how.get('kept') and not args.blank_kept:
        print(f'  {how["kept"]:,} of those are the GSCM price handed back '
              'unchanged, not a prediction - --blank-kept leaves them blank')
    print(f'\n-> {dst}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

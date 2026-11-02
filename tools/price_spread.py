#!/usr/bin/env python3
"""How consistently a month missed its price, not just by how much.

    py tools\\price_spread.py
    py tools\\price_spread.py --month 2610 --by div2
    py tools\\price_spread.py --top 15 --out docs\\spread_2610.csv

The card on the dashboard says a division came in 253 under its planned price.
That one number has two very different stories behind it, and they call for
two different conversations:

    every model in it came in about 253 under   the plan's price for that
                                                division was simply wrong

    half came in 900 under and half 400 over    the plan's level was close
                                                and its mix of prices was not

The mean cannot tell those apart. The standard deviation can, so this reports
the two together, for each division, on both bases:

    actual vs GSCM        what the sheet planned the month at
    actual vs re-priced   what tools\\reprice.py says it could have planned

Both are the same subtraction the dashboard makes - the material's realised
price less its planned one - read over the materials of a division instead of
added up over them.

Everything is weighted by the units that actually sold, so the mean is the
division's real miss per unit and the spread is the spread of the money, not
of the catalogue: a model that sold three units does not move it as far as one
that sold three thousand.

Both sides are the order export, `orders_26XX`, on its `Net Value (Item)` -
the same money the dashboard's gap card is on, which is not the profit
export's net sales.

Only the standard library, like the rest of the tools.
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo_match as PM                                        # noqa: E402
import sap as SAP                                               # noqa: E402
from asp import PRODUCT_KEYS                                    # noqa: E402
from rawdata import (MONTHS, find, master, parse_number,        # noqa: E402
                     pick_file, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# The chain a material hangs off, deepest last. Div 2 is the default because
# it is the level a price is argued at - a Biz is too coarse to act on and a
# model is one line of an argument, not the argument.
PROD_COLS = {
    'biz':  ('Biz', 'Business', 'Business Unit'),
    'div1': ('Div 1', 'Div1', 'Division 1', 'Division'),
    'div2': ('Div 2', 'Div2', 'Division 2'),
    'div3': ('Div 3', 'Div3', 'Category', 'Prod_group'),
}
LEVELS = ('biz', 'div1', 'div2', 'div3')


def read_month(folder: Path, ym: int, say=print) -> dict:
    """{code: [units, value]} for the month, off the order export.

    Rejected lines are dropped and so is anything that nets to nothing or
    less: a return has no price to read, and averaging one in would put a
    number in the ASP column that nobody sold at.
    """
    want = str(ym)[-4:]
    files = [p for p in pick_series(folder, 'orders') if want in p.stem]
    if not files:
        say(f'  no orders_*{want} in {folder}')
        return {}
    got: dict = {}
    lines = used = 0
    for path in sorted(files):
        rows, _ = read_any(path)
        if not rows:
            continue
        head = [c.strip() for c in rows[0]]
        col = {k: find(head, *v) for k, v in
               (('sku', SAP.S_SKU), ('qty', SAP.S_QTY), ('amt', SAP.S_AMT),
                ('reject', SAP.S_REJECT))}
        if any(col[k] is None for k in ('sku', 'qty', 'amt')):
            say(f'  {path.name}: no product, quantity or amount column '
                '- skipped')
            continue
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r)
                             else '')
        for r in rows[1:]:
            lines += 1
            if cell(r, col['reject']):
                continue
            qty = parse_number(cell(r, col['qty'])) or 0.0
            amt = parse_number(cell(r, col['amt'])) or 0.0
            if qty <= 0 or amt <= 0:
                continue
            code = PM.code_norm(cell(r, col['sku']))
            if not code:
                continue
            o = got.setdefault(code, [0.0, 0.0])
            o[0] += qty
            o[1] += amt
            used += 1
    say(f'  {used:,} of {lines:,} order line(s) for '
        f'{MONTHS[(ym % 100) - 1]}; {len(got):,} material(s) sold')
    return got


def spread(rows: list, wkey, dkey) -> dict:
    """Unit-weighted mean and standard deviation of the DIFFERENCE.

    `dkey` is a material's gap - its realised price less the price it was
    planned at - and never a price. The deviation is therefore how much that
    gap varies from material to material inside the group, which is the
    question: a division whose models all missed by the same amount was
    priced wrong at the level, and one whose misses cancel out was not
    priced at the level at all. The deviation of the prices themselves would
    only say a division sells a fridge and a kettle.

    The weights are the units sold, so it is the spread over the units the
    month actually moved. The deviation is the population one over those
    weights - these are the units that sold, not a sample drawn from
    somewhere larger.
    """
    w = sum(r[wkey] for r in rows)
    if w <= 0:
        return {'n': len(rows), 'units': 0.0, 'mean': 0.0, 'sd': 0.0,
                'p10': 0.0, 'mid': 0.0, 'p90': 0.0}
    mean = sum(r[wkey] * r[dkey] for r in rows) / w
    var = sum(r[wkey] * (r[dkey] - mean) ** 2 for r in rows) / w
    # A deviation is one number and a squared one, so a handful of lines can
    # carry it on their own. The percentiles are there to say whether that is
    # what happened: a group genuinely spread has a wide p10..p90, and one
    # carried by a few rows has a narrow middle and a deviation far outside
    # it. Both are weighted by the same units, so they are the same
    # population read two ways.
    at = sorted(rows, key=lambda r: r[dkey])
    def pct(f):
        want, run = f * w, 0.0
        for r in at:
            run += r[wkey]
            if run >= want:
                return r[dkey]
        return at[-1][dkey]
    return {'n': len(rows), 'units': w, 'mean': mean,
            'sd': math.sqrt(max(var, 0.0)),
            'p10': pct(0.10), 'mid': pct(0.50), 'p90': pct(0.90)}


def analyse(folder: Path, ym: int, back: int, plan_stems,
            say=print) -> tuple[list, dict]:
    """One row per material, with both differences and its chain."""
    import plan_price as PP
    import reprice as RP

    gf = PP.find_plan(folder, 'gscm')
    if gf is None:
        raise SystemExit(f'no gscm_* file in {folder} - that is the plan '
                         'being measured against')
    say('reading the plan:')
    planned = PP.read_plan(gf, ym, say=say)
    if planned is None:
        raise SystemExit('the GSCM sheet has no price for that month')

    say(f'\nreading {MONTHS[(ym % 100) - 1]} as it sold:')
    sold = read_month(folder, ym, say=say)
    if not sold:
        raise SystemExit('nothing to measure')

    pp = pick_file(folder, 'product')
    levels: dict = {}
    if pp is not None:
        raw = master(pp, PRODUCT_KEYS, PROD_COLS, say=lambda *a: None)
        levels = {PM.code_norm(k): v for k, v in raw.items()}
        say(f'  product master: {pp.name}, {len(levels):,} product(s)')

    say('')
    # plan_price reads a sheet and takes YYMM; reprice walks real dates and
    # takes YYYYMM. Passing one to the other reads no history at all and
    # quietly leaves every price as the sheet had it, so the conversion is
    # made here rather than relied on.
    priced = RP.reprice(folder, (2000 + ym // 100) * 100 + ym % 100,
                        back, plan_stems, say=say)

    rows = []
    no_plan = no_rep = 0
    for code, it in planned['items'].items():
        k = PM.code_norm(code)
        got = sold.get(k)
        if not got or got[0] <= 0:
            continue                      # planned and not sold: no price
        gscm = it['aud']
        if not gscm:
            no_plan += 1
            continue
        asp = got[1] / got[0]
        rp = (priced.get(code) or {}).get('price')
        if not rp:
            no_rep += 1
        # The sheet's own chain stands in where the master does not know the
        # code - a planned material the master has never seen is still a real
        # line of the plan, and dropping it would quietly shrink the month.
        lv = levels.get(k) or {}
        chain = {n: (lv.get(n) or '').strip() for n in LEVELS}
        if not any(chain.values()):
            for n, v in zip(LEVELS, it['chain']):
                chain[n] = (v or '').strip()
        rows.append({
            'code': code, 'units': got[0], 'value': got[1], 'asp': asp,
            'gscm': gscm, 'rep': rp or 0.0,
            'dg': asp - gscm, 'dgp': (asp / gscm - 1) * 100,
            'dr': (asp - rp) if rp else None,
            'drp': ((asp / rp - 1) * 100) if rp else None,
            **{n: chain[n] or '(blank)' for n in LEVELS},
        })
    if no_plan:
        say(f'  {no_plan} planned material(s) with no price in the sheet '
            '- left out, there is nothing to measure them against')
    if no_rep:
        say(f'  {no_rep} material(s) with no re-priced price - they count '
            'on the GSCM side only')
    return rows, planned


def group(rows: list, by: str) -> list:
    """Each group of `by`, with both spreads, worst miss first."""
    pot: dict = {}
    for r in rows:
        pot.setdefault(r[by], []).append(r)
    out = []
    for name, rs in pot.items():
        rep = [r for r in rs if r['dr'] is not None]
        g = spread(rs, 'units', 'dg')
        gp = spread(rs, 'units', 'dgp')
        p = spread(rep, 'units', 'dr') if rep else None
        pp_ = spread(rep, 'units', 'drp') if rep else None
        out.append({
            'name': name, 'rows': rs,
            'units': g['units'], 'n': g['n'],
            'g': g, 'gp': gp, 'p': p, 'pp': pp_,
            'impact_g': g['mean'] * g['units'],
            'impact_r': (p['mean'] * p['units']) if p else 0.0,
        })
    return sorted(out, key=lambda o: o['impact_g'])


def says(o: dict) -> str:
    """The one sentence the two numbers of a group add up to.

    The spread against the level is the whole point of the exercise: a
    division whose models all missed by the same amount was priced wrong, and
    one whose misses cancel out was not priced at all.
    """
    m, sd = o['g']['mean'], o['g']['sd']
    if not sd:
        return 'one model'
    if abs(m) < 1e-9:
        return 'offsetting - no level to correct'
    cv = sd / abs(m)
    if cv < 0.5:
        return 'systematic - the level is wrong'
    if cv < 1.5:
        return 'level and mix both'
    return 'offsetting - the mix, not the level'


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM')
    ap.add_argument('--back', type=int, default=6, metavar='N',
                    help='months of history the re-price reads (default 6)')
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM',
                    help='the promotion plan the re-price needs')
    ap.add_argument('--by', default='div2', choices=LEVELS,
                    help='the level to group at (default div2)')
    ap.add_argument('--top', type=int, default=0, metavar='N',
                    help='also list the N materials furthest from their '
                         'own group\'s mean - what is making the spread')
    ap.add_argument('--odd', type=float, default=3.0, metavar='X',
                    help='flag materials that sold at more than X times, or '
                         'under a Xth of, the planned price (default 3)')
    ap.add_argument('--out', default=None, metavar='CSV',
                    help='write the per-material rows as well')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        print(f'no {folder}')
        return 1

    ym = args.month
    if ym is not None and ym >= 100000:
        ym = ym % 10000                       # YYYYMM given, YYMM wanted
    if ym is None:
        import plan_price as PP
        gf = PP.find_plan(folder, 'gscm')
        if gf is None:
            print(f'no gscm_* file in {folder}')
            return 1
        body, _ = read_any(gf)
        head = [h.strip() for h in (body[0] if body else [])]
        have = [i for i in range(1, 13)
                if PP.columns(head, 2600 + i)['aud'] is not None
                or PP.columns(head, 2600 + i)['amt_aud'] is not None]
        if not have:
            print(f'  {gf.name}: no month column in it')
            return 1
        ym = 2600 + have[0]

    rows, _ = analyse(folder, ym, args.back, args.plan)
    if not rows:
        print('no material sold that the plan also priced')
        return 1

    gs = group(rows, args.by)
    whole = group([dict(r, _all='all') for r in rows], '_all')[0]

    m = MONTHS[(ym % 100) - 1]
    print(f'\n{m} {2000 + ym // 100}  ·  AUD  ·  order export, '
          f'Net Value (Item)  ·  by {args.by}')
    print(f'{len(rows):,} material(s), {whole["units"]:,.0f} unit(s)\n')

    # Spelled out, because `sd` in a column of money reads as the spread of
    # the prices and it is nothing of the kind: every figure under the two
    # headings is the gap between what a material sold at and what it was
    # planned at, averaged and deviated over the materials of the group.
    w = max(14, max(len(o['name']) for o in gs) + 1)
    print('gap = the material\u2019s realised price less the price it was '
          'planned at')
    print('      so the sd is how much that gap varies model to model, '
          'not how much prices vary\n')
    print(f'{"":<{w}}{"":>7}{"":>10}{"--- gap vs GSCM ---":>22}'
          f'{"- gap vs re-priced -":>22}')
    print(f'{args.by:<{w}}{"n":>7}{"units":>10}'
          f'{"mean gap":>11}{"sd of gap":>11}'
          f'{"mean gap":>11}{"sd of gap":>11}   reading')
    # Nothing clever in the formatting: the re-priced side can be absent for
    # a whole group, so each cell is made before it is placed.
    money = lambda v, sign=True: ('-' if v is None
                                  else format(v, '+,.0f' if sign else ',.0f'))
    row = lambda o, tail='': (
        f'{o["name"][:w - 1]:<{w}}{o["n"]:>7}{o["units"]:>10,.0f}'
        + f'{money(o["g"]["mean"]):>11}{money(o["g"]["sd"], False):>11}'
        + f'{money(o["p"]["mean"] if o["p"] else None):>11}'
        + f'{money(o["p"]["sd"] if o["p"] else None, False):>11}' + tail)
    for o in gs:
        print(row(o, '   ' + says(o)))
    print('-' * (w + 72))
    print(row(dict(whole, name='all')))

    # The same two readings in per cent, because a 253 miss on a 900 phone and
    # on a 4,000 fridge are not the same miss and a column of dollars cannot
    # say so.
    print('\nthe same gap as a share of the price planned (%)\n')
    print(f'{args.by:<{w}}{"mean gap":>11}{"sd of gap":>11}'
          f'{"mean gap":>11}{"sd of gap":>11}')
    pct = lambda v, sign=True: ('-' if v is None
                                else format(v, '+.1f' if sign else '.1f'))
    prow = lambda o: (
        f'{o["name"][:w - 1]:<{w}}'
        + f'{pct(o["gp"]["mean"]):>11}{pct(o["gp"]["sd"], False):>11}'
        + f'{pct(o["pp"]["mean"] if o["pp"] else None):>11}'
        + f'{pct(o["pp"]["sd"] if o["pp"] else None, False):>11}')
    for o in gs:
        print(prow(o))
    print('-' * (w + 44))
    print(prow(dict(whole, name='all')))

    # Is the deviation the group, or is it a few rows? A deviation squares
    # its distances, so a handful of lines can carry one on their own, and
    # the answer changes what to do: a wide middle is a pricing question and
    # a narrow middle with a far-out deviation is usually a data one.
    print('\nwhere the gap vs GSCM actually sits, by units\n')
    print(f'{args.by:<{w}}{"p10":>11}{"median":>11}{"p90":>11}'
          f'{"sd":>11}   ')
    for o in gs + [dict(whole, name='all')]:
        g = o['g']
        wide = g['p90'] - g['p10']
        # Said as what it is rather than as a verdict. A row holding a
        # third of a group's units is not an outlier by weight however far
        # out it sits, so a wide p10..p90 is not proof the group is spread -
        # it is proof the units are. The suspect list below is what catches
        # the other case.
        note = ('' if not g['sd'] else
                'spread across the units'
                if wide >= 2 * g['sd'] else
                'few rows carry the sd - see --top and the list below'
                if wide < g['sd'] else '')
        print(f'{o["name"][:w - 1]:<{w}}{money(g["p10"]):>11}'
              f'{money(g["mid"]):>11}{money(g["p90"]):>11}'
              f'{money(g["sd"], False):>11}   {note}')

    # Not every large gap is a price. A line that sold a bundle under one
    # material, or a quantity in a different unit, lands here as a price
    # several times the planned one and moves a deviation more than any
    # discount could. They are listed rather than dropped: whether they are
    # wrong is not this tool's call to make silently.
    x = max(args.odd, 1.000001)
    odd = [r for r in rows
           if r['gscm'] > 0 and (r['asp'] > x * r['gscm']
                                 or r['asp'] < r['gscm'] / x)]
    if odd:
        odd.sort(key=lambda r: -abs(r['dg']) * r['units'])
        ou = sum(r['units'] for r in odd)
        print(f'\n{len(odd)} material(s) sold at over {x:g}x the planned '
              f'price or under 1/{x:g} of it, {ou:,.0f} unit(s) '
              f'({ou / whole["units"] * 100:.1f}% of the month).')
        print('  These move a deviation more than any discount can. A '
              'bundle booked under one material, or a quantity')
        print('  in a different unit, looks exactly like this - worth '
              'checking before reading the spread above.')
        print(f'  {"material":<24}{args.by:<14}{"units":>8}{"ASP":>9}'
              f'{"planned":>9}{"x plan":>8}')
        for r in odd[:12]:
            print(f'  {r["code"][:23]:<24}{r[args.by][:13]:<14}'
                  f'{r["units"]:>8,.0f}{r["asp"]:>9,.0f}{r["gscm"]:>9,.0f}'
                  f'{r["asp"] / r["gscm"]:>8.1f}')
        keep = [r for r in rows if r not in odd]
        if keep:
            k = spread(keep, 'units', 'dg')
            print(f'\n  without them: mean gap {k["mean"]:+,.0f}, '
                  f'sd of gap {k["sd"]:,.0f} '
                  f'(was {whole["g"]["mean"]:+,.0f} / '
                  f'{whole["g"]["sd"]:,.0f})')

    if args.top:
        # What is making the spread. A division's deviation is a property of
        # its models, and naming them is the difference between knowing the
        # plan is inconsistent and being able to do something about it.
        far = []
        for o in gs:
            for r in o['rows']:
                far.append((abs(r['dg'] - o['g']['mean']) * r['units'],
                            o['name'], r))
        far.sort(key=lambda t: -t[0])
        print(f'\nthe {min(args.top, len(far))} materials furthest from '
              f'their own {args.by}’s mean:')
        print(f'  {"material":<24}{args.by:<14}{"units":>8}{"ASP":>9}'
              f'{"GSCM":>9}{"vs GSCM":>10}{"re-priced":>11}{"vs it":>9}')
        for _, g, r in far[:args.top]:
            rep = format(r['rep'], ',.0f') if r['rep'] else '-'
            dr = format(r['dr'], '+,.0f') if r['dr'] is not None else '-'
            print(f'  {r["code"][:23]:<24}{g[:13]:<14}{r["units"]:>8,.0f}'
                  f'{r["asp"]:>9,.0f}{r["gscm"]:>9,.0f}{r["dg"]:>+10,.0f}'
                  f'{rep:>11}{dr:>9}')

    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('w', newline='', encoding='utf-8-sig') as fh:
            w2 = csv.writer(fh)
            w2.writerow(['Material', 'Biz', 'Div 1', 'Div 2', 'Div 3',
                         'Units', 'Order Value', 'ASP', 'GSCM price',
                         'vs GSCM', 'vs GSCM %', 'Re-priced', 'vs re-priced',
                         'vs re-priced %'])
            for r in sorted(rows, key=lambda r: r['dg'] * r['units']):
                w2.writerow([r['code'], r['biz'], r['div1'], r['div2'],
                             r['div3'],
                             round(r['units']), round(r['value']),
                             round(r['asp'], 2), round(r['gscm'], 2),
                             round(r['dg'], 2), round(r['dgp'], 2),
                             round(r['rep'], 2) if r['rep'] else '',
                             round(r['dr'], 2) if r['dr'] is not None else '',
                             round(r['drp'], 2) if r['drp'] is not None
                             else ''])
        print(f'\n-> {out}  ({len(rows):,} row(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

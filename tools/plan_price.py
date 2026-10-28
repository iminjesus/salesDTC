#!/usr/bin/env python3
"""The price the month was planned at, material by material.

    py tools\\plan_price.py                    # what it reads and what it holds
    py tools\\plan_price.py --month 2610
    py tools\\plan_price.py --top 20           # the biggest lines of the plan

The GSCM sheet is the month's plan at material level: how many of each code
the month is meant to sell and at what price, in AUD and in USD. Its amounts
add up to the same month target the Blue File sets, so it is the same plan
read one level further down - which is what makes it worth having, because a
target by product group cannot say whether a division is behind on units or on
price.

What this reads out of it is the **price**: one planned price per material,
with the planned units and amount beside it. The page then compares that price
with what the material actually sold for, so the question "we expected $241,
what did we get" has an answer per material and, added up, per division.

A row is one material for one account (E-STORE, E-STORE_B2B). The price is the
material's and is the same on every one of its rows; the units and the amounts
are the account's and are added together.

Only the standard library, like the rest of the tools.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import (MONTHS, find, parse_number,                   # noqa: E402
                     pick_file, read_any)

ROOT = Path(__file__).resolve().parent.parent

# The material code. The sheet calls it Item; the order export calls the same
# thing Material, and the two are the same string.
CODE = ('Item', 'Material', 'Material Code', 'SKU', 'Model')
# The chain the sheet carries itself. The page does not use it to place a row -
# it has its own product master for that - but a planned code that never sold
# is only ever seen here, and without this it could not be named.
CHAIN = (('Biz', ('Biz', 'Business', 'Business Unit')),
         ('Div 1', ('DIV 1', 'Div 1', 'Div1', 'Division 1')),
         ('Div 2', ('DIV 2', 'Div 2', 'Div2', 'Division 2')),
         ('Div 3', ('Product Group', 'Prod_group', 'Product Grp', 'Category')))


def columns(head: list[str], ym: int) -> dict:
    """Where the month's figures are, by the month's own name in the header.

    The sheet holds three months side by side and names each column after its
    month, so October is read out of the Oct columns and nothing else. The
    quantity column is spelled `Oct Targer Qty` in the file as it came; both
    spellings are accepted rather than one of them being corrected in a copy
    of the data, which would leave two files to keep.
    """
    m = MONTHS[(ym % 100) - 1]
    up = m.upper()
    return {
        'code': find(head, *CODE),
        'aud': find(head, f'{m} Price(AUD)', f'{m} Price (AUD)',
                    f'{up} PRICE(AUD)'),
        'usd': find(head, f'{m} Price(USD)', f'{m} Price (USD)',
                    f'{up} PRICE(USD)'),
        'qty': find(head, f'{m} Targer Qty', f'{m} Target Qty',
                    f'{m} Tgt Qty'),
        'amt_aud': find(head, f'{up}(AUD)', f'{m}(AUD)',
                        f'{m} Target Amt(AUD)'),
        'amt_usd': find(head, f'{up}(USD)', f'{m}(USD)',
                        f'{m} Target Amt(USD)'),
    }


def read_plan(path: Path, ym: int, say=print) -> dict | None:
    """{'ym', 'file', 'items': {code: {...}}} or None if the month is not in it.

    An item carries its planned price in both currencies, its planned units
    and its planned amount in both currencies, and the chain the sheet gives
    it. The price is taken as written; where the sheet has no price column the
    amount over the units is used instead and the run says so.
    """
    body, info = read_any(path)
    if not body:
        say(f'  {path.name} is empty')
        return None
    head = [h.strip() for h in body[0]]
    at = columns(head, ym)
    m = MONTHS[(ym % 100) - 1]
    if at['code'] is None:
        say(f'  {path.name}: no material column - it has '
            + ', '.join(h for h in head if h)[:160])
        return None
    if at['aud'] is None and at['amt_aud'] is None:
        say(f'  {path.name}: nothing for {m} in it - the columns are '
            + ', '.join(h for h in head if h)[:160])
        return None
    ch = {name: find(head, *names) for name, names in CHAIN}
    derived = at['aud'] is None or at['usd'] is None

    items: dict = {}
    rows = 0
    for r in body[1:]:
        code = (r[at['code']].strip().upper()
                if at['code'] < len(r) else '')
        if not code:
            continue
        num = lambda i: (0.0 if i is None or i >= len(r)
                         else (parse_number(r[i]) or 0.0))
        q = num(at['qty'])
        aa, au = num(at['amt_aud']), num(at['amt_usd'])
        it = items.get(code)
        if it is None:
            it = items[code] = {
                'qty': 0.0, 'amt_aud': 0.0, 'amt_usd': 0.0,
                'aud': num(at['aud']), 'usd': num(at['usd']),
                'chain': [(r[i].strip() if i is not None and i < len(r) else '')
                          for i in ch.values()],
            }
        it['qty'] += q
        it['amt_aud'] += aa
        it['amt_usd'] += au
        rows += 1

    # A price column rounded to the dollar is still the price that was planned
    # with, so it is the one used. Only where there is no price column at all
    # is one worked out, and then it is said out loud: an amount over a
    # quantity is an average and not a price list.
    short = 0
    for code, it in items.items():
        for cur, amt in (('aud', 'amt_aud'), ('usd', 'amt_usd')):
            if not it[cur]:
                it[cur] = (it[amt] / it['qty']) if it['qty'] else 0.0
                short += 1
    items = {k: v for k, v in items.items() if v['qty'] or v['amt_aud']}
    say(f'  {path.name}: {rows:,} row(s), {len(items):,} material(s) for {m}, '
        f'{sum(v["qty"] for v in items.values()):,.0f} unit(s), '
        f'{sum(v["amt_aud"] for v in items.values()):,.0f} AUD / '
        f'{sum(v["amt_usd"] for v in items.values()):,.0f} USD')
    if derived or short:
        say(f'  {short} price(s) worked out as the amount over the units - '
            'the sheet has no price column for them')
    return {'ym': ym, 'file': path.name, 'items': items}


def find_plan(folder: Path, stem: str = 'gscm'):
    return pick_file(folder, stem)


def payload(plan: dict) -> dict:
    """The page's own shape: one short list per material, to keep it small.

    [price AUD, price USD, planned units, planned AUD, planned USD] - and the
    chain only where the material would otherwise have no name on the page.
    """
    r2 = lambda v: round(v, 2)
    return {
        'ym': plan['ym'], 'file': plan['file'],
        'items': {k: [r2(v['aud']), r2(v['usd']), round(v['qty']),
                      round(v['amt_aud']), round(v['amt_usd'])]
                  for k, v in plan['items'].items()},
        'chain': {k: v['chain'] for k, v in plan['items'].items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--plan', default='gscm', metavar='STEM',
                    help='the sheet, by name or prefix (default gscm)')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM',
                    help='which month of it to read (default the newest it '
                         'has a price column for)')
    ap.add_argument('--top', type=int, default=0, metavar='N',
                    help='also list the N biggest materials of the plan')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    path = find_plan(folder, args.plan)
    if path is None:
        print(f'no {args.plan}_* file in {folder.resolve()}')
        return 1
    print(f'reading {folder}')

    want = args.month
    if want is None:
        body, _ = read_any(path)
        head = [h.strip() for h in (body[0] if body else [])]
        # The newest month the sheet actually prices, so a file holding Oct,
        # Nov and Dec is read for the one being traded unless told otherwise.
        have = [i for i in range(1, 13)
                if columns(head, 2600 + i)['aud'] is not None
                or columns(head, 2600 + i)['amt_aud'] is not None]
        if not have:
            print(f'  {path.name}: no month column in it')
            return 1
        want = 2600 + have[0]
        print(f'  month(s) in it: '
              + ', '.join(MONTHS[i - 1] for i in have)
              + f' - reading {MONTHS[want % 100 - 1]} (--month picks another)')
    plan = read_plan(path, want)
    if plan is None:
        return 1
    if args.top:
        rows = sorted(plan['items'].items(),
                      key=lambda kv: -kv[1]['amt_aud'])[:args.top]
        print(f'\nthe {len(rows)} biggest of the plan:')
        print(f'  {"material":<22}{"units":>8}{"AUD":>12}'
              f'{"price":>10}   division')
        for code, v in rows:
            print(f'  {code:<22}{v["qty"]:>8,.0f}{v["amt_aud"]:>12,.0f}'
                  f'{v["aud"]:>10,.0f}   '
                  + ' / '.join(x for x in v['chain'][:3] if x))
    return 0


if __name__ == '__main__':
    sys.exit(main())

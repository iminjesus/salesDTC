#!/usr/bin/env python3
"""Sales deduction, month by month and channel by channel - and what moved it.

    py tools\\deduction.py
    py tools\\deduction.py --was 2604,2605,2606 --now 2607,2608,2609 --top 25

Deduction is the line a channel is paid through, and it moves for reasons that
look alike in a total and not at all alike underneath:

    a rate            every row deeper, in step - an accrual, a programme that
                      applies to all of it, or a mechanic that moved from the
                      price into this line
    a mix             the same rates, more of the deeper rows
    a few accounts    one customer's rebate, which is a negotiation and not a
                      trend
    one month         a true-up: a lump landing where it was settled rather
                      than where it was earned

So this prints the trend per channel - total, share of gross, and per unit -
and then takes two periods apart: how much of the change is rate and how much
is mix, which rows carry it, and whether they are the same rows every month.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import promo_match as PM                                       # noqa: E402
from asp import CUSTOMER_KEYS, PRODUCT_KEYS, QTY_NET           # noqa: E402
from channel_cogs import (DEDUCT, GROSS, NET, PROD_COLS,       # noqa: E402
                          first_readable, pct, per)
from rawdata import (find, key_norm, master, month_of,         # noqa: E402
                     parse_number, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent


class Pot:
    """One channel in one month."""

    def __init__(self):
        self.qty = self.gross = self.deduct = self.net = 0.0
        self.by: dict = {}

    def add(self, key, qty, gross, deduct, net):
        self.qty += qty; self.gross += gross
        self.deduct += deduct; self.net += net
        v = self.by.setdefault(key, [0.0, 0.0, 0.0])
        v[0] += qty; v[1] += gross; v[2] += deduct


def read_month(path: Path, cust: dict, prod: dict, keep_returns: bool,
               say=print) -> tuple:
    rows, info = read_any(path)
    if not rows:
        raise ValueError('it is empty')
    head = [h.strip() for h in rows[0]]
    at = {k: find(head, *names) for k, names in
          (('sku', PRODUCT_KEYS), ('cust', CUSTOMER_KEYS), ('qty', QTY_NET),
           ('net', NET), ('gross', GROSS), ('deduct', DEDUCT))}
    missing = [k for k in ('sku', 'cust', 'qty', 'deduct') if at[k] is None]
    if missing:
        raise ValueError('no ' + ', no '.join(missing))
    cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
    num = lambda r, i: ((parse_number(cell(r, i)) or 0.0)
                        if i is not None else 0.0)

    # Deduction is carried negative in some exports and positive in others.
    # The column decides once, by where its weight sits, so a credit keeps its
    # own sign instead of being read as another deduction.
    neg = pos = 0.0
    for r in rows[1:]:
        v = parse_number(cell(r, at['deduct']))
        if v is None:
            continue
        if v < 0:
            neg -= v
        else:
            pos += v
    sgn = -1 if neg > pos else 1

    ym = month_of(head, rows[1:], path.stem, say=lambda *a: None)
    pots = {CUST.ONLINE: Pot(), CUST.OFFLINE: Pot()}
    for r in rows[1:]:
        qty = num(r, at['qty'])
        if not keep_returns and qty < 0:
            continue
        c = cust.get(key_norm(cell(r, at['cust']))) or {}
        pot = pots.get(CUST.channel_of(c.get('account'), bool(c)))
        if pot is None:
            continue
        p = prod.get(PM.code_norm(cell(r, at['sku']))) or {}
        key = (c.get('account') or '(no account)',
               (p.get('div3') or '').strip() or '(no div 3)',
               cell(r, at['sku']))
        pot.add(key, qty, num(r, at['gross']), sgn * num(r, at['deduct']),
                num(r, at['net']))
    return ym, pots, info


def trend(months: list, say=print) -> None:
    say('\nsales deduction, month by month')
    say(f'  {"month":<9}{"channel":<10}{"units":>11}{"gross":>15}'
        f'{"deduction":>14}{"of gross":>10}{"per unit":>11}')
    for ym, pots in months:
        for name, pot in (('online', pots[CUST.ONLINE]),
                          ('offline', pots[CUST.OFFLINE])):
            if not pot.gross and not pot.deduct:
                continue
            say(f'  {ym:<9}{name:<10}{pot.qty:>11,.0f}{pot.gross:>15,.0f}'
                f'{pot.deduct:>14,.0f}{pct(per(pot.deduct, pot.gross)):>10}'
                f'{(per(pot.deduct, pot.qty) or 0):>11,.2f}')


def compare(months: list, was: list, now: list, channel: str, top: int,
            say=print) -> list:
    """What changed between two sets of months, split into rate and mix."""
    def gather(which):
        out: dict = {}
        g = q = d = 0.0
        for ym, pots in months:
            if ym not in which:
                continue
            pot = pots[channel]
            g += pot.gross; q += pot.qty; d += pot.deduct
            for k, v in pot.by.items():
                a = out.setdefault(k, [0.0, 0.0, 0.0])
                a[0] += v[0]; a[1] += v[1]; a[2] += v[2]
        return out, g, q, d

    a, ag, aq, ad = gather(set(was))
    b, bg, bq, bd = gather(set(now))
    if not ag or not bg:
        say('\n  one of the two periods has no gross sales in this channel')
        return []
    ra, rb = ad / ag, bd / bg
    say(f'\n{channel}: deduction {pct(ra)} of gross -> {pct(rb)}  '
        f'({(rb - ra) * 100:+.2f}pp)')
    say(f'  {ad:,.0f} over {", ".join(sorted(was))}  ->  '
        f'{bd:,.0f} over {", ".join(sorted(now))}')
    # Shift-share on the rows: the same rates with the new weights, then the
    # new rates with the new weights. Mix is what moved because the business
    # moved; rate is what moved because the rows themselves deepened.
    mix = rate = 0.0
    rows = []
    for k in set(a) | set(b):
        va, vb = a.get(k, [0, 0, 0]), b.get(k, [0, 0, 0])
        wa = va[1] / ag if ag else 0
        wb = vb[1] / bg if bg else 0
        ka = va[2] / va[1] if va[1] else 0
        kb = vb[2] / vb[1] if vb[1] else 0
        mix += (wb - wa) * ka
        rate += wb * (kb - ka)
        rows.append({'key': k, 'was': ka, 'now': kb, 'gross': vb[1],
                     'deduct_was': va[2], 'deduct_now': vb[2],
                     'share': wb, 'moved': (wb - wa) * ka + wb * (kb - ka)})
    say(f'  {"the rows themselves deepened (rate)":<40}{rate * 100:>8.2f}pp')
    say(f'  {"the business moved (mix)":<40}{mix * 100:>8.2f}pp')
    say(f'  {"":<40}{"-" * 8}')
    say(f'  {"the change":<40}{(rate + mix) * 100:>8.2f}pp')
    if abs(rate) > abs(mix) * 2:
        say('\n  Nearly all of it is the rows themselves. That is a rate: an '
            'accrual, a programme that applies to all of it, or a mechanic '
            'that moved out of the price and into this line.')
    elif abs(mix) > abs(rate) * 2:
        say('\n  Nearly all of it is the mix. The rates held; what sold '
            'changed, so look at what grew rather than at the deduction.')
    rows.sort(key=lambda r: -abs(r['moved']))
    say(f'\n  the {min(top, len(rows))} rows that moved it most')
    say(f'    {"account":<24}{"div 3":<14}{"model":<18}'
        f'{"was":>8}{"now":>8}{"share":>8}{"pp":>8}')
    for r in rows[:top]:
        acc, div, sku = r['key']
        say(f'    {acc[:24]:<24}{div[:14]:<14}{sku[:18]:<18}'
            f'{r["was"] * 100:>7.1f}%{r["now"] * 100:>7.1f}%'
            f'{r["share"] * 100:>7.1f}%{r["moved"] * 100:>8.2f}')
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--export', default='profit', metavar='STEM')
    ap.add_argument('--customer', default='customer', metavar='STEM')
    ap.add_argument('--product', default='product', metavar='STEM')
    ap.add_argument('--was', metavar='LIST',
                    help='the months to compare from, as 2604,2605,2606 '
                         '(default: the three before --now)')
    ap.add_argument('--now', metavar='LIST',
                    help='the months to compare to (default: the last three '
                         'in the folder)')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME')
    ap.add_argument('--top', type=int, default=20, metavar='N')
    ap.add_argument('--no-returns', dest='returns', action='store_false')
    ap.add_argument('--out', metavar='FILE')
    ap.set_defaults(returns=True)
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    print(f'reading {folder}')
    cp, cust = first_readable(
        folder, args.customer,
        lambda q: master(q, ('Sold-To', 'sold To', 'sold_to'),
                         {'account': CUST.ACCOUNT_NAMES}))
    if not cust:
        print('no customer master could be read - no row can be placed in a '
              'channel')
        return 1
    pp, raw = first_readable(folder, args.product,
                             lambda q: master(q, PRODUCT_KEYS, PROD_COLS))
    prod = {PM.code_norm(k): v for k, v in (raw or {}).items()}
    print(f'  customers: {cp.name}, {len(cust):,}'
          + (f'; products: {pp.name}, {len(prod):,}' if pp else ''))

    months = []
    for path in sorted(pick_series(folder, args.export),
                       key=lambda q: q.name):
        try:
            ym, pots, info = read_month(path, cust, prod, args.returns)
        except (ValueError, OSError, KeyError, IndexError) as e:
            print(f'  {path.name}: {e} - skipped')
            continue
        months.append((str(ym or path.stem), pots))
    if not months:
        print('no profit export could be read')
        return 1
    months.sort(key=lambda m: m[0])
    trend(months)

    known = [m[0] for m in months]
    short = {m[-4:]: m for m in known}
    pick = lambda v: [short.get(x.strip(), x.strip()) for x in v.split(',')
                      if x.strip()]
    now = pick(args.now) if args.now else known[-3:]
    was = pick(args.was) if args.was else known[max(0, len(known) - 6):-3]
    if not was or not now:
        print('\nnot enough months to compare')
        return 0
    rows = compare(months, was, now, args.channel, args.top)
    if args.out and rows:
        with open(args.out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['account', 'div 3', 'model', 'deduction % was',
                        'deduction % now', 'share of gross now',
                        'deduction was', 'deduction now', 'moved pp'])
            for r in rows:
                w.writerow([*r['key'], round(r['was'] * 100, 3),
                            round(r['now'] * 100, 3), round(r['share'] * 100, 4),
                            round(r['deduct_was']), round(r['deduct_now']),
                            round(r['moved'] * 100, 4)])
        print(f'\n-> {args.out}  ({len(rows):,} row(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

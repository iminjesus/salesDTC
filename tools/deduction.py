#!/usr/bin/env python3
"""One money column of the profit export, month by month - and what moved it.

    py tools\\deduction.py
    py tools\\deduction.py --column AK --where "Div 1=DA" --was 2601..2606 --now 2607..2609
    py tools\\deduction.py --column "Paid Commission" --where "Div 1=DA" --top 25

Sales deduction is the default because it was the first question asked of it,
but any column works - `--column` takes a header name or a spreadsheet letter,
and `--where` narrows to one part of the business. A cost line moves for
reasons that look alike in a total and not at all alike underneath:

    a rate            every row deeper, in step - an accrual, a programme that
                      applies to all of it, or a mechanic that moved from the
                      price into this line
    a mix             the same rates, more of the deeper rows
    a few accounts    one customer's rebate, which is a negotiation and not a
                      trend
    one month         a true-up: a lump landing where it was settled rather
                      than where it was earned

So this prints the trend per channel - total, share of sales, and per unit -
and then takes two periods apart: how much of the change is rate and how much
is mix, which rows carry it, and whether they are the same rows every month.

A spreadsheet letter is positional and an export gets re-cut, so the run
always prints the header the letter landed on. Check it before reading
anything else.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import promo_match as PM                                       # noqa: E402
from asp import CUSTOMER_KEYS, PRODUCT_KEYS, QTY_NET           # noqa: E402
from channel_cogs import (DEDUCT, GROSS, NET,                  # noqa: E402
                          first_readable, pct, per)
from rawdata import (find, key_norm, master, month_of,         # noqa: E402
                     parse_number, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# The product levels --where can narrow on, by the spellings the masters use.
PROD_COLS = {'name': ('Marketing Name', 'Product_Name', 'Description'),
             'biz': ('Biz', 'Business'),
             'div1': ('Div 1', 'Div1', 'Division'),
             'div2': ('Div 2', 'Div2'),
             'div3': ('Div 3', 'Div3', 'Category', 'Prod_group'),
             'range': ('Range', 'product_range')}
# What a --where name means, so "Div 1" and "div1" are one thing.
WHERE_AT = {'biz': 'biz', 'div1': 'div1', 'div2': 'div2', 'div3': 'div3',
            'range': 'range', 'category': 'div3', 'sku': 'sku',
            'model': 'sku', 'material': 'sku', 'channel': 'channel',
            'account': 'account', 'customer': 'account'}


def col_index(head: list, want: str):
    """The column a name or a spreadsheet letter points at.

    A letter is positional, and an export that gains a column moves it, so the
    caller is told which header it landed on rather than left to assume.
    """
    i = find(head, want)
    if i is not None:
        return i, 'by name'
    t = want.strip().upper()
    if t and all('A' <= ch <= 'Z' for ch in t) and len(t) <= 3:
        n = 0
        for ch in t:
            n = n * 26 + (ord(ch) - 64)
        if 0 < n <= len(head):
            return n - 1, f'column {t}, counted across'
    return None, 'not found'


def where_rules(args_where) -> dict:
    """--where LEVEL=VALUE, as {slot: {value, ...}}."""
    out: dict = {}
    for rule in args_where or []:
        if '=' not in rule:
            raise SystemExit(f'--where {rule!r}: write it as LEVEL=VALUE, '
                             f'e.g. --where "Div 1=DA"')
        name, vals = rule.split('=', 1)
        slot = WHERE_AT.get(re.sub(r'[^a-z0-9]', '', name.lower()))
        if slot is None:
            raise SystemExit(f'--where {rule!r}: {name.strip()!r} is not one '
                             f'of ' + ', '.join(sorted(set(WHERE_AT))))
        for v in vals.split(','):
            if v.strip():
                out.setdefault(slot, set()).add(v.strip().upper())
    return out


def where_match(rules: dict, c: dict, p: dict, sku: str, chan) -> bool:
    """Does this row belong to the slice --where asked for?"""
    for slot, vals in rules.items():
        if slot == 'channel':
            got = chan or ''
        elif slot == 'account':
            got = c.get('account') or ''
        elif slot == 'sku':
            got = sku
        else:
            got = p.get(slot) or ''
        if str(got).strip().upper() not in vals:
            return False
    return True


def months_in(a: str, b: str) -> list:
    """Every month from a to b inclusive, both written as YYMM."""
    out, cur = [], int(a)
    for _ in range(240):
        out.append(f'{cur:04d}')
        if cur >= int(b):
            break
        cur = cur + 1 if cur % 100 < 12 else (cur // 100 + 1) * 100 + 1
    return out


def spell(v: str, known: list) -> list:
    """A month list, where 2601..2606 stands for the six months between.

    1H against 3Q is six months against three, and writing both out by hand
    is where a month goes missing, so a range is spelled out here instead.
    """
    short = {m[-4:]: m for m in known}
    out = []
    for tok in v.split(','):
        tok = tok.strip()
        if not tok:
            continue
        ends = [t.strip() for t in tok.split('..')] if '..' in tok else [tok]
        if len(ends) == 2 and all(t[-4:].isdigit() for t in ends):
            out += [short.get(m, m) for m in months_in(ends[0][-4:],
                                                       ends[1][-4:])]
        else:
            out.append(short.get(tok, tok))
    gone = [m for m in out if m not in known]
    if gone:
        print('  not in the folder: ' + ', '.join(gone))
    return [m for m in out if m in known]


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
               column: str = '', of: str = 'gross', rules: dict | None = None,
               say=print) -> tuple:
    rows, info = read_any(path)
    if not rows:
        raise ValueError('it is empty')
    head = [h.strip() for h in rows[0]]
    at = {k: find(head, *names) for k, names in
          (('sku', PRODUCT_KEYS), ('cust', CUSTOMER_KEYS), ('qty', QTY_NET),
           ('net', NET), ('gross', GROSS), ('deduct', DEDUCT))}
    how = 'by name'
    if column:
        at['deduct'], how = col_index(head, column)
        if at['deduct'] is None:
            raise ValueError(f'no column {column!r} - the headers are '
                             + ', '.join(h for h in head if h)[:200])
    at['base'] = at['gross'] if of == 'gross' else at['net']
    missing = [k for k in ('sku', 'cust', 'qty', 'deduct', 'base')
               if at[k] is None]
    if missing:
        raise ValueError('no ' + ', no '.join(
            {'base': of}.get(k, k) for k in missing))
    note = {'label': (head[at['deduct']] or column or 'deduction').strip(),
            'how': how, 'seen': 0, 'kept': 0}
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
        chan = CUST.channel_of(c.get('account'), bool(c))
        pot = pots.get(chan)
        if pot is None:
            continue
        sku = cell(r, at['sku'])
        p = prod.get(PM.code_norm(sku)) or {}
        note['seen'] += 1
        if rules and not where_match(rules, c, p, sku, chan):
            continue
        note['kept'] += 1
        key = (c.get('account') or '(no account)',
               (p.get('div3') or '').strip() or '(no div 3)', sku)
        pot.add(key, qty, num(r, at['base']), sgn * num(r, at['deduct']),
                num(r, at['net']))
    return ym, pots, info, note


def trend(months: list, label: str = 'deduction', of: str = 'gross',
          say=print) -> None:
    say(f'\n{label.lower()}, month by month')
    say(f'  {"month":<9}{"channel":<10}{"units":>11}{of:>13}'
        f'{label[:18]:>18}{"of " + of:>10}{"per unit":>11}')
    for ym, pots in months:
        for name, pot in (('online', pots[CUST.ONLINE]),
                          ('offline', pots[CUST.OFFLINE])):
            if not pot.gross and not pot.deduct:
                continue
            say(f'  {ym:<9}{name:<10}{pot.qty:>11,.0f}{pot.gross:>13,.0f}'
                f'{pot.deduct:>18,.0f}{pct(per(pot.deduct, pot.gross)):>10}'
                f'{(per(pot.deduct, pot.qty) or 0):>11,.2f}')


def compare(months: list, was: list, now: list, channel: str, top: int,
            label: str = 'deduction', of: str = 'gross', say=print) -> list:
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
        say(f'\n  one of the two periods has no {of} sales in this channel')
        return []
    ra, rb = ad / ag, bd / bg
    say(f'\n{channel}: {label.lower()} {pct(ra)} of {of} -> {pct(rb)}  '
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
            'changed, so look at what grew rather than at the cost line.')
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
    ap.add_argument('--column', default='', metavar='NAME|LETTER',
                    help='the money column to follow, as a header name or a '
                         'spreadsheet letter (default: sales deduction)')
    ap.add_argument('--of', choices=('gross', 'net'), default='gross',
                    help='what the rate is a share of (default: gross)')
    ap.add_argument('--where', action='append', metavar='LEVEL=VALUE',
                    help='narrow to one slice, e.g. --where "Div 1=DA"; '
                         'repeatable, and a value list is allowed')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME')
    ap.add_argument('--top', type=int, default=20, metavar='N')
    ap.add_argument('--no-returns', dest='returns', action='store_false')
    ap.add_argument('--out', metavar='FILE')
    ap.set_defaults(returns=True)
    args = ap.parse_args()
    rules = where_rules(args.where)

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

    # A level the master does not carry would silently match nothing, so it is
    # an error up front rather than an empty table further down.
    has = {k for k in PROD_COLS
           if any((v.get(k) or '').strip() for v in prod.values())}
    for slot in (set(rules) & set(PROD_COLS)) - has:
        raise SystemExit(f'--where: {pp.name if pp else "the product master"} '
                         f'has no {slot} - it carries '
                         + (', '.join(sorted(has)) or 'none of the levels'))
    for slot, vals in rules.items():
        if slot in has:
            seen = {(v.get(slot) or '').strip().upper() for v in prod.values()}
            gone = sorted(v for v in vals if v not in seen)
            if gone:
                print(f'  note: no product has {slot} = '
                      + ', '.join(gone) + '; it carries '
                      + ', '.join(sorted(v for v in seen if v)[:12]))

    months = []
    label, kept, seen = 'deduction', 0, 0
    for path in sorted(pick_series(folder, args.export),
                       key=lambda q: q.name):
        try:
            ym, pots, info, note = read_month(path, cust, prod, args.returns,
                                              args.column, args.of, rules)
        except (ValueError, OSError, KeyError, IndexError) as e:
            print(f'  {path.name}: {e} - skipped')
            continue
        if not months:
            label = note['label']
            # A letter is positional. Say which header it landed on, because
            # a re-cut export moves it and nothing else would show that.
            print(f'  column: {label!r} ({note["how"]})'
                  + (f', as a share of {args.of}' if args.column else ''))
        kept += note['kept']; seen += note['seen']
        months.append((str(ym or path.stem), pots))
    if not months:
        print('no profit export could be read')
        return 1
    if rules:
        slice_ = ', '.join(k + '=' + '/'.join(sorted(v))
                           for k, v in sorted(rules.items()))
        print(f'  {slice_}: {kept:,} of {seen:,} rows')
        if not kept:
            print('  nothing matched - check the spelling against the note '
                  'above')
            return 1
    months.sort(key=lambda m: m[0])
    trend(months, label, args.of)

    known = [m[0] for m in months]
    now = spell(args.now, known) if args.now else known[-3:]
    was = (spell(args.was, known) if args.was
           else known[max(0, len(known) - 6):-3])
    if not was or not now:
        print('\nnot enough months to compare')
        return 0
    rows = compare(months, was, now, args.channel, args.top, label, args.of)
    if args.out and rows:
        with open(args.out, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['account', 'div 3', 'model', f'% of {args.of} was',
                        f'% of {args.of} now', f'share of {args.of} now',
                        f'{label} was', f'{label} now', 'moved pp'])
            for r in rows:
                w.writerow([*r['key'], round(r['was'] * 100, 3),
                            round(r['now'] * 100, 3), round(r['share'] * 100, 4),
                            round(r['deduct_was']), round(r['deduct_now']),
                            round(r['moved'] * 100, 4)])
        print(f'\n-> {args.out}  ({len(rows):,} row(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

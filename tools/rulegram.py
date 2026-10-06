#!/usr/bin/env python3
"""What a promotion rule is made of, read off the codes themselves.

    py tools\\rulegram.py --orders "26 DTC Sep"

The store writes a promotion as one joined code and nothing documents its
shape:

    AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT

Read left to right it is plainly not arbitrary - a country, who may buy, where,
what kind of product, when it runs, the mechanic, then the offer - but the
number of parts varies, so counting from the left gets the wrong answer on half
the codes and counting from the right gets it on the other half.

So the **dates are the landmark**. Every part before them says where and to whom
the promotion applied; every part after says what it was. That one split holds
whatever the length, and this tool reports what actually turns up in each
position on either side of it, by the units behind it rather than by how many
distinct spellings exist.

Nothing here is matched against a plan. It is one file read on its own terms,
which is the only way to find out what the vocabulary is before asking whether
two files share one.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo as PR                                              # noqa: E402
from promo_match import (MECHANIC, RULE_DATE, code_norm,        # noqa: E402
                         mechanics_in, parse_rule, split_rules)
from rawdata import find, parse_number, pick_file, read_any     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

D_SKU = ('Product Code', 'SKU', 'Material', 'Model Code', 'Product Number')
D_QTY = ('Quantity', 'Qty', 'Units')
D_AMT = ('AUD Revenue excl. GST', 'Net Amount', 'Amount', 'Line Total')
D_RULE = ('promotion_rule', 'Promotion Rule', 'Promo Rule', 'Rule')
D_STATUS = ('order_status', 'Order Status', 'Status')

# What a token is, decided by what it looks like and nothing else. The point of
# naming only these is that everything left over is the thing worth reading:
# an unknown token on a lot of units is a category this file uses and nobody
# has written down.
COUNTRY = {'AU', 'NZ', 'SG', 'MY', 'TH', 'VN', 'ID', 'PH', 'IN', 'KR'}
WHO = {'EPP', 'SCOM', 'S.COM', 'SME', 'SMB', 'EDU', 'GOV', 'B2C', 'B2B', 'DTC',
       'STAFF', 'CORP', 'CORPORATE', 'PARTNERSHIP', 'INTERNAL', '3PD', 'NRM',
       'T1', 'T2', 'T3', 'T1-T2', 'T2-T3', 'T1-T2-T3', 'TIER1', 'TIER2',
       'TIER3', 'ALL'}
WHERE = {'WEB', 'APP', 'STORE', 'ONLINE', 'POS', 'SHOP', 'MOBILE'}
PCT = re.compile(r'^\d{1,3}(PCT|PERCENT|OFF)$|^PCT$|^PERCENT$')
MONEY = re.compile(r'^\$?\d{2,5}(OFF|DOLLAR)?$')
SERIAL = re.compile(r'^\d{4,}$')


def kind_of(tok: str, groups=frozenset()) -> str:
    """The one word for what this piece of a code is, or 'unnamed'.

    `groups` is the product master's own vocabulary - its divisions, categories
    and ranges - passed in rather than written here, so what counts as a product
    group is whatever that file says it is.
    """
    u = tok.upper()
    if not re.search(r'[A-Z0-9]', u):
        return 'punctuation'
    if RULE_DATE.match(u):
        return 'date'
    if code_norm(u) in groups:
        return 'product group'
    if u in COUNTRY:
        return 'country'
    if u in WHO:
        return 'who may buy'
    if u in WHERE:
        return 'where'
    if u in MECHANIC:
        return 'mechanic'
    if PCT.match(u):
        return 'how much off'
    if SERIAL.match(u):
        return 'serial'
    if MONEY.match(u):
        return 'how much off'
    return 'unnamed'


def parts_of(raw: str) -> list:
    """The code's pieces, on whichever separator it was written with."""
    return [p for p in re.split(r'[_\s]+', raw.strip()) if p]


def split_on_dates(parts: list) -> tuple:
    """(before the dates, the dates, after them) - the one split that holds."""
    at = [i for i, p in enumerate(parts) if RULE_DATE.match(p.upper())]
    if not at:
        return parts, [], []
    return parts[:at[0]], parts[at[0]:at[-1] + 1], parts[at[-1] + 1:]


def table(title, counter, weight, total, say, top=14, width=34):
    say(f'\n  {title}')
    if not counter:
        say('    nothing')
        return
    for k, v in counter.most_common(top):
        say(f'    {str(k)[:width]:<{width}}{v:>10,.0f}{v / (total or 1) * 100:>7.1f}%'
            + (f'   {weight[k]:>12,.0f}' if weight else ''))
    if len(counter) > top:
        rest = total - sum(v for _, v in counter.most_common(top))
        say(f'    {f"and {len(counter) - top:,} more":<{width}}{rest:>10,.0f}'
            f'{rest / (total or 1) * 100:>7.1f}%')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--orders', default='26 DTC Sep', metavar='STEM')
    ap.add_argument('--top', type=int, default=14, metavar='N')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'rule_grammar.csv'))
    args = ap.parse_args()

    folder = Path(args.dir)
    op = pick_file(folder, args.orders)
    if op is None:
        print(f'no orders file matching {args.orders!r} in {folder.resolve()}',
              file=sys.stderr)
        return 2
    rows, info = read_any(op)
    head = [h.strip() for h in rows[0]]
    i_rule = find(head, *D_RULE)
    i_qty, i_amt = find(head, *D_QTY), find(head, *D_AMT)
    i_sku, i_st = find(head, *D_SKU), find(head, *D_STATUS)
    print(f'reading:\n  {op.name}: {info["format"]}, {len(rows) - 1:,} rows')
    if i_rule is None:
        print(f'  no promotion rule column; columns are: '
              + ', '.join(h for h in head if h), file=sys.stderr)
        return 1
    print(f'  rule column: {head[i_rule]!r}')

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # What the product master calls its divisions, categories and ranges. A rule
    # token spelling one of those is a product group, and nothing here decides
    # that on its own: TV, DA, AV and MON are in the rules because they are in
    # the master, and a short form the master does not use stays unnamed and is
    # reported as such.
    groups = set()
    pp = pick_file(folder, 'product') or pick_file(folder, 'product_2608')
    if pp:
        prows, _ = read_any(pp)
        phead = [h.strip() for h in prows[0]]
        cols = [find(phead, n) for n in ('Division', 'Category', 'Range',
                                         'product_range', 'Series')]
        for r in prows[1:]:
            for i in cols:
                v = code_norm(cell(r, i))
                if v:
                    groups.add(v)
        print(f'  product master: {pp.name}, {len(groups):,} division/category/'
              f'range spelling(s) to recognise')
    else:
        print('  no product master, so a product group in a rule cannot be told '
              'from any other word')

    # One record per rule occurrence, carrying the units behind it: a shape on
    # four hundred units says more about the vocabulary than one on four.
    seen = collections.Counter()
    units = collections.Counter()
    lines = kept = 0
    for r in rows[1:]:
        if 'CANCEL' in cell(r, i_st).upper():
            continue
        kept += 1
        q = parse_number(cell(r, i_qty)) or 0.0
        for raw in split_rules(cell(r, i_rule)):
            lines += 1
            seen[raw] += 1
            units[raw] += max(q, 0.0)
    if not seen:
        print('\n  not one row carries a promotion rule.', file=sys.stderr)
        return 1
    tot_u = sum(units.values()) or 1.0
    print(f'  {kept:,} live order line(s), {lines:,} rule occurrence(s), '
          f'{len(seen):,} distinct rule(s), {tot_u:,.0f} unit(s)')

    # ── the shape ───────────────────────────────────────────────────────────
    shape = collections.Counter()
    dated = und = 0
    for raw, n in units.items():
        parts = parts_of(raw)
        before, when, after = split_on_dates(parts)
        shape[(len(before), len(when), len(after))] += n
        if when:
            dated += n
        else:
            und += n
    print(f'\nthe shape, by units  (pieces before the dates / dates / after)')
    for k, v in shape.most_common(args.top):
        print(f'    {str(k):<34}{v:>10,.0f}{v / tot_u * 100:>7.1f}%')
    print(f'  {dated / tot_u * 100:.0f}% of units are on a rule that carries its '
          f'own dates; the rest have no landmark\n  and are read as one piece')

    # ── either side of the dates ────────────────────────────────────────────
    front: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    back: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    kinds = collections.Counter()
    unnamed = collections.Counter()
    unnamed_where = collections.defaultdict(collections.Counter)
    for raw, n in units.items():
        before, when, after = split_on_dates(parts_of(raw))
        for i, p in enumerate(before):
            front[i][p.upper()] += n
        for i, p in enumerate(after):
            back[i][p.upper()] += n
        for side, parts in (('before the dates', before), ('after them', after)):
            for p in parts:
                k = kind_of(p, groups)
                kinds[k] += n
                if k == 'unnamed':
                    unnamed[p.upper()] += n
                    unnamed_where[side][p.upper()] += n

    print('\n\nBEFORE THE DATES - where the promotion ran and who could buy it')
    for i in sorted(front)[:5]:
        table(f'piece {i + 1}', front[i], None, tot_u, print, args.top)
    print('\n\nAFTER THE DATES - what the promotion was')
    for i in sorted(back)[:5]:
        table(f'piece {i + 1} after the dates', back[i], None, tot_u, print,
              args.top)

    # The piece immediately before the dates. Whatever each token means, this
    # is one slot used one way, and reading it as a slot needs no vocabulary at
    # all - which is the only way to name the short forms the master does not
    # spell.
    last_before = collections.Counter()
    no_slot = 0.0
    for raw, n in units.items():
        before, when, _ = split_on_dates(parts_of(raw))
        if not (when and before):
            continue
        tok = before[-1].upper()
        # Where the last piece before the dates is the country, the buyer or the
        # site, this rule simply has no category piece - counted, not listed,
        # because a site in the category list reads as a category.
        if kind_of(tok, groups) in ('country', 'who may buy', 'where'):
            no_slot += n
        else:
            last_before[tok] += n
    if last_before:
        tot_slot = sum(last_before.values())
        table('the piece immediately before the dates - what the rule is about',
              last_before, None, tot_slot, print, 20)
        named = sum(v for k, v in last_before.items() if code_norm(k) in groups)
        print(f'  {named / tot_slot * 100:.0f}% of those units name something '
              f'the product master also spells; the rest are short forms only '
              f'the\n  store uses, and this list is where to read them rather '
              f'than guess at them.')
        print(f'  a further {no_slot:,.0f} unit(s) '
              f'({no_slot / (tot_slot + no_slot) * 100:.0f}%) have no piece '
              f'here at all - their last piece before the\n  dates is the site '
              f'or the buyer, so those rules say nothing about what they are on')

    print('\n\nwhat each piece is, by units')
    for k, v in kinds.most_common():
        print(f'    {k:<34}{v:>10,.0f}{v / sum(kinds.values()) * 100:>7.1f}%')
    print('  "unnamed" is the answer this run exists for: a piece on a lot of '
          'units that no\n  vocabulary in these tools names is a category this '
          'file uses and nobody wrote down.')
    table('the unnamed pieces, biggest first', unnamed, None,
          sum(unnamed.values()), print, max(args.top, 24))
    for side in ('before the dates', 'after them'):
        c = unnamed_where[side]
        if c:
            print(f'\n  of those, the ones that sit {side}: '
                  + ', '.join(f'{k} {v:,.0f}' for k, v in c.most_common(12)))

    # ── one row per distinct rule, taken apart ──────────────────────────────
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Rule', 'Lines', 'Units', 'Before the dates', 'Dates',
                    'After them', 'Mechanic', 'Offer', 'Family', 'Unnamed pieces'])
        for raw, n in sorted(seen.items(), key=lambda kv: -units[kv[0]]):
            before, when, after = split_on_dates(parts_of(raw))
            d = parse_rule(raw)
            kind, rest = mechanics_in(d['what'])
            offer = ' '.join(rest)
            w.writerow([raw, n, round(units[raw]), ' '.join(before),
                        ' '.join(when), ' '.join(after),
                        ' + '.join(sorted(set(kind))), offer,
                        PR.family_label(' + '.join(sorted(set(kind))), offer),
                        ' '.join(p for p in before + after
                                 if kind_of(p, groups) == 'unnamed')])
    print(f'\n-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""What the promotions look like, and whether a chart can be stacked by them.

    py tools\\promo.py                    # every store export in the folder
    py tools\\promo.py --division MX      # one division only
    py tools\\promo.py --division VD DA   # or several, if CE is split in the master
    py tools\\promo.py --month 2608       # one month

The store export carries a promotion on every order line, as one
underscore-joined code:

    AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT

Read whole, there are hundreds of them and no two months share many - which is
the complaint: the detail is there and it cannot be seen past. So the code is
pulled apart into three levels, widest first, and the run reports how much each
one gathers:

    offer type   PWP, GWP, Discount, Cashback, Bundle, Trade-Up - the mechanic
    offer        what it was on, with the mechanic taken out
    rule         the code itself, dates and all

The question underneath is whether the profit page can stack by any of them.
The profit file is keyed on a customer and a product; a promotion belongs to an
order. So a profit row can only carry a promotion by being shared out over the
promotions its orders ran under - and that is honest only where a row's orders
mostly sit on one. The last block measures exactly that, per level, so the
answer is a number rather than a hope.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                         # noqa: E402
from promo_match import (MECHANIC, mechanics_in, parse_rule,    # noqa: E402
                         split_rules)
from rawdata import (find, key_norm, master, norm_stem,         # noqa: E402
                     parse_number, pick_file, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

D_ORDER = ('Order Code', 'Order No', 'Order Number', 'Order ID', 'order_code')
D_SKU = ('Product Code', 'SKU', 'Material', 'Model Code', 'Product Number')
D_QTY = ('Quantity', 'Qty', 'Units')
D_AMT = ('AUD Revenue excl. GST', 'USD Revenue excl. GST', 'Net Amount',
         'Amount', 'Line Total')
D_RULE = ('promotion_rule', 'Promotion Rule', 'Promo Rule', 'Rule')
D_PROMO = ('Nationwide_Campaign', 'DTC_Campaign1', 'Promotion Name',
           'Promotion', 'Campaign')
D_GROUP = ('Portal Group', 'Portal', 'Site', 'Channel', 'Store')
D_STATUS = ('order_status', 'Order Status', 'Status')

NONE = '(no promotion)'


# What an offer *does*, which is the level a person can hold in their head.
#
# Read off the codes themselves rather than invented: `--tokens` counts the
# pieces the offer strings are built from, and these are the ones that came
# back on a large share of MX's units. The same offer is written several ways -
# 50PCT, 50PCTOFF, 50OFF, 50 PCT - and a wave code (26F, B4F, FF8F, 26R) is
# glued on each time it runs, which is what turned one offer into ten thousand.
#
# First match wins, so the order is the precedence: an accessories offer at 30%
# is filed under Accessories rather than under percent-off. Edit the table, not
# the code - that is the point of it being a table.
#
# These came off **MX's** codes. Another division writes its offers differently -
# CE's run to cashback, redemption, a bonus gift, delivery and installation - so
# on CE this table is a hypothesis, and the run says how much of it the table
# fails to name along with the tokens those unnamed units are built from. Write
# the new families from that list rather than from what sounds likely.
FAMILIES = [
    ('EPP welcome voucher', r'WELCOME'),
    ('Trade-in / Trade-up',  r'TRADE'),
    ('Accessories offer',    r'\bACC(ESSORIES)?\b'),
    ('First 72 hours',       r'\d*HR\b|FIRST\d+'),
    ('% off RRP',            r'RRP'),
    ('$ off',                r'\b\d{2,4}OFF\b'),
    ('% off',                r'\d+\s?PCT|PCTOFF|\d+OFF'),
    ('Bundle / PWP',         r'BUNDLE|PWP|GWP'),
    # ── CE's, read off CE_product's own Offer_Detail ────────────────────────
    # Appended rather than interleaved: first match wins, so anything put above
    # MX's rows would quietly re-bucket MX, and these were derived from a file
    # MX is not in. Within the block the order is offer before campaign - a
    # "[Boost Week] EPP $100 Voucher" is a voucher that ran during Boost Week,
    # not a campaign that happened to be a voucher - and the specific before
    # the general.
    ('Price match',          r'PRICE\s?MATCH'),
    ('Stunt promotion',      r'STUNT'),
    ('EPP surplus',          r'SURPLUS'),
    ('Aged clearance / EOL', r'CLEARANCE|AGED|\bEOL\b'),
    ('Cart abandon',         r'ABANDON'),
    ('Spend and save',       r'\bSPEND\b'),
    ('Secret sale',          r'SECRET'),
    ('Live commerce',        r'LIVE\s?COMMERCE'),
    ('Flash sale',           r'\bFLASH\b'),
    ('Staff / EDU offer',    r'\bSTAFF\b|\bEDU\b'),
    ('Samsung Care+',        r'SAMSUNG\s?CARE|\bSC\b'),
    ('Rewards points',       r'REWARD|\bPTS\b|POINTS'),
    ('Delivery / install',   r'DELIVERY|INSTALL|TABLETOP'),
    ('Bonus gift',           r'\bBONUS\b|\bGIFT\b|\bFREE\b'),
    ('$ voucher',            r'VOUCHER|\bCREDIT\b'),
    # The two MX rows above match 50PCT and 100OFF - the store writes a
    # promotion as one token. CE's plan writes the same thing in prose, "20%
    # off" and "$100 Discount", and the punctuation is stripped before matching,
    # so it arrives as "20 OFF" and matches neither. Its own row rather than a
    # space added to MX's, which would move MX units between named families.
    ('Price off',            r'\d+\s?OFF\b|\d+\s?DISCOUNT\b|\bDEEPER\b'),
    ('EPP offer',            r'\bEPP\b'),
    # Not a promotion at all: the Offer_Detail cell used as a comment field.
    # Named so it can be counted and left out, rather than sitting in the
    # residual looking like an offer nobody has classified yet.
    # No comma in the name: --precedence is a comma-separated list, and a
    # family nobody can name on the command line is a family nobody can reorder.
    ('Plan note (not an offer)',
     r'\bOVERRIDE\b|SHARPEN|\bEXTENDED\b|\bCVM\b|\bCRP\b|OFFER CHANGE'
     r'|DATE CHANGE|RETAIL PROMO'),
    ('Samsung / Boost Week', r'\bBOOST\b|SAMSUNG\s?WEEK|TECH\s?FEST'),
]


OTHER = '(not one of the named families)'


def families_in(offer: str) -> list:
    """Every family an offer matches, in the table's order."""
    up = re.sub(r'[^A-Z0-9]+', ' ', offer.upper())
    return [name for name, pat in FAMILIES if re.search(pat, up)]


def family_of(offer: str, order=None) -> str:
    """The one family a unit is filed under - the first match in `order`.

    This is a **choice**, not a reading. Most of MX's promoted units ran under
    more than one rule, so most match more than one family, and something has
    to decide which the unit counts as. First match wins, and the order is
    therefore the whole of the decision - which is why it is a table at the top
    of this file and a --precedence flag on the command line, rather than
    something buried in the code.
    """
    hits = families_in(offer)
    if not hits:
        return OTHER
    for name in (order or []):
        if name in hits:
            return name
    return hits[0]


def levels_of(raw: str) -> tuple[str, str, str]:
    """A rule code as offer type, offer, rule - widest to narrowest.

    One cell can hold several rules. They are kept together rather than picked
    between: a line that ran under two offers ran under both, and choosing one
    would quietly halve the other. The set is **sorted**, so a line carrying
    PWP and a discount lands in one bucket however the two were ordered in the
    cell - unsorted, `PWP + Discount` and `Discount + PWP` were two different
    answers to the same question.
    """
    rules = [parse_rule(r) for r in split_rules(raw)]
    if not rules:
        return NONE, NONE, NONE
    kinds, rest = [], []
    for d in rules:
        k, r = mechanics_in(d['what'])
        kinds += k
        rest.append(' '.join(r) or d['what'])
    # Deduplicated case-blind: `PROMOTEXT X, X` is one offer written twice.
    seen, detail = set(), []
    for r in rest:
        if r.upper() not in seen:
            seen.add(r.upper())
            detail.append(r)
    # Sorted at every level, for the reason the mechanic set is: the store
    # writes a promotion's two rules in either order, and unsorted that is one
    # offer counted as two.
    return (' + '.join(sorted(set(kinds))) or '(mechanic not in the code)',
            ' + '.join(sorted(detail)) or '(no detail)',
            ' + '.join(sorted({d['raw'] for d in rules})))


def cell(r, i):
    return (r[i].strip() if i is not None and i < len(r) else '')


def read_store(path, say=print):
    rows, info = read_any(path)
    if not rows:
        return None
    head = [h.strip() for h in rows[0]]
    i = {k: find(head, *v) for k, v in
         {'order': D_ORDER, 'sku': D_SKU, 'qty': D_QTY, 'amt': D_AMT,
          'rule': D_RULE, 'promo': D_PROMO, 'group': D_GROUP,
          'status': D_STATUS}.items()}
    say(f'  {path.name}: {info["format"]}, {len(rows) - 1:,} rows')
    if i['sku'] is None:
        say('    no product code - skipped')
        return None
    if i['rule'] is None and i['promo'] is None:
        say('    no promotion column - skipped')
        return None
    say('    promotion from ' + repr(head[i['rule'] if i['rule'] is not None
                                        else i['promo']]))
    out = []
    for r in rows[1:]:
        out.append({
            'order': cell(r, i['order']),
            'sku': cell(r, i['sku']),
            'qty': parse_number(cell(r, i['qty'])) or 0.0,
            'amt': parse_number(cell(r, i['amt'])) or 0.0,
            'raw': cell(r, i['rule']) or cell(r, i['promo']),
            'group': cell(r, i['group']) or '(no group)',
            'status': cell(r, i['status']).upper(),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--dtc', default='dtc', metavar='STEM',
                    help="how the store's exports are named (default: dtc; "
                         "'26 DTC Aug' is also tried)")
    ap.add_argument('--product', default='product', metavar='STEM',
                    help='how the product master is named (default: product)')
    ap.add_argument('--division', nargs='+', metavar='NAME',
                    help='these divisions only, e.g. MX, or VD DA for CE if '
                         'that is how the master spells it')
    ap.add_argument('--month', metavar='YYMM',
                    help='one month only, by the digits in the file name')
    ap.add_argument('--top', type=int, default=12, metavar='N')
    ap.add_argument('--precedence', metavar='LIST',
                    help='which family a unit counts as when it matches '
                         'several, highest first, comma separated. The default '
                         'is the order of the table in this file')
    ap.add_argument('--tokens', type=int, default=0, metavar='N',
                    help='also list the N commonest pieces the offer strings '
                         'are built from, which is where a grouping rule comes '
                         'from')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'promo_levels.csv'))
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    want = [p for p in pick_series(folder, args.dtc)]
    if not want:
        # The store exports have also been named '26 DTC Aug'.
        want = [p for p in folder.iterdir()
                if p.is_file() and 'dtc' in norm_stem(p.stem)]
    if args.month:
        want = [p for p in want if args.month in re.sub(r'\D', '', p.stem)]
    want = sorted(want, key=lambda p: re.sub(r'\D', '', p.stem))
    if not want:
        print(f'no store export like {args.dtc}_* in {folder.resolve()}',
              file=sys.stderr)
        return 2

    print('reading:')
    lines = []
    for p in want:
        got = read_store(p)
        if got:
            lines.extend(got)
    if not lines:
        print('\nnothing could be read.', file=sys.stderr)
        return 1

    # Division, so the question can be asked of MX on its own.
    div = {}
    if args.division:
        plans = [pick_file(folder, n) for n in ('MX_product', 'ce_product')]
        for cand in pick_series(folder, args.product) + [c for c in plans if c]:
            try:
                info = master(cand, ('SKU', 'Product Code', 'Material',
                                     'Product Number', 'Model Code'),
                              {'division': ('Product Division', 'Division',
                                            'Div')}, say=lambda *a: None)
            except (ValueError, OSError, IndexError):
                continue
            if info:
                div = {k: v.get('division', '') for k, v in info.items()}
                print(f'  product master: {cand.name}, {len(div):,} code(s)')
                break
        asked = {d.upper() for d in args.division}
        label = ', '.join(sorted(asked))
        if not div:
            print(f'  no product master, so --division {label} cannot '
                  'be applied', file=sys.stderr)
            return 1
        before = len(lines)
        # What the master actually spells, and how many of these lines sit in
        # each - printed whether the filter worked or not. A division asked for
        # by the wrong name otherwise comes back as "nothing", which reads as
        # "nothing was promoted" when it means "that is not the word".
        spread = collections.Counter(
            (div.get(key_norm(l['sku'])) or '(not in the master)').upper()
            for l in lines)
        lines = [l for l in lines
                 if (div.get(key_norm(l['sku'])) or '').upper() in asked]
        print(f'  {label}: {len(lines):,} of {before:,} line(s)')
        if not lines:
            print(f'  nothing in {label}. The master spells its divisions:',
                  file=sys.stderr)
            for name, n in spread.most_common(12):
                print(f'    {name:<24} {n:,} line(s)', file=sys.stderr)
            return 1

    order = [s.strip() for s in args.precedence.split(',') if s.strip()] \
        if args.precedence else None
    if order:
        known = {n for n, _ in FAMILIES}
        bad = [s for s in order if s not in known]
        if bad:
            print(f'--precedence names no such family: {", ".join(bad)}\n'
                  f'  the families are: {", ".join(n for n, _ in FAMILIES)}',
                  file=sys.stderr)
            return 2
        print(f'  precedence: {" > ".join(order)}')

    for l in lines:
        l['type'], l['offer'], l['rule'] = levels_of(l['raw'])
        l['all_fam'] = [] if l['type'] == NONE else families_in(l['offer'])
        l['family'] = (NONE if l['type'] == NONE
                       else family_of(l['offer'], order))
        l['n_rules'] = len(split_rules(l['raw']))

    tot_q = sum(l['qty'] for l in lines) or 1.0
    on = [l for l in lines if l['type'] != NONE]
    on_q = sum(l['qty'] for l in on)
    print(f'\n{len(lines):,} order line(s), {tot_q:,.0f} unit(s)')
    print(f'  {len(on):,} line(s) carry a promotion - {on_q / tot_q * 100:.0f}% '
          'of the units')

    # ── can a bar be stacked by this at all? ────────────────────────────────
    # A stacked bar divides a total: every unit in exactly one band. An order
    # that ran under a welcome voucher AND a product discount AND a PWP is in
    # three at once, so a promotion is not a division of the revenue - and this
    # is the number that decides what shape the chart can take.
    multi = sum(l['qty'] for l in on if l['n_rules'] > 1)
    print(f'  {multi:,.0f} of those units ({multi / (on_q or 1) * 100:.0f}%) '
          'ran under more than one rule at once')

    print('\nhow much each level gathers')
    print(f'  {"level":<12}{"distinct":>10}{"top 8 cover":>14}')
    for key, name in (('type', 'offer type'), ('family', 'family'),
                      ('offer', 'offer'), ('rule', 'rule')):
        c = collections.Counter()
        for l in on:
            c[l[key]] += l['qty']
        top8 = sum(v for _, v in c.most_common(8))
        print(f'  {name:<12}{len(c):>10,}{top8 / (on_q or 1) * 100:>13.0f}%')
    print('  "top 8 cover" is what the eight biggest would hold if the chart '
          'stacked by that\n  level - the rest folds into Other. A level that '
          'gathers badly is one the chart\n  cannot say much with.')

    for key, name in (('type', 'offer type'), ('family', 'family'),
                      ('offer', 'offer')):
        c = collections.Counter()
        for l in on:
            c[l[key]] += l['qty']
        print(f'\n  by {name}')
        for k, v in c.most_common(args.top):
            print(f'    {k[:52]:<52}{v:>12,.0f}{v / (on_q or 1) * 100:>6.0f}%')
        if len(c) > args.top:
            rest = on_q - sum(v for _, v in c.most_common(args.top))
            print(f'    {f"and {len(c) - args.top:,} more":<52}{rest:>12,.0f}'
                  f'{rest / (on_q or 1) * 100:>6.0f}%')

    # ── how much work the precedence is doing ───────────────────────────────
    # A family is only a partition because something decides which one a unit
    # counts as when it matches several. If almost every unit matches one
    # family, the order is a formality; if most match two or three, the order
    # IS the answer and had better be the one the business would give.
    over = collections.Counter()
    alone = collections.Counter()
    for l in on:
        for f in l['all_fam']:
            over[f] += l['qty']
            if len(l['all_fam']) == 1:
                alone[f] += l['qty']
    if over:
        print('\nhow much of each family is only in that family')
        print(f'  {"family":<32}{"units matching":>16}{"only this one":>16}')
        for k, v in over.most_common():
            print(f'  {k[:32]:<32}{v:>16,.0f}'
                  f'{alone.get(k, 0) / v * 100:>15.0f}%')
        both = sum(l['qty'] for l in on if len(l['all_fam']) > 1)
        print(f'  {both:,.0f} unit(s) ({both / (on_q or 1) * 100:.0f}%) match '
              'more than one family, so that much of the\n  split is decided by '
              'the precedence rather than read off the code. A family whose\n'
              '  "only this one" is low is one the precedence is lending units '
              'to, or taking\n  them from.')

    # ── what the table does not name ────────────────────────────────────────
    # The family table was read off MX's own codes, so it is MX's table. Pointed
    # at another division it is a guess until this number says otherwise: the
    # share of units it files under the residual, and the pieces those units are
    # built from - which is the list the division's own families get written
    # from, the same way MX's were.
    rest = [l for l in on if l['family'] == OTHER]
    rest_q = sum(l['qty'] for l in rest)
    print(f'\nwhat the family table does not name: {rest_q:,.0f} unit(s) '
          f'({rest_q / (on_q or 1) * 100:.0f}% of the promoted)')
    if rest:
        tok = collections.Counter()
        for l in rest:
            for w in {p.upper() for p in
                      re.split(r'[^A-Za-z0-9]+', l['offer']) if p}:
                tok[w] += l['qty']
        for k, v in tok.most_common(args.top):
            print(f'    {k[:40]:<40}{v:>12,.0f}{v / (rest_q or 1) * 100:>6.0f}%')
        print('  a token high here is a family the table is missing: these are '
              'the pieces the\n  unnamed units are built from, as a share of '
              'the unnamed. FAMILIES at the top of\n  tools/promo.py is where '
              'one goes, and the order of that table is the precedence.')

    # ── can the profit page stack by this? ──────────────────────────────────
    # A profit row is one customer and one product. It can only carry a
    # promotion by being shared out over the promotions its own orders ran
    # under, so what matters is how concentrated that is: if a row's units sit
    # almost entirely on one promotion, the share is nearly a fact; if they are
    # spread over five, the chart would be apportioning and should say so.
    print('\nwhether a profit row can carry one')
    print(f'  {"level":<12}{"rows":>9}{"on one":>9}{"units on the biggest":>22}')
    for key, name in (('type', 'offer type'), ('family', 'family'),
                      ('offer', 'offer'), ('rule', 'rule')):
        rows = collections.defaultdict(collections.Counter)
        for l in on:
            rows[(l['group'], key_norm(l['sku']))][l[key]] += l['qty']
        n = share = 0.0
        pure = 0
        for c in rows.values():
            t = sum(c.values())
            if t <= 0:
                continue
            n += 1
            best = max(c.values())
            share += best / t
            pure += 1 if len(c) == 1 else 0
        if not n:
            continue
        print(f'  {name:<12}{int(n):>9,}{pure / n * 100:>8.0f}%'
              f'{share / n * 100:>21.0f}%')
    print('  a row is one portal group and one product code - the finest key '
          'the store export\n  and the profit file share. "on one" is the share '
          'of rows whose units sit on a\n  single promotion; the last column is '
          'the average share held by each row\'s\n  biggest one. High means a '
          'stack by promotion is near enough a measurement.')

    # ── what the offer level is made of ─────────────────────────────────────
    # 10,000 distinct offers is not a level, it is a pile. Before any rule for
    # grouping them can be written, the pieces they are built from have to be
    # visible - so the commonest tokens are counted, by the units behind them.
    if args.tokens:
        tok = collections.Counter()
        for l in on:
            for w in set(p.upper() for p in
                         re.split(r'[^A-Za-z0-9]+', l['offer']) if p):
                tok[w] += l['qty']
        print(f'\nthe pieces the offers are built from, by units')
        for k, v in tok.most_common(args.tokens):
            print(f'    {k[:40]:<40}{v:>12,.0f}{v / (on_q or 1) * 100:>6.0f}%')
        print('  a token on a large share of the units is a grouping waiting to '
              'be named - a\n  campaign, a mechanic the vocabulary is missing, '
              'or a wave code that only\n  fragments what is otherwise one '
              'offer.')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh)
        w.writerow(['family', 'offer type', 'offer', 'rule', 'units', 'amount',
                    'lines'])
        agg = collections.defaultdict(lambda: [0.0, 0.0, 0])
        for l in lines:
            a = agg[(l['family'], l['type'], l['offer'], l['rule'])]
            a[0] += l['qty']; a[1] += l['amt']; a[2] += 1
        for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            w.writerow([*k, round(v[0]), round(v[1]), v[2]])
    print(f'\n-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

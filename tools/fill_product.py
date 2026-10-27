#!/usr/bin/env python3
"""Rows for the product master, for codes the orders use and it has not got.

    py tools\\fill_product.py --in docs\\unplaced.csv --out docs\\product_add.csv

`tools/lead_time.py --blank` says which codes the master cannot place. This
writes the rows to add, in the master's own format, so they can be pasted in.

Nothing here invents a classification. Every row is filled from evidence the
folder already holds, and each one says what the evidence was:

    plan        the promotion plan names a category for the code, and the
                codes already in the master under that same plan category
                agree on a product chain - so this code takes it
    code        no plan line, but the master's own codes sharing a prefix
                with this one agree on a chain. SM-X940NZAIXSA and
                SM-X940NZAAXSA are one product in two colours, and a shorter
                prefix still separates a tablet from a phone
    -           neither - the row is written with its levels empty and has to
                be filled by hand

The confidence column is how many master rows voted and whether they were
unanimous. A row that says `plan 41/41` is forty-one codes agreeing; one that
says `code 3/5` is three of five, and wants looking at before it is pasted.
"""
from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo_match as PM                                       # noqa: E402
from asp import PRODUCT_KEYS                                   # noqa: E402
from rawdata import find, key_norm, pick_file, read_any        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# The levels a row has to carry for the page to place it. Spelled the way the
# masters have spelled them; the file's own header decides which is used.
LEVELS = [('Biz', ('Biz', 'Business', 'Business Unit')),
          ('Div 1', ('Div 1', 'Div1', 'Division 1', 'Division')),
          ('Div 2', ('Div 2', 'Div2', 'Division 2')),
          ('Div 3', ('Div 3', 'Div3', 'Division 3', 'Prod_group',
                     'Product Group', 'Category')),
          ('Range', ('Range', 'product_range', 'Material Group'))]
# What the plan calls the thing a category is. The first that is in the file
# wins, and the run says which.
PLAN_CAT = ('Product Category', 'Category', 'Product Division', 'Division',
            'Product', 'Prod_group', 'Product Group')
# A prefix is taken on the code as written, punctuation and all: SM-X is
# four characters and separates a tablet from a phone, where the normalised
# SMX is three and would be let through by any threshold that also let SM-
# through. Thin evidence is accepted and reported rather than refused - one
# unanimous voter is still a fact about the folder, and the run names the
# rows that rest on one.
MIN_PREFIX = 4
THIN = 3                 # fewer voters than this is worth looking at


def read_master(folder: Path, stem: str, say=print):
    """(path, header, rows, sku column) - the file as it is, not as a dict.

    Read raw because the output has to be the same shape as the input: the
    point is a block that can be pasted into the master, not a table that
    happens to hold the same facts.
    """
    path = pick_file(folder, stem)
    if path is None:
        raise SystemExit(f'no {stem}_* file in {folder}')
    rows, info = read_any(path)
    if not rows:
        raise SystemExit(f'{path.name} is empty')
    head = [h.strip() for h in rows[0]]
    at = find(head, *PRODUCT_KEYS)
    if at is None:
        raise SystemExit(f'{path.name}: no product code column - it has '
                         + ', '.join(h for h in head if h)[:200])
    say(f'  master: {path.name}, {len(rows) - 1:,} row(s), '
        f'{len(head)} column(s), keyed on {head[at]!r}')
    return path, head, rows[1:], at


def plan_categories(folder: Path, stems, say=print) -> dict:
    """{code: category} off the promotion plans, however they spell it."""
    out: dict = {}
    for want in stems:
        path = PM.plan_file(folder, want)
        if path is None:
            say('  no plan file matching '
                + ' or '.join(repr(n) for n in str(want).split('|')))
            continue
        rows, _ = read_any(path)
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        si = find(head, *PM.NAMES['sku'])
        ci = find(head, *PLAN_CAT)
        if si is None or ci is None:
            say(f'  {path.name}: no ' + ('product code' if si is None
                                         else 'category') + ' column')
            continue
        say(f'  plan: {path.name}, category from {head[ci]!r}')
        n = 0
        for r in rows[1:]:
            code = (r[si].strip() if si < len(r) else '')
            cat = (r[ci].strip() if ci < len(r) else '')
            if code and cat:
                # First spelling wins: a code is in the plan many times, once
                # per window, and they agree on what it is.
                out.setdefault(PM.code_norm(code), cat)
                n += 1
        say(f'        {n:,} line(s), {len(out):,} code(s) so far')
    return out


def vote(chains: list) -> tuple:
    """The chain the voters agree on, and how many of how many agreed."""
    if not chains:
        return None, 0, 0
    top, n = collections.Counter(chains).most_common(1)[0]
    return top, n, len(chains)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--in', dest='src', default='docs/unplaced.csv',
                    metavar='FILE',
                    help='the --blank listing (default docs/unplaced.csv)')
    ap.add_argument('--out', default='docs/product_add.csv', metavar='FILE')
    ap.add_argument('--product', default='product', metavar='STEM')
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM')
    ap.add_argument('--known', action='store_true',
                    help='also write the codes the master already has a row '
                         'for, whose levels are only partly filled')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    src = Path(args.src)
    if not src.is_absolute():
        src = ROOT / src
    if not src.is_file():
        raise SystemExit(f'no {src} - run: py tools\\lead_time.py --blank '
                         f'--out {args.src}')

    print(f'reading {folder}')
    mpath, head, body, at = read_master(folder, args.product)
    # Where each level sits in the master's own header, so the block written
    # lines up column for column with the file it is pasted into.
    col = {name: find(head, *names) for name, names in LEVELS}
    have = [n for n, i in col.items() if i is not None]
    print('  levels in it: ' + (', '.join(have) or 'none - nothing to fill'))
    if not have:
        return 1

    cat = plan_categories(folder, args.plan)

    # What the master already knows, two ways: by plan category and by code.
    chain_of = {}                      # normalised code -> chain
    raw_of: dict = {}                  # the code as written -> chain
    by_cat: dict = {}
    for r in body:
        sku = (r[at].strip() if at < len(r) else '')
        if not sku:
            continue
        chain = tuple((r[col[n]].strip() if col[n] is not None
                       and col[n] < len(r) else '') for n in have)
        if not any(chain):
            continue                       # a row as empty as the ones added
        k = PM.code_norm(sku)
        chain_of[k] = chain
        raw_of[sku.strip().upper()] = chain
        c = cat.get(k)
        if c:
            by_cat.setdefault(c.strip().upper(), []).append(chain)
    print(f'  {len(chain_of):,} master row(s) carry a chain; '
          f'{len(by_cat):,} plan category(s) have one to learn from')

    with src.open(encoding='utf-8-sig', newline='') as f:
        want = list(csv.DictReader(f))
    if not want:
        print(f'{src.name} is empty')
        return 1
    field = next((k for k in want[0] if k.strip().lower() == 'code'), None)
    if field is None:
        raise SystemExit(f'{src.name}: no "code" column - it has '
                         + ', '.join(want[0]))
    todo = [w for w in want
            if args.known or str(w.get('in the master', 'no')).strip().lower()
            != 'yes']
    print(f'  {len(todo):,} code(s) to write'
          + ('' if args.known else f' of {len(want):,} in {src.name}'))

    out_rows, why = [], []
    for w in todo:
        sku = (w.get(field) or '').strip()
        if not sku:
            continue
        k = PM.code_norm(sku)
        chain, n, of, how = None, 0, 0, '-'
        c = cat.get(k)
        if c:
            chain, n, of = vote(by_cat.get(c.strip().upper(), []))
            if chain:
                how = 'plan'
        if chain is None:
            # The master's own codes, longest prefix first: a colour variant
            # before a sibling model before the family. Unanimity is required
            # here where the plan's majority is not - a prefix is a guess
            # about naming, and a split one is a guess about nothing.
            up = sku.strip().upper()
            for L in range(len(up), MIN_PREFIX - 1, -1):
                sibs = [v for kk, v in raw_of.items() if kk.startswith(up[:L])]
                got, n2, of2 = vote(sibs)
                if got and n2 == of2:
                    chain, how, n, of = got, f'code {up[:L]}', n2, of2
                    break
            else:
                n = of = 0
        row = [''] * len(head)
        row[at] = sku
        if chain:
            for name, v in zip(have, chain):
                row[col[name]] = v
        out_rows.append(row)
        why.append({'code': sku, 'from': how, 'votes': f'{n}/{of}' if of else '',
                    'plan category': c or '',
                    **{n2: v for n2, v in zip(have, chain or [''] * len(have))}})

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(out_rows)
    print(f'\n-> {out}  ({len(out_rows):,} row(s), the master\'s own columns)')

    note = out.with_name(out.stem + '_why' + out.suffix)
    with note.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(why[0]) if why else ['code'])
        w.writeheader()
        w.writerows(why)
    print(f'-> {note}  (where each row came from)')

    tally = collections.Counter(x['from'].split()[0] for x in why)
    print('\nfilled from: '
          + ', '.join(f'{k} {v}' for k, v in tally.most_common()))
    def votes(x):
        a, _, b = x['votes'].partition('/')
        return (int(a or 0), int(b or 0))

    weak = [x for x in why if x['from'] != '-' and x['votes']
            and (votes(x)[0] != votes(x)[1] or votes(x)[1] < THIN)]
    if weak:
        print(f'  {len(weak)} row(s) rest on thin or split evidence - look at '
              'these before pasting:')
        for x in sorted(weak, key=votes)[:12]:
            print(f'    {x["code"]:<20}{x["from"]:<22}{x["votes"]:>7}   '
                  + ' / '.join(v for v in
                               (x.get('Biz'), x.get('Div 1'), x.get('Div 3'))
                               if v))
    blank = [x for x in why if x['from'] == '-']
    if blank:
        print(f'  {len(blank)} row(s) have nothing to go on and are written '
              'empty:')
        for x in blank[:10]:
            print(f'    {x["code"]}')
        if len(blank) > 10:
            print(f'    ... and {len(blank) - 10} more')
    return 0


if __name__ == '__main__':
    sys.exit(main())

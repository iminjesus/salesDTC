#!/usr/bin/env python3
"""Add the units a model actually sold, online and offline, to a price gap file.

    py tools\\gap_units.py gap.csv --export profit_2609

Reads a file keyed on a model code - the crawler's `gap.csv` is the one this
was written for - looks each model up in a profit export, and writes the same
rows back with what that model sold beside the two shelf prices.

Which side of the business a row is on comes from `customer.py`, the same rule
both dashboards use: the account name, with anything spelled `off-line` on the
offline side and everything else online. A row whose customer the master does
not have is neither, and is counted and reported rather than quietly folded
into one of them - a split that does not add up to the export is worse than no
split.

    py tools\\gap_units.py gap.csv --export profit_2609 --named "harvey norman"

`--named` adds a column per retailer named, counting its **offline** units -
the shelf the crawler priced - from the accounts whose name contains that
text. A named retailer is a subset of the offline units, not a third channel:
Harvey Norman's units are already inside `offline units` and are not added to
anything. Units sold through its accounts that are not marked off-line are
left out and reported, so the column never quietly means two things. The run
also prints the accounts each name matched, so a retailer the master spells
differently reads as nothing matched rather than as a zero.

New columns
    online units, offline units        what the export counted, by channel
    online share                       of the two, where there are any
    unplaced units                     sold, but the customer could not be placed
    online net sales, offline net sales
    <name> offline units, <name> offline net sales   one pair per --named

A model with no row in the export gets blanks, not zeros: "it sold none" and
"the export does not mention it" are different answers and only one of them is
a finding.
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
from asp import AMT_NET, CUSTOMER_KEYS, PRODUCT_KEYS, QTY_NET  # noqa: E402
from rawdata import (MASTER_RAW, find, key_norm, master,       # noqa: E402
                     parse_number, pick_file, pick_series, read_any)

# How the customer master names its key, in one place so the lookup and the
# retailer search agree about which column is the Sold-To.
CUSTOMER_MASTER_KEYS = ('Sold-To', 'sold To', 'sold_to')

# The column in the gap file that holds a model code, in the order they are
# tried. The crawler writes both sides; either names the same product.
MODEL_COLS = ('model', 'left_model', 'right_model', 'sku', 'Material')


def cell(row, i):
    return (row[i] if i is not None and i < len(row) else '') or ''


# Sold-To -> the name it matched under, filled in by named_accounts and read
# back when the per-account breakdown is printed.
NAMES_SEEN: dict = {}


def squash(t: str) -> str:
    return ''.join(ch for ch in str(t or '').lower() if ch.isalnum())


def named_accounts(head: list, rows: list, key_names: tuple, names: list,
                   say=print) -> dict:
    """{name as typed: the customer keys whose master row names it}.

    Every column of the master is searched, not the account name alone. The
    account name here carries the channel and nothing else - `off-line`,
    `E-STORE` - so a retailer looked for there is never found; which column
    does hold it differs by master and is not worth guessing at. Matched with
    case and punctuation taken out, so "harvey norman" finds "HARVEY NORMAN
    AUSTRALIA PTY LTD" and "Harvey-Norman".

    What matched, and the column it matched in, is printed: a retailer the
    master spells some other way has to read as nothing matched, not as a zero.
    """
    k = find(head, *key_names)
    out = {n: set() for n in names}
    seen = {n: collections.Counter() for n in names}
    where = {n: collections.Counter() for n in names}
    wanted = {n: squash(n) for n in names if squash(n)}
    for r in rows:
        key = key_norm(r[k] if k is not None and k < len(r) else '')
        if not key:
            continue
        for n, want in wanted.items():
            for i, v in enumerate(r):
                if want in squash(v):
                    out[n].add(key)
                    seen[n][str(v).strip()] += 1
                    where[n][head[i] if i < len(head) else f'column {i}'] += 1
                    NAMES_SEEN[key] = str(v).strip()
                    break
    for n in names:
        if not out[n]:
            say(f'  {n!r}: no column of the master contains it - that column '
                f'will be empty')
            continue
        col = ', '.join(c for c, _ in where[n].most_common(2))
        shown = ', '.join(a for a, _ in seen[n].most_common(3))
        say(f'  {n!r}: {len(out[n]):,} account(s), from {col} - {shown}'
            + (' ...' if len(seen[n]) > 3 else ''))
    return out


def master_columns(head: list, rows: list, say=print) -> None:
    """What the master has to offer, for when a retailer is in none of it."""
    say('  the master\'s columns, with what they hold:')
    for i, h in enumerate(head):
        vals = collections.Counter(str(r[i]).strip() for r in rows
                                   if i < len(r) and str(r[i]).strip())
        if not vals:
            continue
        shown = ', '.join(v[:28] for v, _ in vals.most_common(2))
        say(f'    {h[:28]:<30} {len(vals):>6,} distinct   {shown}')


def sold_by_channel(path: Path, cust: dict, online: str, groups=None,
                    say=print) -> tuple:
    """{model code: {'on': units, 'off': units, ...}} out of a profit export."""
    rows, info = read_any(path)
    if not rows:
        say(f'  {path.name}: empty')
        return {}, {}
    head = [h.strip() for h in rows[0]]
    i_sku = find(head, *PRODUCT_KEYS)
    i_qty = find(head, *QTY_NET)
    i_amt = find(head, *AMT_NET)
    i_cust = find(head, *CUSTOMER_KEYS)
    say(f'  {path.name}: {info["format"]}, {len(rows) - 1:,} rows')
    for what, i in (('product', i_sku), ('quantity', i_qty),
                    ('net sales', i_amt), ('customer', i_cust)):
        say(f'    {what:<10} ' + (repr(head[i]) if i is not None
                                  else '-- not found --'))
    if i_sku is None or i_qty is None:
        say('  without a product code and a quantity there is nothing to '
            'count', )
        return {}, {}
    if i_cust is None:
        say('  no customer column, so no row can be placed in a channel')
        return {}, {}

    out: dict[str, dict] = {}
    totals = {'rows': 0, 'on': 0.0, 'off': 0.0, 'lost': 0.0, 'nocode': 0.0,
              'named': collections.Counter(),
              # What the export actually bought from, by name. A --named that
              # finds nothing is almost always a retailer the master spells
              # some other way, and the only cure is to see the real spellings.
              'accounts': collections.Counter(),
              # And, for a retailer that did match, what each of its Sold-To
              # codes brought in - the join itself, written out, so a code the
              # export never mentions is visible rather than a quiet nothing.
              'per_account': collections.Counter()}
    for r in rows[1:]:
        qty = parse_number(cell(r, i_qty)) or 0.0
        amt = parse_number(cell(r, i_amt)) or 0.0 if i_amt is not None else 0.0
        totals['rows'] += 1
        code = PM.code_norm(cell(r, i_sku))
        if not code:
            totals['nocode'] += qty
            continue
        key = key_norm(cell(r, i_cust))
        c = cust.get(key) or {}
        where = CUST.channel_of(c.get('account'), bool(c))
        totals['accounts'][(c.get('account') or '(no account name)',
                            where)] += qty
        v = out.setdefault(code, {'on': 0.0, 'off': 0.0, 'lost': 0.0,
                                  'on_amt': 0.0, 'off_amt': 0.0,
                                  'named': collections.Counter()})
        # A named retailer is its offline business: the shelf the crawler
        # priced. It sits inside the offline units rather than beside them,
        # so it is counted on the same row and nothing is taken off either
        # side. A retailer that also sells online - Harvey Norman does - has
        # those units left out, and the run says how many rather than letting
        # the column quietly mean two things.
        for name, keys in (groups or {}).items():
            if key not in keys:
                continue
            totals['per_account'][(name, key, where)] += qty
            if where == CUST.OFFLINE:
                v['named'][name] += qty
                v['named'][name + '\0amt'] += amt
                totals['named'][name] += qty
            else:
                totals['named'][name + '\0out'] += qty
        if where == online:
            v['on'] += qty
            v['on_amt'] += amt
            totals['on'] += qty
        elif where == CUST.OFFLINE:
            v['off'] += qty
            v['off_amt'] += amt
            totals['off'] += qty
        else:
            # Blank account name, or a customer the master does not have.
            v['lost'] += qty
            totals['lost'] += qty
    return out, totals


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('gap', help='the csv to add the columns to')
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--export', default='profit', metavar='STEM',
                    help='how the export to count is named (default: profit; '
                         'try --export profit_2609). The units and the money '
                         'are read from it and from nothing else')
    ap.add_argument('--customer', default='customer', metavar='STEM',
                    help='how the customer master is named (default: customer)')
    ap.add_argument('--named', nargs='*', default=[], metavar='RETAILER',
                    help='also count the units sold through the accounts whose '
                         'name contains this, one column each: --named '
                         '"harvey norman" "jb hi-fi". A named retailer sits '
                         'inside one of the two channels, it is not a third '
                         'one')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME',
                    help=f'which channel counts as online (default: {CUST.ONLINE})')
    ap.add_argument('--out', default=None,
                    help='where to write (default: beside the input, '
                         '<name>_units.csv)')
    args = ap.parse_args()

    gap = Path(args.gap)
    if not gap.is_file():
        print(f'no such file: {gap.resolve()}', file=sys.stderr)
        return 2
    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    sp = pick_file(folder, args.export) or next(
        iter(pick_series(folder, args.export)), None)
    if sp is None:
        print(f'no export matching {args.export!r} in {folder.resolve()}',
              file=sys.stderr)
        return 2

    print('customer master:')
    cp = next(iter(pick_series(folder, args.customer)), None)
    cust = {}
    if cp is not None:
        want = {slot: names for _, slot, names in CUST.LEVELS if names}
        want['account'] = CUST.ACCOUNT_NAMES
        cust = master(cp, CUSTOMER_MASTER_KEYS, want, say=lambda *a: None)
        print(f'  {cp.name}, {len(cust):,} account(s)')
    else:
        print(f'  nothing matching {args.customer!r} - without it no row can '
              f'be placed in a channel', file=sys.stderr)
        return 2

    groups = {}
    if args.named:
        print('\nnamed retailers:')
        head, raw = MASTER_RAW.get(cp.name, ([], []))
        groups = named_accounts(head, raw, CUSTOMER_MASTER_KEYS, args.named)
        if not any(groups.values()):
            master_columns(head, raw)

    print('\nthe export:')
    sold, totals = sold_by_channel(sp, cust, args.channel, groups)
    if not sold:
        return 2
    print(f'  {totals["on"]:,.0f} online, {totals["off"]:,.0f} offline unit(s)'
          + (f', {totals["lost"]:,.0f} whose customer the master does not have'
             if totals['lost'] else '')
          + (f', {totals["nocode"]:,.0f} with no product code'
             if totals['nocode'] else ''))
    for name in args.named:
        got = totals['named'].get(name, 0.0)
        out_of = totals['named'].get(name + '\0out', 0.0)
        print(f'  {name}: {got:,.0f} offline unit(s)'
              + (f', {got / totals["off"] * 100:.1f}% of all offline'
                 if totals['off'] and got else '')
              + (f'; {out_of:,.0f} more sold through its accounts that are not '
                 f'marked off-line, left out' if out_of else ''))
        if not got and not out_of:
            print(f'  nothing was bought through an account naming {name!r}; '
                  f'the columns above say what the master does hold.')
            continue
        names_seen = NAMES_SEEN
        hits = sorted(((k, w, q) for (n, k, w), q
                       in totals['per_account'].items() if n == name),
                      key=lambda x: -x[2])
        print(f'    {"sold-to":<14}{"side":<14}{"units":>12}   account')
        for k, side, q in hits[:20]:
            print(f'    {k[:12]:<14}{side:<14}{q:>12,.0f}   '
                  f'{(names_seen.get(k) or "")[:44]}')
        quiet = [k for k in groups.get(name, ()) if
                 not any(h[0] == k for h in hits)]
        if quiet:
            print(f'    {len(quiet):,} more Sold-To code(s) under that name '
                  f'bought nothing this month')

    with gap.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f'{gap.name} has no rows', file=sys.stderr)
        return 2
    cols = [c for c in MODEL_COLS if c in rows[0]]
    if not cols:
        print(f'{gap.name} has no model column (looked for '
              f'{", ".join(MODEL_COLS)})', file=sys.stderr)
        return 2
    print(f'\nmatching on {", ".join(cols)}')

    added = ['online units', 'offline units', 'online share', 'unplaced units',
             'online net sales', 'offline net sales']
    for name in args.named:
        added += [f'{name} offline units', f'{name} offline net sales']
    found = covered = 0.0
    for r in rows:
        hit = next((sold[k] for c in cols
                    if (k := PM.code_norm(r.get(c))) in sold), None)
        if hit is None:
            for a in added:
                r[a] = ''
            continue
        found += 1
        covered += hit['on'] + hit['off'] + hit['lost']
        both = hit['on'] + hit['off']
        r['online units'] = round(hit['on'], 2)
        r['offline units'] = round(hit['off'], 2)
        r['online share'] = round(hit['on'] / both, 4) if both else ''
        r['unplaced units'] = round(hit['lost'], 2) if hit['lost'] else ''
        r['online net sales'] = round(hit['on_amt'], 2)
        r['offline net sales'] = round(hit['off_amt'], 2)
        for name in args.named:
            r[f'{name} offline units'] = round(
                hit['named'].get(name, 0.0), 2)
            r[f'{name} offline net sales'] = round(
                hit['named'].get(name + '\0amt', 0.0), 2)

    out = Path(args.out) if args.out else gap.with_name(f'{gap.stem}_units.csv')
    with out.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) + [
            a for a in added if a not in rows[0]])
        w.writeheader()
        w.writerows(rows)

    every = totals['on'] + totals['off'] + totals['lost']
    print(f'{found:,.0f} of {len(rows):,} row(s) in {gap.name} sold in that '
          f'month; they are {covered:,.0f} of the export\'s '
          f'{every:,.0f} unit(s) ({covered / every * 100:.1f}%)'
          if every else f'{found:,.0f} of {len(rows):,} row(s) matched')
    print(f'-> {out.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

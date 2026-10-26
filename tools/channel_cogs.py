#!/usr/bin/env python3
"""Why the cost of goods sits differently online and offline - same model, both sides.

    py tools\\channel_cogs.py
    py tools\\channel_cogs.py --export profit_2609 --top 25 --out docs\\channel_cogs.csv

A channel comparison of a ratio is two questions wearing one number. Online can
show a higher cost of goods because it sells a different basket - more of the
models that were always thin - or because the same model behaves differently
there. Only the second is about the channel, and only it can be acted on, so
this reads the export twice: once as it stands, and once over the models that
**both** channels actually sold.

Three readings come out of it, and they answer different questions:

    cost of goods / net sales    the ratio the P&L shows
    cost of goods / unit         what the goods cost. The same model costs the
                                 same to make, so a gap here is cost being
                                 loaded onto the channel - freight, returns,
                                 units given away - and not a price at all
    net sales / unit             what the channel realised per unit. A gap here
                                 is a price, and nothing to do with cost

The gap on the common models is then split, the way a price/volume bridge is:

    mix       the same per-model ratios, weighted the way each channel sells
    rate      the same weights, with each model's own ratio - and that one is
              split again into what the goods cost and what they sold for

Online carries discounts straight off the price - EPP, education, vouchers -
where offline pays its channel through sales deduction, so the two are not
expected to meet. The point is to say how much of the gap is which.
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
from rawdata import (MASTER_RAW, find, key_norm, master,       # noqa: E402
                     parse_number, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# The figures, by the spellings the exports have used. Net sales is the
# denominator the P&L divides by; gross and deduction are only here so the run
# can say where each channel's discount was booked, which is most of the reason
# the two ratios differ before anything is sold at all.
NET = ('*Net Sales', 'Net Sales', 'Net Sales Amt')
COGS = ('*Cost of Goods Sold', 'Cost of Goods Sold', 'COGS', '*Ref. CoGS')
GROSS = ('*S.Gross Sales', '*Gross Sales', 'Gross Sales', 'S.Gross Sales AMT')
DEDUCT = ('*Sales Deduction', 'Sales Deduction', '*Delear Discount')
# What the product master can say about a model, for grouping and for reading
# the listing afterwards.
PROD_COLS = {'name': ('Marketing Name', 'Product_Name', 'Description'),
             'div3': ('Div 3', 'Div3', 'Category', 'Prod_group'),
             'biz': ('Biz', 'Business', 'Division')}


def pct(v):
    return '-' if v is None else f'{v * 100:,.1f}%'


def per(a, b):
    return None if not b else a / b


class Side:
    """One channel's totals, and the same totals per model."""

    def __init__(self):
        self.qty = self.net = self.cogs = self.gross = self.deduct = 0.0
        self.by: dict[str, dict] = {}

    def add(self, code, qty, net, cogs, gross, deduct):
        self.qty += qty; self.net += net; self.cogs += cogs
        self.gross += gross; self.deduct += deduct
        v = self.by.setdefault(code, {'qty': 0.0, 'net': 0.0, 'cogs': 0.0})
        v['qty'] += qty; v['net'] += net; v['cogs'] += cogs

    def ratio(self):
        return per(self.cogs, self.net)


def first_readable(folder: Path, prefix: str, read, say=print) -> tuple:
    """The newest file of a series that actually reads, and what it read.

    A folder holds the same export several ways - a csv, a workbook, an .xlsb
    that needs a module nobody installed - and the newest name is not always
    the one that opens. Each candidate is tried in turn and the reason it was
    skipped is printed, because "no customer master" and "the newest customer
    master is an .xlsb" are different problems with different fixes.
    """
    tried = []
    for cand in pick_series(folder, prefix):
        tried.append(cand.name)
        try:
            got = read(cand)
        except (ValueError, OSError, KeyError, IndexError) as e:
            say(f'  {cand.name}: {e}')
            say(f'    - trying the next {prefix} file')
            continue
        if got:
            return cand, got
        say(f'  {cand.name}: nothing could be read out of it'
            f' - trying the next {prefix} file')
    if tried:
        say(f'  none of {", ".join(tried)} could be read')
    return None, None


def two_sided(cp: Path) -> dict:
    """The accounts the master spells both ways - online in one row, offline
    in another.

    master() fills each column from the first row that has anything in it and
    reports the disagreements, which is the right rule for a detail column. A
    channel is not a detail column: the first row decides which side of the
    business every one of that account's rows lands on, and if the two
    spellings sit on different sides the split is a coin toss. Worth knowing
    how much money is riding on it before reading anything else.
    """
    head, rows = MASTER_RAW.get(cp.name, ([], []))
    k = find(head, 'Sold-To', 'sold To', 'sold_to')
    a = find(head, *CUST.ACCOUNT_NAMES)
    if k is None or a is None:
        return {}
    seen: dict = collections.defaultdict(set)
    for r in rows:
        key = key_norm(r[k] if k < len(r) else '')
        name = (r[a].strip() if a < len(r) else '')
        if key and name:
            seen[key].add(CUST.channel_of(name))
    return {key: v for key, v in seen.items() if len(v) > 1}


def read_export(path: Path, cust: dict, risky: dict = None, say=print) -> tuple:
    rows, info = read_any(path)
    if not rows:
        raise ValueError('it is empty')
    head = [h.strip() for h in rows[0]]
    at = {k: find(head, *names) for k, names in
          (('sku', PRODUCT_KEYS), ('cust', CUSTOMER_KEYS), ('qty', QTY_NET),
           ('net', NET), ('cogs', COGS), ('gross', GROSS), ('deduct', DEDUCT))}
    say(f'\nreading {path.name}: {info["format"]}, {len(rows) - 1:,} rows')
    for k in ('sku', 'cust', 'qty', 'net', 'cogs', 'gross', 'deduct'):
        i = at[k]
        say(f'  {k:<7} ' + (repr(head[i]) if i is not None else '-- not found --'))
    missing = [k for k in ('sku', 'cust', 'qty', 'net', 'cogs') if at[k] is None]
    if missing:
        raise ValueError('no ' + ', no '.join(missing)
                         + ' column, so there is nothing to compare')

    sides = {CUST.ONLINE: Side(), CUST.OFFLINE: Side()}
    lost = Side()
    risk = {'qty': 0.0, 'net': 0.0, 'keys': collections.Counter()}
    cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
    num = lambda r, i: (parse_number(cell(r, i)) or 0.0) if i is not None else 0.0
    for r in rows[1:]:
        code = PM.code_norm(cell(r, at['sku']))
        if not code:
            continue
        ckey = key_norm(cell(r, at['cust']))
        c = cust.get(ckey) or {}
        where = CUST.channel_of(c.get('account'), bool(c))
        if risky and ckey in risky:
            risk['qty'] += num(r, at['qty'])
            risk['net'] += num(r, at['net'])
            risk['keys'][ckey] += num(r, at['qty'])
        side = sides.get(where, lost)
        # Costs are carried signed in some exports and positive in others; the
        # ratio is about size, and a sign flip halfway down a column would make
        # a channel look like it sold its goods for nothing.
        side.add(code, num(r, at['qty']), num(r, at['net']),
                 abs(num(r, at['cogs'])), num(r, at['gross']),
                 abs(num(r, at['deduct'])))
    if risk['qty']:
        say(f'\n  {len(risk["keys"]):,} account(s) the master spells on both '
            f'sides of the business carry {risk["qty"]:,.0f} unit(s) and '
            f'{risk["net"]:,.0f} of net sales here.')
        say('    Which channel they landed in came from the first row of the '
            'master, not from the sale - so that much of the split is a coin '
            'toss. Biggest first: '
            + ', '.join(f'{k} ({v:,.0f}u)'
                        for k, v in risk['keys'].most_common(5)))
    return sides[CUST.ONLINE], sides[CUST.OFFLINE], lost


def headline(on: Side, off: Side, lost: Side, say=print) -> None:
    say('\nthe export as it stands')
    say(f'  {"":<10}{"units":>12}{"net sales":>15}{"cost of goods":>15}'
        f'{"CoGS %":>9}{"net/unit":>11}{"CoGS/unit":>11}{"deduct/gross":>14}')
    for name, s in (('online', on), ('offline', off), ('unplaced', lost)):
        if not s.qty and not s.net:
            continue
        say(f'  {name:<10}{s.qty:>12,.0f}{s.net:>15,.0f}{s.cogs:>15,.0f}'
            f'{pct(s.ratio()):>9}'
            f'{(per(s.net, s.qty) or 0):>11,.0f}{(per(s.cogs, s.qty) or 0):>11,.0f}'
            f'{pct(per(s.deduct, s.gross)):>14}')
    if lost.qty:
        say(f'  {lost.qty:,.0f} unit(s) sat on a customer the master could not '
            f'place, and are in neither channel')

    # "Cost of goods is most of the cost online" is a different question from
    # the ratio above, and it has a different answer: offline pays its channel
    # through sales deduction, which is a cost line sitting beside cost of
    # goods, and online takes its discount off the price, where it never
    # becomes a cost at all. Same economics, very different stacks.
    say('\nthe cost stack, which is the other question')
    say(f'  {"":<10}{"cost of goods":>15}{"sales deduction":>17}'
        f'{"CoGS share of the two":>23}')
    for name, s2 in (('online', on), ('offline', off)):
        both = s2.cogs + s2.deduct
        if not both:
            continue
        say(f'  {name:<10}{s2.cogs:>15,.0f}{s2.deduct:>17,.0f}'
            f'{pct(per(s2.cogs, both)):>23}')
    a, b = on.ratio(), off.ratio()
    if a is not None and b is not None:
        say(f'\n  online is {(a - b) * 100:+.1f}pp on cost of goods over net '
            f'sales - and the rest of this is about where that comes from')


def common(on: Side, off: Side, say=print) -> list:
    """The models both channels sold, with the per-unit figures for each."""
    both = [c for c in on.by if c in off.by
            and on.by[c]['qty'] > 0 and off.by[c]['qty'] > 0
            and on.by[c]['net'] > 0 and off.by[c]['net'] > 0]
    out = []
    for c in both:
        a, b = on.by[c], off.by[c]
        out.append({
            'code': c,
            'on_qty': a['qty'], 'off_qty': b['qty'],
            'on_net': a['net'], 'off_net': b['net'],
            'on_cogs': a['cogs'], 'off_cogs': b['cogs'],
            'on_asp': a['net'] / a['qty'], 'off_asp': b['net'] / b['qty'],
            'on_cpu': a['cogs'] / a['qty'], 'off_cpu': b['cogs'] / b['qty'],
            'on_r': a['cogs'] / a['net'], 'off_r': b['cogs'] / b['net'],
        })
    say(f'\nmodels both channels sold: {len(out):,}')
    for name, s, k in (('online', on, 'on_net'), ('offline', off, 'off_net')):
        share = per(sum(x[k] for x in out), s.net)
        qshare = per(sum(x[k[:-3] + 'qty'] for x in out), s.qty)
        say(f'  they are {pct(share)} of {name} net sales, {pct(qshare)} of its units')
    return out


def sane(rows: list, low: float, high: float, prod: dict, say=print) -> list:
    """The models whose figures can be a price on both sides.

    An export carries more than shelf sales: credits, free-of-charge
    shipments, samples and returns all arrive as a quantity with little or no
    revenue against a full cost. A tablet that cost 1,003 and shows 36 of net
    sales per unit is not a tablet sold cheaply, and in a ratio it is not a
    small error - the bridge divides by that price, so one such model moved
    the price effect by 29pp on a gap of 7.

    So a model is only compared where both sides' cost of goods over net sales
    lands inside a band a price can actually produce. What falls outside is
    not thrown away quietly: it is counted, and the biggest are named, because
    "sold below cost" is a finding of its own.
    """
    keep, drop = [], []
    for x in rows:
        (keep if low <= x['on_r'] <= high and low <= x['off_r'] <= high
         else drop).append(x)
    if not drop:
        return keep
    net = sum(x['on_net'] + x['off_net'] for x in drop)
    say(f'\n{len(drop):,} model(s) left out of the bridge: cost of goods over '
        f'net sales outside {low * 100:.0f}-{high * 100:.0f}% on one side or '
        f'the other')
    say(f'  {net:,.0f} of net sales between the two channels. They are not '
        f'prices - credits, free goods, samples and returns read this way')
    for x in sorted(drop, key=lambda x: -(x['on_net'] + x['off_net']))[:6]:
        p = prod.get(x['code']) or {}
        say(f'    {x["code"][:18]:<18} online {x["on_r"] * 100:>6.0f}% '
            f'offline {x["off_r"] * 100:>7.0f}%   net/unit '
            f'{x["on_asp"]:>8,.0f} / {x["off_asp"]:>8,.0f}   '
            f'{(p.get("name") or "")[:26]}')
    return keep


def bridge(rows: list, say=print) -> None:
    """The gap on the common models, split into mix and rate.

    Shift-share, the same shape as a price/volume bridge: hold the per-model
    ratios and move the weights, then hold the weights and move the ratios.
    The rate half is split again, because a model's ratio can only move if what
    it cost changed or what it sold for did.
    """
    on_net = sum(x['on_net'] for x in rows)
    off_net = sum(x['off_net'] for x in rows)
    if not on_net or not off_net:
        say('  nothing to bridge')
        return
    r_on = sum(x['on_cogs'] for x in rows) / on_net
    r_off = sum(x['off_cogs'] for x in rows) / off_net
    mix = rate = cost_eff = price_eff = 0.0
    for x in rows:
        w_on, w_off = x['on_net'] / on_net, x['off_net'] / off_net
        mix += (w_on - w_off) * x['off_r']
        rate += w_on * (x['on_r'] - x['off_r'])
        # r = cost per unit / price per unit, so the two effects are read at
        # the other side's level and never both at once - that is what makes
        # them add back to the whole.
        cost_eff += w_on * (x['on_cpu'] - x['off_cpu']) / x['on_asp']
        price_eff += w_on * x['off_cpu'] * (1 / x['on_asp'] - 1 / x['off_asp'])
        x['contrib'] = w_on * (x['on_r'] - x['off_r']) + (w_on - w_off) * x['off_r']
    say(f'\nsame models, both channels: online {pct(r_on)} vs offline '
        f'{pct(r_off)}  ({(r_on - r_off) * 100:+.1f}pp)')
    say(f'  {"which basket (mix)":<34}{mix * 100:>8.1f}pp   '
        f'the same models weighted the way each channel sells them')
    say(f'  {"the models themselves (rate)":<34}{rate * 100:>8.1f}pp   '
        f'each model against itself, weighted as online sells')
    say(f'      {"what the goods cost":<30}{cost_eff * 100:>8.1f}pp   '
        f'cost per unit, online against offline')
    say(f'      {"what they sold for":<30}{price_eff * 100:>8.1f}pp   '
        f'net sales per unit, online against offline')
    say(f'  {"":<34}{"-" * 8}')
    say(f'  {"the gap":<34}{(mix + rate) * 100:>8.1f}pp')
    if abs(cost_eff) > abs(price_eff) * 2:
        say('\n  The same model costs the channel more. That is not a price: '
            'look for freight, returns and units given away, and for a cost '
            'line that is only charged to one side.')
    elif abs(price_eff) > abs(cost_eff) * 2:
        say('\n  The same model costs the same and sells for less. That is a '
            'price: the discount is in what was realised, not in what was '
            'bought, and it is the channel mix and the stacked offers that '
            'decide it.')


def listing(rows: list, prod: dict, top: int, say=print) -> None:
    rows = sorted(rows, key=lambda x: -abs(x.get('contrib', 0)))[:top]
    say(f'\nthe {len(rows)} models that move the gap most')
    say(f'  {"model":<18}{"units on/off":>16}{"net/unit on":>12}{"off":>9}'
        f'{"cost/unit on":>14}{"off":>9}{"CoGS% on":>10}{"off":>8}{"pp":>7}  name')
    for x in rows:
        p = prod.get(x['code']) or {}
        say(f'  {x["code"][:18]:<18}'
            f'{x["on_qty"]:>8,.0f}/{x["off_qty"]:<7,.0f}'
            f'{x["on_asp"]:>12,.0f}{x["off_asp"]:>9,.0f}'
            f'{x["on_cpu"]:>14,.0f}{x["off_cpu"]:>9,.0f}'
            f'{x["on_r"] * 100:>9.0f}%{x["off_r"] * 100:>7.0f}%'
            f'{x.get("contrib", 0) * 100:>7.2f}  {(p.get("name") or "")[:28]}')


def write_csv(path: Path, rows: list, prod: dict, say=print) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['model', 'name', 'div3', 'online units', 'offline units',
                    'online net', 'offline net', 'online cogs', 'offline cogs',
                    'online net/unit', 'offline net/unit', 'online cost/unit',
                    'offline cost/unit', 'online cogs%', 'offline cogs%',
                    'contribution pp'])
        for x in sorted(rows, key=lambda x: -abs(x.get('contrib', 0))):
            p = prod.get(x['code']) or {}
            w.writerow([x['code'], p.get('name', ''), p.get('div3', ''),
                        round(x['on_qty']), round(x['off_qty']),
                        round(x['on_net']), round(x['off_net']),
                        round(x['on_cogs']), round(x['off_cogs']),
                        round(x['on_asp'], 2), round(x['off_asp'], 2),
                        round(x['on_cpu'], 2), round(x['off_cpu'], 2),
                        round(x['on_r'] * 100, 2), round(x['off_r'] * 100, 2),
                        round(x.get('contrib', 0) * 100, 3)])
    say(f'\n-> {path}')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--export', default='profit', metavar='STEM',
                    help='the profit export to read (default: the newest '
                         'profit_*)')
    ap.add_argument('--customer', default='customer', metavar='STEM')
    ap.add_argument('--product', default='product', metavar='STEM')
    ap.add_argument('--top', type=int, default=20, metavar='N',
                    help='how many models to list (default 20)')
    ap.add_argument('--band', nargs=2, type=float, default=(0.2, 1.5),
                    metavar=('LOW', 'HIGH'),
                    help='the cost of goods over net sales a model has to be '
                         'inside, on both sides, to be bridged (default '
                         '0.2 1.5). Outside it the figure is a credit, a free '
                         'shipment or a return rather than a price, and the '
                         'bridge divides by it')
    ap.add_argument('--min-units', type=float, default=0.0, metavar='N',
                    help='leave out a model that sold fewer than this on '
                         'either side - one unit each way is a rounding '
                         'difference wearing a percentage')
    ap.add_argument('--out', metavar='FILE', help='write every common model')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder

    # The customer master first: without it no row can be placed in a channel,
    # and there is nothing to compare.
    print(f'reading {folder}')
    cp, cust = first_readable(
        folder, args.customer,
        lambda q: master(q, ('Sold-To', 'sold To', 'sold_to'),
                         {'account': CUST.ACCOUNT_NAMES}))
    if not cust:
        print(f'no customer master named like {args.customer!r} could be read '
              f'- without it no row can be placed in a channel')
        return 1
    pp, raw = first_readable(folder, args.product,
                             lambda q: master(q, PRODUCT_KEYS, PROD_COLS))
    prod = {PM.code_norm(k): v for k, v in (raw or {}).items()}
    print(f'  customers: {cp.name}, {len(cust):,} account(s)'
          + (f'; products: {pp.name}, {len(prod):,}' if pp is not None
             else '; no product master, so models are listed by code alone'))

    risky = two_sided(cp)
    path, got = first_readable(folder, args.export,
                               lambda q: read_export(q, cust, risky))
    if got is None:
        print(f'no export named like {args.export!r} could be read')
        return 1
    on, off, lost = got
    headline(on, off, lost)
    rows = common(on, off)
    if args.min_units:
        rows = [x for x in rows
                if min(x['on_qty'], x['off_qty']) >= args.min_units]
        print(f'  {len(rows):,} left after --min-units {args.min_units:g}')
    if not rows:
        print('\nno model was sold on both sides, so there is nothing to '
              'compare like for like')
        return 0
    rows = sane(rows, args.band[0], args.band[1], prod)
    if not rows:
        print('\nnothing left inside the band, so there is nothing to bridge')
        return 0
    bridge(rows)
    listing(rows, prod, args.top)
    if args.out:
        write_csv(Path(args.out), rows, prod)
    return 0


if __name__ == '__main__':
    sys.exit(main())

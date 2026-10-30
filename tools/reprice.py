#!/usr/bin/env python3
"""What October should have been priced at, from what the months before it sold at.

    py tools\\reprice.py
    py tools\\reprice.py --month 2610 --back 6
    py tools\\reprice.py --out docs\\reprice_2610.csv

The GSCM sheet quotes a price per material for the month ahead. Measured
against what the month actually sold at, that price is out by a large number
- and most of that gap is not a discount anyone gave, it is a plan written
before the month was traded.

This writes the price the plan could have carried instead, from two things the
folder already holds:

    the list price      what the promotion plan says the product is meant to
                        sell for - the RRP
    the discount        what came off that list price when the product was
                        last sold under the same campaign

A campaign comes round: SECRET SALE, BOOST WEEK, Samsung Week. So the discount
is read **per campaign** - the price a product went out at during Boost Week
in August is the best guess at what it will go out at during Boost Week in
October - and October's own plan says which campaigns cover which days.

    price = RRP x (1 - discount), one day at a time, averaged over the month

A day with no campaign takes that product's own off-promotion discount, which
is rarely nought: a list price is not a street price.

Where the plan quotes no RRP - and it has one for about seven materials in ten
- the six-month ASP stands in. Where there is no history either, the GSCM
price is left exactly as it was, and the run says how many of each.

Nothing here is a forecast of volume. The day average weights every day of the
month alike, because the folder has no daily forecast to weight them by, and
inventing one would bury a price estimate inside a demand estimate.

Only the standard library, like the rest of the tools.
"""
from __future__ import annotations

import argparse
import calendar
import collections
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promo_match as PM                                        # noqa: E402
import sap as SAP                                               # noqa: E402
from asp import PRODUCT_KEYS                                    # noqa: E402
from rawdata import (MONTHS, find, key_norm, master,            # noqa: E402
                     parse_number, pick_file, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent

# How many units a (product, campaign) pair needs before its discount is read
# as that pair's own. Below it the pair borrows from its division, and below
# that from the month: three units at an odd price is an anecdote.
MIN_UNITS = 5
# The product levels this borrows by, coarsest last.
PROD_COLS = {'div3': ('Div 3', 'Div3', 'Category', 'Prod_group'),
             'div1': ('Div 1', 'Div1', 'Division 1', 'Division'),
             'biz': ('Biz', 'Business', 'Business Unit')}
NO_CAMP = ''                     # the key for a day with no campaign on it


def month_days(ym: int) -> list:
    y, m = ym // 100, ym % 100
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def months_back(ym: int, n: int) -> list:
    """The n months before ym, oldest first."""
    out, y, m = [], ym // 100, ym % 100
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(y * 100 + m)
    return list(reversed(out))


def campaign_at(plan, canon, code: str, day) -> str:
    """Which campaign covers this product on this day, spelled one way.

    The DTC campaign first and the second DTC column after it, which is the
    order the page reads them in; a nationwide-only day is named as such,
    because a nationwide campaign is a real trading condition even where the
    plan does not say which one it was.
    """
    live, nat, _ = PM.plan_state(plan, code, day)
    return (PM.campaign_names(live, canon, 1)
            or PM.campaign_names(live, canon, 2)
            or ('(nationwide)' if nat else NO_CAMP))


def rrp_of(plan, code: str):
    """The list price the plan quotes for a product.

    The RRP column where there is one, and the plan has several price columns
    that are not it - S.COM_Price, T1_Price, a promo price. Reading those as a
    list price would put the discount at nought on exactly the products that
    were discounted, so where there is no RRP the highest price quoted stands
    in: in a promotion plan, the list price is the one nothing is off.

    Commonest value wins among the lines: the same product is planned many
    times over, and one mistyped cell should not become the price.
    """
    cands, _ = plan.candidates(PM.code_norm(code))
    named = [c['prices']['RRP'] for c in cands
             if (c['prices'].get('RRP') or 0) > 0]
    if named:
        return collections.Counter(named).most_common(1)[0][0]
    tops = [max(v for v in c['prices'].values() if v and v > 0)
            for c in cands if any(v and v > 0 for v in c['prices'].values())]
    if not tops:
        return None
    return collections.Counter(tops).most_common(1)[0][0]


class History:
    """What each product went out at, split by the campaign it went out under.

    Three depths of the same question, because a product that sold five units
    last quarter cannot answer it alone: the product's own discount, its
    division's, and the whole book's. Each is read only where there are enough
    units behind it to mean anything.
    """

    def __init__(self):
        self.by: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        self.skus: dict = collections.defaultdict(lambda: [0.0, 0.0])

    def add(self, code, level, camp, qty, amt, rrp):
        if qty <= 0:
            return
        # The ASP tally takes every line; the discount tally takes only the
        # lines that have a list price to be a discount off. Mixing them put
        # money in the numerator with nothing in the denominator and read as a
        # product selling above its own RRP.
        self.skus[code][0] += qty
        self.skus[code][1] += amt
        if not rrp:
            return
        for scope in (('sku', code), ('div3', level.get('div3')),
                      ('div1', level.get('div1')), ('all', '')):
            if scope[1] is None:
                continue
            t = self.by[(scope, camp)]
            t[0] += qty
            t[1] += amt
            t[2] += qty * rrp

    def discount(self, scope, camp):
        """1 - what was collected over what was listed, or None.

        Never below nought. A price over its own list price is a bundle, a
        freight line or a mistyped RRP, and re-pricing a product *above* its
        list because of one is not a forecast anyone would stand behind.
        """
        t = self.by.get((scope, camp))
        if not t or t[0] < MIN_UNITS or t[2] <= 0:
            return None
        return max(0.0, 1.0 - (t[1] / t[2]))

    def asp(self, code):
        q, a = self.skus.get(code, [0.0, 0.0])
        return (a / q) if q >= MIN_UNITS else None


def read_history(folder: Path, plan, canon, months: list, levels: dict,
                 say=print) -> History:
    """Every order line of those months, priced and banded by its campaign."""
    h = History()
    want = {str(m)[-4:] for m in months}
    files = [p for p in pick_series(folder, 'orders')
             if any(w in p.stem for w in want)]
    if not files:
        say('  no order export for ' + ', '.join(str(m) for m in months))
        return h
    rrp_cache: dict = {}
    lines = used = 0
    for path in sorted(files):
        rows, _ = read_any(path)
        if not rows:
            continue
        head = [c.strip() for c in rows[0]]
        col = {k: find(head, *v) for k, v in
               (('sku', SAP.S_SKU), ('qty', SAP.S_QTY), ('amt', SAP.S_AMT),
                ('made', SAP.S_MADE), ('reject', SAP.S_REJECT))}
        if any(col[k] is None for k in ('sku', 'qty', 'amt', 'made')):
            say(f'  {path.name}: no product, quantity, amount or date column '
                '- skipped')
            continue
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
        for r in rows[1:]:
            lines += 1
            if cell(r, col['reject']):
                continue
            day = SAP.to_date(cell(r, col['made']))
            if day is None or day.year * 100 + day.month not in months:
                continue
            qty = parse_number(cell(r, col['qty'])) or 0.0
            amt = parse_number(cell(r, col['amt'])) or 0.0
            if qty <= 0 or amt <= 0:
                continue            # a return, a credit, a line worth nothing
            sku = cell(r, col['sku'])
            code = PM.code_norm(sku)
            if code not in rrp_cache:
                rrp_cache[code] = rrp_of(plan, sku)
            h.add(code, levels.get(code, {}),
                  campaign_at(plan, canon, code, day), qty, amt,
                  rrp_cache[code])
            used += 1
    say(f'  {used:,} of {lines:,} order line(s) in '
        + ', '.join(str(m) for m in months)
        + f'; {len(h.skus):,} product(s) with a realised price')
    camps = {c for (_, c) in h.by if c and c != '(nationwide)'}
    say(f'  {len(camps)} campaign(s) in that history: '
        + ', '.join(sorted(camps)[:6]) + (' ...' if len(camps) > 6 else ''))
    return h


def price_for(code, plan, canon, hist, levels, days, gscm, say_why=None):
    """One material's re-priced month, and how it was arrived at.

    The month is walked a day at a time because a campaign covers days, not
    months: a product on Boost Week for nine days of October is not the same
    price as one on it for all thirty-one.
    """
    rrp = rrp_of(plan, code)
    lv = levels.get(PM.code_norm(code), {})
    k = PM.code_norm(code)
    where = []

    def disc(camp):
        """That campaign's discount for this product, then its division."""
        for scope, name in ((('sku', k), 'this product'),
                            (('div3', lv.get('div3')), lv.get('div3')),
                            (('div1', lv.get('div1')), lv.get('div1')),
                            (('all', ''), 'the whole book')):
            if scope[1] is None:
                continue
            d = hist.discount(scope, camp)
            if d is not None:
                return d, name
        return None, None

    if rrp:
        total, on = 0.0, 0
        used = collections.Counter()
        for day in days:
            camp = campaign_at(plan, canon, k, day)
            if camp:
                on += 1
            d, from_ = disc(camp)
            if d is None:
                # No history for that campaign anywhere: the product's own
                # off-promotion discount is the nearest honest answer.
                d, from_ = disc(NO_CAMP)
            if d is None:
                total = None
                break
            used[(camp or '(no campaign)', from_)] += 1
            total += rrp * (1.0 - d)
        if total is not None:
            price = total / len(days)
            where = [f'{c} x{n} ({f})' for (c, f), n in used.most_common(4)]
            return price, 'rrp', rrp, on / len(days), where
    # No list price, or nothing to discount it by: what it actually sold at.
    asp = hist.asp(k)
    if asp:
        return asp, 'asp', rrp, 0.0, ['six-month ASP']
    return gscm, 'kept', rrp, 0.0, ['no list price and no history']


def reprice(folder: Path, ym: int, back: int, plan_stems, say=print) -> dict:
    """{code: {...}} - the re-priced month, with how each price was reached."""
    import plan_price as PP

    gf = PP.find_plan(folder, 'gscm')
    if gf is None:
        raise SystemExit(f'no gscm_* file in {folder} - that is the month '
                         'being re-priced')
    say('reading the plan to re-price:')
    planned = PP.read_plan(gf, ym, say=say)
    if planned is None:
        raise SystemExit('the GSCM sheet has no price for that month')

    say('\nreading the promotion plan:')
    plan, meta = PM.load_plans(folder, plan_stems, say=say)
    if not getattr(plan, 'rows', None):
        raise SystemExit('no promotion plan - there is no list price and no '
                         'campaign to read a discount under')
    canon = PM.canon_campaigns(plan.rows, say=lambda *a: None)

    pp = pick_file(folder, 'product')
    levels = {}
    if pp is not None:
        raw = master(pp, PRODUCT_KEYS, PROD_COLS, say=lambda *a: None)
        levels = {PM.code_norm(k): v for k, v in raw.items()}
        say(f'  product master: {pp.name}, {len(levels):,} product(s)')

    months = months_back(ym, back)
    say(f'\nreading what those products sold at over '
        f'{MONTHS[(months[0] % 100) - 1]} .. '
        f'{MONTHS[(months[-1] % 100) - 1]}:')
    hist = read_history(folder, plan, canon, months, levels, say=say)

    days = month_days(ym)
    out = {}
    how = collections.Counter()
    for code, it in planned['items'].items():
        price, kind, rrp, promo, where = price_for(
            code, plan, canon, hist, levels, days, it['aud'])
        how[kind] += 1
        # What it has actually been going out at over those months, on the
        # order export's own money - the one figure that answers "has this
        # model's price moved" without crossing files to do it.
        was = hist.asp(PM.code_norm(code))
        out[code] = {
            'gscm': it['aud'], 'price': round(price, 2), 'how': kind,
            'rrp': rrp, 'promo_days': round(promo, 3), 'qty': it['qty'],
            'asp6': None if was is None else round(was, 2),
            'why': '; '.join(where),
            'chain': it['chain'],
        }
    say(f'\nre-priced {len(out):,} material(s): '
        + ', '.join(f'{n:,} {k}' for k, n in how.most_common()))
    say('  rrp  = list price x the discount that campaign has been selling at')
    say('  asp  = no list price in the plan, so the six-month ASP stands in')
    say('  kept = no list price and no history, so the GSCM price is unchanged')
    was = sum(v['gscm'] * v['qty'] for v in out.values())
    now = sum(v['price'] * v['qty'] for v in out.values())
    say(f'\n  at the planned quantities: {was:,.0f} -> {now:,.0f} AUD '
        f'({(now / was - 1) * 100:+.1f}%)')
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM',
                    help='the month to re-price (default: the one the GSCM '
                         'sheet prices first)')
    ap.add_argument('--back', type=int, default=6, metavar='N',
                    help='how many months of history to read (default 6)')
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM')
    ap.add_argument('--out', default=None, metavar='FILE',
                    help='default docs/reprice_<month>.csv')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        raise SystemExit(f'no such folder: {folder.resolve()}')

    ym = args.month
    if ym is None:
        import plan_price as PP
        gf = PP.find_plan(folder, 'gscm')
        if gf is None:
            raise SystemExit(f'no gscm_* file in {folder.resolve()}')
        body, _ = read_any(gf)
        head = [h.strip() for h in (body[0] if body else [])]
        have = [i for i in range(1, 13)
                if PP.columns(head, 2600 + i)['aud'] is not None]
        if not have:
            raise SystemExit(f'{gf.name}: no month column in it')
        ym = 2600 + have[0]
    full = (2000 + ym // 100) * 100 + ym % 100

    out = reprice(folder, full, args.back, args.plan)

    path = Path(args.out) if args.out else ROOT / 'docs' / f'reprice_{ym}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Material', 'Biz', 'Div 1', 'Div 2', 'Div 3',
                    'Planned qty', 'GSCM price', 'Re-priced', 'Change %',
                    'RRP', 'Promo days', 'From', 'Why'])
        for code, v in sorted(out.items(),
                              key=lambda kv: -abs((kv[1]['price']
                                                   - kv[1]['gscm'])
                                                  * kv[1]['qty'])):
            ch = (v['price'] / v['gscm'] - 1) * 100 if v['gscm'] else None
            w.writerow([code, *(v['chain'] + [''] * 4)[:4], v['qty'],
                        f"{v['gscm']:.2f}", f"{v['price']:.2f}",
                        '' if ch is None else f'{ch:+.1f}',
                        '' if v['rrp'] is None else f"{v['rrp']:.2f}",
                        f"{v['promo_days'] * 100:.0f}%", v['how'], v['why']])
    print(f'\n-> {path}  ({len(out):,} material(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

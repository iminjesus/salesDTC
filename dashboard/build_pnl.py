#!/usr/bin/env python3
"""Draw the profit chart: what came in, where it went, what was left.

    py dashboard\\build_pnl.py                 # -> dashboard/PNL_<MONTH>.html
    py dashboard\\build_pnl.py --open

One bar for gross sales, a stack beside it for sales deduction, cost of goods
sold and operating cost, and a line for operating profit over net sales - the
shape of the Sales Dashboard's profit chart, across the members of whichever
dimension is picked rather than across months.

Which column is which comes from tools/analyze_structure.py, which works the
relations out from the numbers; this only draws them. Run that first, or let
this recompute when the saved analysis does not match the export.

The numbers are embedded, so the page works with no server, no database and no
connection - it can be sent to someone and opened.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import webbrowser
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import analyze_structure as A                                  # noqa: E402
import customer as CUST                                        # noqa: E402
import orders as ORD                                           # noqa: E402
import promo_match as PM                                       # noqa: E402
import lead_time as LT                                        # noqa: E402
import sap as SAP                                              # noqa: E402
import plan_price as PP                                        # noqa: E402
import target as TGT                                           # noqa: E402
from rawdata import (MASTER_RAW as RAW, find, is_return,        # noqa: E402
                     key_norm, master,
                     month_before, month_name, month_of, parse_number,
                     pick_file, pick_latest, pick_series, read_any)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# lead_time.py's key for the figure over every division, which is what a
# division with nothing sold last month falls back to.
ALL_DIVS = '\0all'


# The drill, top first: the account name only says online or offline, and the
# detail comes from the levels underneath it. Product sits alongside.
PRODUCT_LEVELS = [
    # The product tree as the master itself draws it: a business, then three
    # divisions, then the range and the model. Division and Category were two
    # flattenings of the same tree - Div 3 is Category with Aircon split back
    # into RAC and SAC - so the tree replaces them rather than sitting beside
    # them. Each keeps the old spellings as fallbacks, so a master written
    # before the Div columns existed still fills the chain, with the levels it
    # cannot tell apart holding the same value - which the page then walks
    # through in one click rather than three.
    ('Biz',   'biz',   ('Biz', 'Business', 'Business Unit', 'Division')),
    ('Div 1', 'div1',  ('Div 1', 'Div1', 'Division 1', 'Division')),
    ('Div 2', 'div2',  ('Div 2', 'Div2', 'Division 2', 'Division')),
    ('Div 3', 'div3',  ('Div 3', 'Div3', 'Division 3', 'Prod_group',
                        'Product Group', 'Category')),
    ('Range', 'range', ('Range', 'product_range', 'Material Group')),
    # The SKU itself, so per-unit prices can be read down to one model. Taken
    # from the export rather than the master, so it works even unjoined.
    ('SKU',   'sku',   ()),
]
FILTERS = CUST.LEVELS + PRODUCT_LEVELS
CUST_DEPTH = len(CUST.LEVELS)
# Where the promotion levels start, once they are appended. The page splits the
# levels into chains at these two marks: customer, then product, then promotion.
PROMO_AT = len(FILTERS)

# The five figures the chart is made of, plus the denominator of the line. Each
# is looked up by header with the spellings the export has used, and the build
# prints what it matched.
SERIES = [
    ('gross',     'Gross Sales', ('*S.Gross Sales', '*Gross Sales', 'Gross Sales',
                                  'S.Gross Sales AMT', '*Net Sales', 'Net Sales')),
    ('deduction', 'Sales Deduction', ('*Sales Deduction', 'Sales Deduction',
                                      '*Delear Discount')),
    ('cogs',      'COGS', ('*Cost of Goods Sold', 'Cost of Goods Sold', 'COGS',
                           '*Ref. CoGS')),
    ('opex',      'Operating Cost', ('*Operating Expense', 'Operating Expense',
                                     'Operating Cost', '*Operating Cost',
                                     '*Other Expense')),
    ('profit',    'Operating Profit', ('*Operating Profit', 'Operating Profit',
                                       'Subsidiary Op.Profit')),
    # The denominator of the profit line, kept apart from the gross figure:
    # the line is profit over net sales, not over gross.
    ('net',       'Net Sales', ('*Net Sales', 'Net Sales', 'Net Sales Amt')),
    # And the denominator of every per-unit figure, ASP among them.
    ('qty',       'Qty', ('Quantity(Net)', 'Net Sales Qty', 'Qty', 'Quantity')),
]

# The order files' own figures, totalled onto the same key. They are counts of
# what was ordered, not a share of what was sold, so the basis never scales
# them - see ORDERED in the template.
#
# The month is modelled as: what its own orders booked, plus what the month
# before carried into it, less what it carries on. `tools/cohort.py` tested that
# reading against the month it claims to explain and it came back at 99% of the
# units, so it is the one the page runs on.
ORDER_SERIES = [
    ('oqty', 'Booked Qty (this month\'s orders)'),
    ('oamt', 'Booked (this month\'s orders)'),
    ('iqty', 'Carried-in Qty'),
    ('iamt', 'Carried in'),
    ('xqty', 'Carried-out Qty'),
    ('xamt', 'Carried out'),
]
N_ORDER = len(ORDER_SERIES)

# What brought the order in, as bands of one stack. Read from the promotion
# plan: the lines for that product whose window covers that date, and which
# campaign columns they name. Not from the price - the price rejects lines the
# plan does cover, because a trade-in or a stacked voucher moves what was
# collected away from what the plan quotes.
# Three on the page. The other two stay in the data and come back with
# --promo-bands all: "Nation-wide only" and "Not in the plan" are real and
# different - the plan saying nothing is not the plan saying there was no
# promotion - but three bands is what this is read for, and the distinction is
# kept rather than thrown away.
# The bands are a partition, not a nest: every unit is in exactly one of them,
# and "DTC + Nation-wide" does not contain "DTC only" - it is the DTC units
# that had a nation-wide campaign running over them as well. Named as a pair
# so that reads off the legend: all the DTC business is the two together, and
# the same campaign can appear in both, split by whether a nation-wide one
# overlapped it.
PROMO_LABEL = {
    'pdtc':  'DTC only',
    'pboth': 'DTC + Nation-wide',
    'pnat':  'Nation-wide only',
    'pnone': 'No promotion',
    'pgap':  'Not in the plan',
}
# What each band folds to when only three are shown. The two that fold are the
# ones that say "no DTC promotion brought this in", which is what the third
# band means on a page read for DTC.
PROMO_FOLD = {'pnat': 'pnone', 'pgap': 'pnone'}
PROMO_ORDER = ('pboth', 'pdtc', 'pnat', 'pnone', 'pgap')
# The levels the promotion adds to the key. Two, so the first splits the bar
# and the second is what a bar opens into - the same shape as the customer and
# product chains, and driven by the same code.
# Three levels, not two. The plan's two DTC columns are a hierarchy - the first
# names the campaign, the second what ran inside it - so they are two levels and
# a bar on one opens by the other. Joined into a single "A + B" value they were
# neither campaign, and there was nothing to open.
PROMO_LEVELS = [('Promotion', 'promoband', ()),
                ('DTC campaign 1', 'promocamp1', ()),
                ('DTC campaign 2', 'promocamp2', ())]
# What the orders could not band is not a fourth thing to look at: no DTC
# promotion brought it in, which is what the third band says. It reads as
# "No promotion" and only --promo-bands all keeps it apart.
NO_ORDER = 'No promotion'
NO_ORDER_ALL = '(no order matched)'
NO_CAMPAIGN = '(no campaign)'
# A blank second column is the plan saying there was no second campaign, which
# is a different statement from the first one being blank as well.
NO_SECOND = '(no second campaign)'
# And a blank *first* column over a filled second one is a third statement
# again: there is a campaign, the plan wrote it in the other column. CE does
# that for whole programmes - Tech Upgrade, BOOST WEEK, SECRET SALE - and 3,374
# lines across the two plans are like it. Reading that as "(no campaign)" said
# the opposite of what the plan holds; this says where to look, and clicking
# the band drills to the column that names it.
ONLY_SECOND = '(named in campaign 2)'


# How many campaign names the drill carries. Bounded on purpose: one series per
# campaign on every combination is what makes a payload too big to open, and the
# tail of a campaign list is a long run of ones.
PROMO_TOP = 8


# The plan, read once per folder and stem set. Two readers ask it different
# questions - the promotion split asks which campaign a date sat in, the list
# price asks what the product was meant to sell for - and a build over nine
# months would otherwise read the same file eighteen times.
_PLANS: dict = {}


def plan_once(folder, stems, say=print) -> tuple:
    """(plan, meta), or (None, None) when the folder has no plan file."""
    key = (str(folder), tuple(stems))
    if key not in _PLANS:
        try:
            _PLANS[key] = PM.load_plans(Path(folder), list(stems), say=say)
        except Exception:
            _PLANS[key] = (None, None)
    return _PLANS[key]


def month_window(ym: int) -> tuple:
    """The first and last day of a month, written 2608 or 202608.

    Both spellings are in use - the flags take 2608, the payload carries
    202608 - and a window built on the wrong one lands two thousand years out,
    where every plan line reads as expired and every product falls back to
    whatever price the plan mentions most.
    """
    y, m = ym // 100, ym % 100
    y += 2000 if y < 100 else 0
    first = date(y, m, 1)
    return first, date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def rrp_by_sku(plan, skus, ym, say=print) -> dict:
    """{SKU: list price} for this month, read off the promotion plan.

    The plan is the one file in the folder that states what a product was meant
    to sell for; the profit export states what was collected, which is the
    question ASP answers. Keeping them apart is the point - the gap between the
    two is the discount, and a book that carried only one of them cannot show
    it.

    A line counts when its window touches the month. A product with no line
    live in the month falls back to whatever else the plan says about it,
    because a list price does not stop existing between campaigns. Where the
    lines disagree the commonest value wins: the same product is planned many
    times over, and one mistyped line should not become the price.
    """
    # A folder with no plan in it, or a plan with nothing live in it: there is
    # no list price to report and no line worth printing about it, because
    # promo_bander has already said the plan is missing.
    if plan is None or not getattr(plan, 'rows', None) or not ym:
        return {}
    first, last = month_window(ym)
    out = {}
    # Two ways to have no list price, and they are not the same finding: a
    # product the plan has never heard of, and one the plan plans without ever
    # quoting an RRP. The first is a gap in the plan's coverage, the second a
    # gap in its RRP column, and only the second is answered by filling a cell
    # in - so they are counted apart rather than both reading as "no RRP".
    unknown, unpriced = [], []
    for sku in skus:
        cands, _ = plan.candidates(PM.code_norm(sku))
        priced = [(c, v) for c in cands
                  if (v := (c.get('prices') or {}).get('RRP'))]
        if not priced:
            (unpriced if cands else unknown).append(sku)
            continue
        live = [v for c, v in priced
                if (not c['start'] or c['start'] <= last)
                and (not c['end'] or c['end'] >= first)]
        pool = live or [v for _, v in priced]
        tally: dict = {}
        for v in pool:
            tally[v] = tally.get(v, 0) + 1
        # Commonest first, and the higher price where even that ties - a list
        # price that is wrong high is visible as a discount that is too big,
        # where one that is wrong low reads as a product sold above list.
        out[sku] = max(tally, key=lambda v: (tally[v], v))
    if skus:
        say(f'  list price: {len(out):,} of {len(skus):,} SKU(s) have an RRP '
            f'in the plan')
        for miss, what in ((unknown, 'not in the plan at all'),
                           (unpriced, 'planned, but no RRP on the line')):
            if miss:
                say(f'    {len(miss):,} {what}: ' + ', '.join(miss[:8])
                    + (f' ... and {len(miss) - 8} more' if len(miss) > 8 else ''))
        if unknown or unpriced:
            say('    a blank RRP cell is the plan saying nothing, not the '
                'product having no list price - py dashboard\\build_pnl.py '
                '--rrp <code> says which')
    return out


def say_rrp(plan, code: str, ym: int) -> None:
    """Everything the plan says about one product's price, and nothing else.

    The workbook leaves a cell empty where the plan is silent, and empty reads
    the same whichever silence it was: a product the plan never lists, a
    product listed with every price column but RRP, or a product whose only
    lines expired before the month. This says which, by name, so the answer to
    "has this really no list price?" is read off the file rather than guessed.
    """
    print(f'\nwhat the plan says about {code!r}:')
    if plan is None or not getattr(plan, 'rows', None):
        print('  no plan was read, so nothing - pass --plan with the stems of '
              'the plan files in the folder')
        return
    norm = PM.code_norm(code)
    cands, how = plan.candidates(norm)
    print(f'  code read as {norm!r}')
    if cands:
        print(f'  matched by {how}')
    if not cands:
        # The near misses, because a code the plan carries under one spelling
        # is a different problem from a product the plan never planned.
        near = sorted({c['sku'] for c in plan.rows
                       if c['code'][:6] == norm[:6]})[:8]
        print('  no plan line for it' + (f'  (nearest by code: '
                                         f'{", ".join(near)})' if near else ''))
        return
    first, last = month_window(ym) if ym else (None, None)
    print(f'  {len(cands)} plan line(s)' + (f', month {first} .. {last}'
                                            if first else ''))
    for c in cands:
        live = (first is None
                or ((not c['start'] or c['start'] <= last)
                    and (not c['end'] or c['end'] >= first)))
        window = (f'{c["start"] or "-"} .. {c["end"] or "-"}')
        prices = ', '.join(f'{k}={v:,.0f}' for k, v in
                           sorted((c.get('prices') or {}).items())) or 'none'
        print(f'    {c["promo"]}  [{window}]'
              f'{"" if live else "  (outside the month)"}')
        print(f'      {prices}')
    rrps = sorted({v for c in cands if (v := (c.get('prices') or {}).get('RRP'))})
    if not rrps:
        print('  -> RRP: no line quotes one, so the workbook leaves it empty')
        return
    # What the sheet actually writes, through the same function that writes it
    # - a diagnostic that reasons about the answer separately is a second
    # implementation, and the two would drift.
    chose = rrp_by_sku(plan, [code], ym, say=lambda *a: None).get(code)
    other = [v for v in rrps if v != chose]
    print(f'  -> RRP on the sheet: {chose:,.0f}'
          + (f'   (the plan also quotes {", ".join(f"{v:,.0f}" for v in other)}'
             f' on other lines)' if other else ''))


# What this report is not about, left out of every build unless --add asks
# for it back. Both were drawing a band on every bar and a dotted margin line
# across the chart, and neither is the DTC business the page is read for:
# Memory is another business, and (blank) is where rows the product master
# could not place end up. A default rather than a flag because it is a
# property of the report, not of one run - and it is not a silent one: every
# build prints what went and how much, and the page says so under the menu.
DROP_DEFAULT = ('Biz=Memory', 'Biz=(blank)')


def parse_rules(rules, flag: str) -> dict:
    """LEVEL=VALUE[,VALUE] strings, as {level index: {VALUE, ...}}.

    By level name as the page prints it, ignoring case and spacing, so
    biz=Memory and "Biz = Memory" are the same instruction. A name that is not
    a level is a stop rather than a silent no-op: a page built without the
    exclusion that was asked for is worse than one that would not build.
    """
    shown = FILTERS + PROMO_LEVELS
    at = {re.sub(r'[^a-z0-9]', '', lbl.lower()): n
          for n, (lbl, _, _) in enumerate(shown)}
    out: dict = {}
    for rule in rules or []:
        if '=' not in rule:
            raise SystemExit(f'{flag} {rule!r}: write it as LEVEL=VALUE, '
                             f'e.g. {flag} "Biz=Memory,(blank)"')
        name, vals = rule.split('=', 1)
        n = at.get(re.sub(r'[^a-z0-9]', '', name.lower()))
        if n is None:
            raise SystemExit(f'{flag} {rule!r}: {name.strip()!r} is not a '
                             f'level. The levels are: '
                             + ', '.join(lbl for lbl, _, _ in shown))
        for v in vals.split(','):
            if v.strip():
                out.setdefault(n, set()).add(v.strip().upper())
    return out


def drop_rules(args) -> dict:
    """What this build leaves out: the defaults, plus --drop, less --add."""
    if getattr(args, 'add_all', False):
        return {}
    rules = parse_rules(list(DROP_DEFAULT) + list(args.drop or []), '--drop')
    for n, vs in parse_rules(args.add, '--add').items():
        if n in rules:
            rules[n] -= vs
            if not rules[n]:
                del rules[n]
    return rules


# How long either side of a campaign is worth counting. A month: long enough
# to be a rate rather than a weekend, short enough that it is still the same
# product at the same price.
SHOULDER = 30


def campaign_watcher(plan, canon):
    """A per-line hook that totals each campaign's products day by day.

    Banding cannot answer what a campaign's products did *before* it opened or
    *after* it closed: outside its window a campaign bands nothing. So this
    does not follow the band - it follows the **products the campaign names**,
    and counts them on every day inside the window and for a month either side
    of it.

    Returns (watch, tally). The tally is {campaign: {'in': {day: [u, a]},
    'before': [u, a, days], 'after': [u, a, days]}}.
    """
    if plan is None or not getattr(plan, 'rows', None):
        return None, {}
    spans: dict = {}
    by_sku: dict = {}
    for r in plan.rows:
        if not r['start'] or not r['end']:
            continue       # a line with no window cannot date a campaign
        for n in (r.get('camp') or []):
            if not n:
                continue
            name = canon.get(n, n)
            spans.setdefault(name, []).append((r['start'], r['end']))
            by_sku.setdefault(r['code'], set()).add(name)

    # A campaign name comes round again: Black Friday ran in 2025 and runs
    # again in 2026, and taking the first start to the last end would draw a
    # fourteen-month window nobody ever ran. The lines are folded into runs
    # instead and a day belongs to the run it falls in.
    #
    # Only overlapping lines merge, with two days of slack for a weekend. A
    # fortnight of slack chained a quarter's worth of short bursts into one
    # run: on the real plans it took 131 runs down to 94 and pushed the 90th
    # percentile from 112 days to 176, which is a campaign nobody ran.
    win: dict = {}
    for name, got in spans.items():
        runs = []
        for a, b in sorted(got):
            if runs and (a - runs[-1][1]).days <= 2:
                if b > runs[-1][1]:
                    runs[-1][1] = b
            else:
                runs.append([a, b])
        win[name] = runs
    tally: dict = {}
    seen = [None, None]

    def watch(sku, day, qty, amt):
        if day is None:
            return
        if seen[0] is None or day < seen[0]:
            seen[0] = day
        if seen[1] is None or day > seen[1]:
            seen[1] = day
        for name in by_sku.get(PM.code_norm(sku), ()):
            runs = win.get(name, ())
            # The run the day is actually inside wins. Taking the first run
            # within a shoulder instead put every October day on a run that
            # closed on 20 September - thirty days of shoulder reach across a
            # month end, and a campaign that comes round each month had its
            # later runs swallowed whole by its first: the run drawn started
            # in September, so nothing of it opened in October.
            hit = next(((a, b) for a, b in runs if a <= day <= b), None)
            if hit is None:
                # Outside every run, the nearest one it shoulders - a day
                # belongs to the run it is closest to, not to whichever is
                # listed first.
                near = None
                for a, b in runs:
                    gap = (a - day).days if day < a else (day - b).days
                    if gap <= SHOULDER and (near is None or gap < near[0]):
                        near = (gap, a, b)
                hit = None if near is None else (near[1], near[2])
            if hit is None:
                continue
            start, end = hit
            t = tally.setdefault((name, start), {
                'in': {}, 'before': [0.0, 0.0], 'after': [0.0, 0.0],
                'win': (start, end)})
            if day < start:
                t['before'][0] += qty
                t['before'][1] += amt
            elif day > end:
                t['after'][0] += qty
                t['after'][1] += amt
            else:
                d = t['in'].setdefault(day.isoformat(), [0.0, 0.0])
                d[0] += qty
                d[1] += amt

    tally['\0seen'] = seen
    return watch, tally


def day_watcher(basis: str = 'mixed', band_of=None, fold: dict | None = None,
                lead: dict | None = None, month_end=None, at: int = 0):
    """A per-line hook that totals the order export by day on the chart's key.

    What the month will be paid for is not one thing measured one way:

        carried in   ordered last month, despatched this one - revenue here,
                     and it sits on the day it left, which is its only day in
                     this month
        this month   ordered this month, on the day it was ordered, which is
                     what the export measures and what a reader means by a
                     day's demand
        rollover     ordered this month and leaving after it - next month's
                     revenue, drawn apart and counted in nothing

    A line that has already left is certain either way. One that has not is
    predicted from its division's average lead time: ordered later than that
    many days before month end, it is a rollover. "Maybe" is the word on the
    chart because that is exactly what it is.

    Two readings come out of the same pass, because they answer different
    questions about the same month:

        payment   what the month will be paid for - carried in, plus this
                  month's orders that leave inside it. The first three buckets
                  above, minus the rollover
        order     what the month took in - every order placed in it, on the
                  day it was placed, whether or not it leaves inside the
                  month. Nothing carried in: that was last month's demand

    Neither is the other's total and they are not added up. A month can take
    good orders and be paid for few of them, and that is the thing worth
    seeing, not an average of the two.

    Returns (daily, tally) with tally {(day, key): [units, amount, roll units,
    roll amount, order units, order amount]}.
    """
    tally: dict = {}
    fold = {} if fold is None else fold
    lead = lead or {}

    def daily(key, gi, made, which, qty, amt, sku):
        roll = False
        if basis in ('gi', 'made'):             # the two older readings
            if which == (SAP.CARRIED_OUT if basis == 'gi' else SAP.CARRIED_IN):
                return
            if which == SAP.OPEN and basis == 'gi':
                return
            day = gi if basis == 'gi' else made
        elif which == SAP.CARRIED_IN:
            day = gi                            # the day it became revenue
        elif which == SAP.CARRIED_OUT:
            day, roll = made, True              # certain: it leaves after
        elif which == SAP.OPEN:
            day = made
            # Not shipped yet, so its division's average decides. A division
            # with no average - nothing of it sold last month - falls back to
            # the figure over everything, and then to not guessing at all.
            div = (key[at] or '').strip()
            days = lead.get(div, lead.get(ALL_DIVS))
            roll = (days is not None and month_end is not None and made
                    and made + timedelta(days=round(days)) > month_end)
        else:                                   # BOOKED: ordered and shipped
            day = made
        if day is None:
            return
        if band_of is not None:
            # Banded on the day it was ordered, not the day it shipped: the
            # promotion was live when the customer bought. That is the rule
            # the month's own banding runs on, kept here so the two agree.
            band, c1, c2 = band_of(sku, made)
            band = fold.get(band, band)
            key = key + (PROMO_LABEL.get(band, band), c1, c2)
        v = tally.setdefault((day.isoformat(), key),
                             [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        v[2 if roll else 0] += qty
        v[3 if roll else 1] += amt
        # The order reading: everything placed this month, on the day it was
        # placed. Carried in is last month's demand and is no part of it.
        if basis == 'mixed' and which != SAP.CARRIED_IN:
            v[4] += qty
            v[5] += amt

    return daily, tally


def day_payloads(tally: dict, basis: str, ym: int, source: str,
                 banded: bool = False, drops: dict | None = None,
                 asof=None, say=print) -> list:
    """One payload per day, in the shape a month payload has.

    The page unifies the two sets together and then splits them, so a day has
    to arrive looking like a month: the same levels in the same order, members
    by name, and combinations indexing into them. Then every control the
    monthly chart has - the drill, the split, the percent scale, the running
    total - works on days without knowing that it is.
    """
    if not tally:
        return []
    levels = FILTERS + (PROMO_LEVELS if banded else [])
    # The same values the page leaves out of the months - Memory, the blanks,
    # anything else --drop names. A chart that drew them on days and not on
    # months would be two charts about two different businesses.
    if drops:
        gone = {k for k in tally
                if any(k[1][n].strip().upper() in vs
                       for n, vs in drops.items() if n < len(k[1]))}
        for k in gone:
            del tally[k]
        if gone:
            say(f'  --drop took out {len(gone):,} of the day rows as well')
        if not tally:
            return []
    names: list = [[] for _ in levels]
    index: list = [{} for _ in levels]
    for _, key in tally:
        for i, part in enumerate(key[:len(levels)]):
            if part not in index[i]:
                index[i][part] = len(names[i])
                names[i].append(part)
    lv = [{'name': levels[i][0], 'values': names[i]} for i in range(len(levels))]
    # Units and the order's own money. Not gross sales: the order export is not
    # the profit export, and a figure called Gross Sales that is neither would
    # be read as the one the rest of the page draws.
    series = [{'key': 'qty', 'label': 'Order Qty'},
              {'key': 'gross', 'label': 'Order Value'},
              # Drawn apart and counted in nothing: it is next month's
              # revenue, and a KPI that added it would be claiming money the
              # month will not be paid.
              {'key': 'rqty', 'label': 'Maybe rollover (qty)'},
              {'key': 'rgross', 'label': 'Maybe rollover'}]
    if basis == 'mixed':
        # The month as orders rather than as revenue. Not a total to add to
        # the others - a second reading of the same lines.
        series += [{'key': 'oqty', 'label': 'Ordered (qty)'},
                   {'key': 'ogross', 'label': 'Ordered'}]
    by_day: dict = {}
    for (day, key), v in tally.items():
        by_day.setdefault(day, {})[key] = v
    # Nothing after the day the export was taken. On the order date there is
    # nothing there anyway; on the despatch date there is, and it is a
    # schedule - a bar drawn from it says the month sold something it has not.
    if asof:
        late = sorted(d for d in by_day if d > asof.isoformat())
        for d in late:
            del by_day[d]
        if late:
            say(f'  the export was taken {asof.isoformat()}; {len(late)} '
                f'day(s) after it are a despatch plan and are left off')
    if not by_day:
        return []
    out = []
    for day in sorted(by_day):
        y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
        rows = by_day[day]
        out.append({
            # YYYYMMDD marks it as a day and orders the columns; ym stays the
            # real month so anything that reads one still can.
            'd': y * 10000 + m * 100 + d,
            'ym': y * 100 + m,
            'month': f'{d} {MONTHS[m - 1]}',
            'title': f'{MONTHS_LONG[m - 1]} {y} Orders, by day',
            'file': source,
            'rows': len(rows),
            'custDepth': CUST_DEPTH,
            # No promotion chain and no carry-in on a day: both are answers
            # about a month, and the page switches those buttons off itself
            # when the levels are not there.
            'promoAt': PROMO_AT if banded else None,
            'carryIn': False,
            'asof': asof.isoformat() if asof else None,
            # Which day it is. The page says so under the chart, because the
            # answer decides whether the days add up to the month.
            'dayBasis': basis,
            'levels': lv,
            'series': series,
            'combos': [{'k': [index[i][k[i]] for i in range(len(levels))],
                        'n': 1, 'v': [round(x) for x in v]}
                       for k, v in rows.items()],
        })
    lo, hi = sorted(by_day)[0], sorted(by_day)[-1]
    what = {'gi': 'the day each order left',
            'made': 'the day each order was placed'}.get(
                basis, "last month's orders on the day they left, this "
                       "month's on the day they were placed")
    say(f'\n  by day, on {what}:\n    {len(out)} day(s), {lo} .. {hi}, '
        f'{sum(len(r) for r in by_day.values()):,} combination(s)')
    roll = sum(v[3] for r in by_day.values() for v in r.values())
    kept = sum(v[1] for r in by_day.values() for v in r.values())
    took = sum(v[5] for r in by_day.values() for v in r.values())
    if roll:
        say(f'    {kept:,.0f} counted; {roll:,.0f} leaves after the month and '
            'is drawn dashed, out of the total')
    if took:
        say(f'    on orders placed this month instead: {took:,.0f}')
    return out


def read_fx(folder: Path, stem: str, say=print) -> dict:
    """{YYYYMM: rate} off a two-column file: a month, and what a dollar is.

    The page draws one currency at a time and converts a whole month at its
    own rate, so a month with no rate is not a month converted badly - it is
    a month the button has to stay off for, and the build says which.
    """
    path = pick_file(folder, stem)
    if path is None:
        return {}
    try:
        rows, _ = read_any(path)
    except (ValueError, OSError) as e:
        say(f'  {path.name}: {e} - no currency button')
        return {}
    if not rows:
        return {}
    head = [h.strip() for h in rows[0]]
    mi = find(head, 'month', 'Month', 'ym', 'YM', 'Period')
    ri = find(head, 'Rate', 'rate', 'FX', 'fx', 'USD', 'Exchange Rate')
    if mi is None or ri is None:
        say(f'  {path.name}: needs a month column and a rate column - it has '
            + ', '.join(h for h in head if h)[:120])
        return {}
    out = {}
    for r in rows[1:]:
        m = parse_number(r[mi].strip() if mi < len(r) else '')
        v = parse_number(r[ri].strip() if ri < len(r) else '')
        if m is None or v is None or v <= 0:
            continue                       # a month not set yet, left blank
        m = int(m)
        ym = m if m > 9999 else (2000 + m // 100) * 100 + m % 100
        out[ym] = v
    say(f'  {path.name}: {len(out)} month(s) with a rate, '
        f'{min(out.values()):.5f} .. {max(out.values()):.5f}' if out
        else f'  {path.name}: no month has a rate')
    return out


def day_chart(folder, args, cust: dict, prod: dict, say=print) -> list:
    """The daily chart, read off the order export on its own terms.

    Not a finer cut of a month the profit exports closed: the orders run ahead
    of them - October's orders are there while October's P&L is not - so the
    day chart is built for the month the order export covers and stands beside
    the monthly chart rather than inside it.
    """
    if args.no_days or args.no_sap:
        return []
    files = sorted(pick_series(folder, args.sap), key=lambda q: q.name)
    seen: set = set()
    files = [f for f in files
             if not (f.stem.lower() in seen or seen.add(f.stem.lower()))]
    if not files:
        return []
    months = {}
    for f in files:
        m = month_of([], [], f.stem, say=lambda *a: None)
        if m:
            months.setdefault(m, []).append(f)
    if args.day_month:
        want = int(args.day_month)
        want = want if want > 9999 else 202000 + want % 10000
        want = (want // 100) * 100 + want % 100
        if want not in months:
            say(f'\n--day-month {args.day_month} is not in the order export - '
                f'it carries ' + ', '.join(str(m) for m in sorted(months)))
            return []
    elif months:
        want = max(months)                      # the latest month it carries
    else:
        say('\nno month could be read off the order export, so no daily chart')
        return []
    say(f'\nthe daily chart, off {", ".join(f.name for f in months[want])} '
        f'({want}):')
    bander = (None if args.no_promo
              else promo_bander(folder, args.plan, say=lambda *a: None))
    # Last month's lead time per Div 1, which is what says whether an order
    # placed near this month's end will leave inside it. Measured, not
    # assumed: tools/lead_time.py is the same reading, printed.
    lead = {}
    if args.day_basis == 'mixed':
        lead = LT.average_days(folder, month_before(want), cust, prod,
                               by='div1', sap=args.sap,
                               say=lambda *a: None)
        if lead:
            rest = lead.get(ALL_DIVS)
            shown = sorted(((k, v) for k, v in lead.items() if k != ALL_DIVS),
                           key=lambda kv: -kv[1])
            say(f'  lead time off {month_before(want)}, days to despatch: '
                + ', '.join(f'{k} {v:.1f}' for k, v in shown[:8])
                + ('' if rest is None else f'; anything else {rest:.1f}'))
        else:
            say(f'  no {month_before(want)} orders to measure a lead time '
                'from, so nothing is called a rollover')
    # The campaigns the open month's own orders ran under. Without this the
    # page only knows the campaigns of months that have a profit export, so
    # the one month a reader is watching has none of them - which is the month
    # the question is about.
    _plan = None if args.no_promo else plan_once(folder, args.plan,
                                                 lambda *a: None)[0]
    watch, by_day = campaign_watcher(
        _plan, PM.canon_campaigns(_plan.rows, say=lambda *a: None)
        if _plan else {})
    daily, tally = day_watcher(
        args.day_basis, bander,
        {} if args.promo_bands == 'all' else PROMO_FOLD,
        lead=lead, month_end=month_window(want)[1],
        at=len(CUST.LEVELS) + [n for n, _, _ in PRODUCT_LEVELS].index('Div 1'))
    got = SAP.load(
        months[want], month=want, cust_levels=CUST.LEVELS,
        prod_levels=PRODUCT_LEVELS, customers=cust, products=prod,
        currency=args.currency,
        skip_sku=tuple(t.strip().upper()
                       for t in args.skip_sku.split(',') if t.strip()),
        daily=daily, watch=watch, marketplace=not args.no_marketplace,
        say=lambda *a: None)
    if got is None:
        say('  the order export could not be read as orders')
        return []
    # Which column the money on this chart and in the achievement table came
    # from. The reader was silenced to keep the run short and that took this
    # with it - and "where does Actual to date come from" is a question the
    # build should answer without being asked.
    SAP.say_other(got, want, kept=not args.no_marketplace, say=say)
    say(f'  the money is {got.amount_col or "-- no money column --"}'
        + ('' if got.amount_col else
           ', so every amount here is zero')
        + (f'; --currency picks another' if got.amount_col else ''))
    out = day_payloads(tally, args.day_basis, want,
                       ', '.join(f.name for f in months[want]),
                       banded=bander is not None, drops=drop_rules(args),
                       asof=got.asof, say=say)
    if bander is None:
        say('  no promotion plan, so the daily chart has no band on it')
    say(f'  {got.counted:,} of {got.lines:,} line(s) counted - the rest are '
        'another month, a marketplace, or rejected')
    # On the first day only: the page gathers campaigns across every payload,
    # and the same dictionary on all thirty-one would count every campaign day
    # thirty-one times over.
    if out:
        # What this chart does not count, and whose it was. The order export
        # is the store's own orders; a marketplace line carries someone else's
        # reference and is dropped before anything is totalled. Narrow to a
        # customer that sells only through a marketplace and the result is an
        # empty chart, which looks exactly like a customer that sold nothing.
        # Carried to the page so it can say which.
        out[0]['offStore'] = {
            'kept': not args.no_marketplace,
            'total': [got.other[0], round(got.other[1]), round(got.other[2])],
            'who': {k: [v[0], round(v[1]), round(v[2])]
                    for k, v in sorted(got.other_who.items(),
                                       key=lambda kv: -kv[1][2])[:400]},
        }
        found = campaign_payload(by_day, folder, args)
        out[0]['campaigns'] = found
        opened = [k for k, v in found.items()
                  if (v.get('start') or '')[:7]
                  == f'{want // 100}-{want % 100:02d}']
        if found:
            say(f'  {len(found)} campaign(s) touched the month'
                + (f', {len(opened)} opened in it: '
                   + ', '.join(sorted(opened)[:5])
                   + (' ...' if len(opened) > 5 else '')
                   if opened else ' and none opened in it'))
    return out


def campaign_payload(by_day: dict, folder, args) -> dict:
    """{campaign: {start, end, days: {day: [units, amount]}}}.

    Only the days inside the campaign's own window: a day after it closed is
    an order banded on a line whose dates say otherwise, and drawing it would
    say the campaign was still running.
    """
    seen = by_day.pop('\0seen', [None, None]) if by_day else [None, None]
    out: dict = {}
    # One entry per campaign name, since that is what the page's level holds:
    # where a name ran twice, the run that sold the most is the one drawn.
    best: dict = {}
    for (name, _), t in (by_day or {}).items():
        if re.match(r'^\(.*\)$', str(name).strip()):
            continue            # a placeholder, not a campaign
        units = sum(v[0] for v in t['in'].values())
        if name not in best or units > best[name][0]:
            best[name] = (units, t)
    for name, (_, t) in best.items():
        start, end = t['win']
        days = {d: [round(v[0]), round(v[1])] for d, v in sorted(t['in'].items())}
        if not days and not t['before'][0] and not t['after'][0]:
            continue
        # How many days either side the data actually covers. Dividing a
        # month's units by thirty days the export never held would quote a
        # rate the business never ran at.
        def covered(lo, hi):
            if seen[0] is None:
                return 0
            lo, hi = max(lo, seen[0]), min(hi, seen[1])
            return max(0, (hi - lo).days + 1)
        out[name] = {
            'start': start.isoformat(), 'end': end.isoformat(),
            'days': days,
            'before': [round(t['before'][0]), round(t['before'][1]),
                       covered(start - timedelta(days=SHOULDER),
                               start - timedelta(days=1))],
            'after': [round(t['after'][0]), round(t['after'][1]),
                      covered(end + timedelta(days=1),
                              end + timedelta(days=SHOULDER))],
        }
    return out


def apply_drops(combos, counts, rules, keys, say=print) -> list:
    """Take the dropped values out, and say what went with them.

    At the end, once every source has been merged in, so a value excluded from
    the sales side cannot come back through the order side carrying a booking
    - which is exactly what a filter applied earlier would have let happen.
    """
    if not rules:
        return []
    gone, rows, amount = [], 0, 0.0
    at = keys.index('net') if 'net' in keys else (
        keys.index('gross') if 'gross' in keys else None)
    # The spellings actually taken out, rather than the ones typed at the
    # flag: "memory" was the instruction, Memory is what left the page.
    hit: dict = {}
    for k in [k for k in combos
              if any(k[n].strip().upper() in vs for n, vs in rules.items()
                     if n < len(k))]:
        for n, vs in rules.items():
            if n < len(k) and k[n].strip().upper() in vs:
                hit.setdefault(n, set()).add(k[n])
        rows += counts.pop(k, 0)
        amount += combos.pop(k)[at] if at is not None else 0
        gone.append(k)
    shown = FILTERS + PROMO_LEVELS
    said = [f'{shown[n][0]}: ' + ', '.join(sorted(vs))
            for n, vs in sorted(hit.items())]
    say('\nleft out of this page: '
        + ('; '.join(said) if said else 'nothing matched')
        + '   (--add brings one back, --add-all draws the file as it is)')
    if said:
        say(f'  {len(gone):,} combination(s), {rows:,} row(s)'
            + (f', {amount:,.0f} in net sales' if at is not None else '')
            + ' - out of the bars, the totals and the workbook alike')
    # A value that matched nothing is a typo or a value this month does not
    # have, and the difference matters: the first leaves the page carrying what
    # was meant to be excluded, and nothing on the page would say so.
    for n, vs in sorted(rules.items()):
        missed = sorted(v for v in vs
                        if not any(g.strip().upper() == v
                                   for g in hit.get(n, ())))
        if missed:
            say(f'  {shown[n][0]}: nothing to drop for '
                + ', '.join(repr(v) for v in missed)
                + ' - no row of this export carries it')
    return said


def campaign_windows(plan, canon) -> dict:
    """{campaign: [first day, last day]} over the plan's own lines.

    A campaign is many lines - one per product, often one per tier - and they
    do not all start together: the window the page draws is the first day any
    of them opens to the last day any of them closes, which is the campaign as
    a customer met it.
    """
    out: dict = {}
    for r in (plan.rows if plan else []):
        for n in (r.get('camp') or []):
            if not n:
                continue
            name = canon.get(n, n)
            v = out.setdefault(name, [None, None])
            if r['start'] and (v[0] is None or r['start'] < v[0]):
                v[0] = r['start']
            if r['end'] and (v[1] is None or r['end'] > v[1]):
                v[1] = r['end']
    return out


def promo_bander(folder, stems, say=print):
    """(sku, date) -> which promotion band, or None when there is no plan.

    One cache per product and month, because an export asks the same question
    tens of thousands of times and the answer only changes with the window.
    """
    plan, meta = plan_once(folder, stems, say)
    if plan is None:
        return None
    if not meta or not plan.rows:
        say(f'  no plan file matching {", ".join(stems)}, so the page cannot '
            f'split by promotion')
        return None
    say(f'  promotion plan: {len(plan.rows):,} live line(s) over '
        f'{len(plan.by_code):,} product code(s)')
    # One spelling per campaign. `DTC Boost week` and `DTC Boost Week` are one
    # campaign and came out as two bars; the commonest spelling in the plan
    # wins, read off the plan rather than from a table here.
    canon = PM.canon_campaigns(plan.rows, say=say)
    cache: dict = {}

    def band(sku, day):
        if day is None:
            # No date, so no window can be tested - an absence of information
            # about this line, not a finding about it.
            return ('pgap', NO_CAMPAIGN, NO_CAMPAIGN)
        k = (PM.code_norm(sku), day.year, day.month, day.day)
        hit = cache.get(k)
        if hit is not None:
            return hit
        # Both answers come out together: which band, and which campaign inside
        # it. One walk of the plan lines answers both, and it is the same walk
        # the profit split and the ASP sheet make - see PM.plan_state.
        live, nat, dtc = PM.plan_state(plan, k[0], day)
        hit = ('pboth' if (dtc and nat) else 'pdtc' if dtc
               else 'pnat' if nat
               # A live line that names no campaign says there was none. No
               # live line at all says nothing either way.
               else 'pnone' if live else 'pgap')
        # And which DTC campaign, for the drill - each column on its own, so
        # one opens into the other. Spelled one way; a product in two campaigns
        # at once on the same date keeps both, because picking one would be
        # inventing a precedence the plan does not state.
        one = PM.campaign_names(live, canon, 1)
        two = PM.campaign_names(live, canon, 2)
        cache[k] = hit = (hit,
                          one or (ONLY_SECOND if two else NO_CAMPAIGN),
                          two or (NO_SECOND if one else NO_CAMPAIGN))
        return hit

    return band

MONTHS_LONG = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
               'August', 'September', 'October', 'November', 'December')
# Short, for the month buttons on the page.
MONTHS = tuple(m[:3] for m in MONTHS_LONG)


def name_column(folder: Path, args) -> None:
    """Point the Customer name level at the column that names the customer.

    The level itself stays whatever this finds. It went away twice while this
    was conditional on the master, and a search box that is sometimes there is
    worse than one whose list is thin: where nothing names the account, the
    account code stands in, which is still one customer per value and still
    something to search. Only --no-customer-name removes it.

    The level list is a module constant because everything downstream reads
    it, so this is the one place it changes, and it happens before any of that
    downstream work starts.
    """
    global FILTERS, CUST_DEPTH, PROMO_AT

    def without(why: str) -> None:
        global FILTERS, CUST_DEPTH, PROMO_AT
        CUST.LEVELS = [lv for lv in CUST.LEVELS if lv[1] != 'name']
        FILTERS = CUST.LEVELS + PRODUCT_LEVELS
        CUST_DEPTH = len(CUST.LEVELS)
        PROMO_AT = len(FILTERS)
        print(f'the customer drill stops at Type2: {why}')

    if args.no_customer_name:
        return without('--no-customer-name')
    if args.customer_name_column:
        # Named explicitly, so it goes to the front and the usual spellings
        # stay behind it as a fallback.
        CUST.LEVELS = [(n, s, ((args.customer_name_column,) + tuple(names))
                        if s == 'name' else names)
                       for n, s, names in CUST.LEVELS]
    names = next((ns for _, s, ns in CUST.LEVELS if s == 'name'), ())
    for path in pick_series(folder, 'customer'):
        try:
            rows, _ = read_any(path)
        except (ValueError, OSError):
            continue
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        chan = find(head, *CUST.ACCOUNT_NAMES)
        taken = {chan} | {find(head, *ns) for _, s, ns in CUST.LEVELS
                          if ns and s != 'name'}
        taken.discard(None)
        at = find(head, *names)
        how = 'by name'
        if at is None or at in taken:
            # The spellings are a list and the list is always one short. Any
            # header with "name" in it that is not already spoken for is the
            # column, whatever else is around the word - Cust Name, SoldTo
            # Name 1, Name of Customer have all turned up.
            at = next((i for i, h in enumerate(head)
                       if 'name' in h.lower() and i not in taken), None)
            how = 'the only unused header with "name" in it'
        if at is not None and at not in taken:
            print(f'the customer name comes from {head[at]!r} in {path.name}'
                  + ('' if how == 'by name' else f' ({how})'))
            CUST.LEVELS = [(n, s, ((head[at],) + tuple(ns)) if s == 'name'
                            else ns) for n, s, ns in CUST.LEVELS]
            return
        # One file is enough to answer: the masters are the same shape.
        # Nothing is guessed from here - a column picked by shape alone is as
        # likely to be an address as a name - but the shapes are printed, so
        # the next run can name the right one instead of this one asking
        # again.
        print(f'{path.name} has no column naming the customer. Its columns, '
              'widest first:')
        body = rows[1:]
        seen = []
        for i, h in enumerate(head):
            vals = {r[i].strip() for r in body if i < len(r) and r[i].strip()}
            seen.append((len(vals), i, h, sorted(vals)[:2]))
        for n, i, h, eg in sorted(seen, reverse=True)[:8]:
            print(f'    {h or "(blank)":<28}{n:>7} value(s)   '
                  + ', '.join(v[:28] for v in eg))
        print('  the customer name is usually the widest of them: '
              '--customer-name-column "<header>" points the level at it.')
        print('  until then the level carries the account code, which still '
              'names one customer per value')
        return
    print('no customer master could be read, so the customer name level '
          'carries the account code')


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--file', default=None,
                    help='the export to draw (default: the highest-numbered '
                         'profit_* file in the folder)')
    ap.add_argument('--months', metavar='LIST', default=None,
                    help='which months to draw, as 2608,2609 - or, with a minus '
                         'in front, which to leave out: -2609 draws every month '
                         'but September. A month whose sales have not settled '
                         'does not belong on the page beside ones that have')
    # Both default to the month the export turns out to cover, so a new month
    # does not quietly overwrite the last one's page under the last one's name.
    ap.add_argument('--out', default=None,
                    help='default: dashboard/PNL_<MONTH>.html, the month '
                         'the page is read for - the order export\'s where '
                         'there is one, otherwise the newest profit month')
    ap.add_argument('--title', default=None,
                    help="default: the export's month, e.g. September 2026 Profit")
    ap.add_argument('--structure', default=str(ROOT / 'docs' / 'structure.json'),
                    help='the analysis to read; recomputed if it does not match')
    ap.add_argument('--start-channel', metavar='NAME', default=CUST.ONLINE,
                    help=f'the channel the page opens on (default: {CUST.ONLINE}). '
                         'Pass "" to open on all of them.')
    ap.add_argument('--find', metavar='VALUE',
                    help='say where one code appears - which column of the export '
                         'holds it and what the masters have for it')
    ap.add_argument('--rrp', metavar='CODE',
                    help='say what the promotion plan holds for one product '
                         'code - which lines, which windows, which prices - so '
                         'an empty RRP cell in the workbook can be read as the '
                         'plan being silent rather than the product having no '
                         'list price. e.g. --rrp AC100HEHPKG/SA')
    ap.add_argument('--where', metavar='VALUE',
                    help='say where one filter value sits - which Channel, Type '
                         'and so on carry it, and how many rows. e.g. --where GOV')
    ap.add_argument('--cdn', action='store_true',
                    help='link Chart.js instead of embedding it: a smaller file '
                         'that then needs a connection')
    ap.add_argument('--orders', default=None, metavar='NAME',
                    help='the order export for the month the profit file covers. '
                         "By default the one named for that month, e.g. '26 DTC "
                         "Sep' for a September profit file")
    ap.add_argument('--orders-before', default=None, metavar='NAME',
                    help='the month before, whose unfinished orders became this '
                         "month's revenue. By default the one named for it. "
                         'Without it the page cannot say what was carried in')
    ap.add_argument('--sap', default='orders', metavar='STEM',
                    help="SAP's sales-order exports, which carry a despatch "
                         'date and so need no inference at all (default: the '
                         'orders_* files). This is the basis the page prefers')
    ap.add_argument('--no-sap', action='store_true',
                    help="fall back to the store export and its statuses, "
                         'which has to infer which month a unit belongs to')
    ap.add_argument('--any-month', action='store_true',
                    help='model the month with whatever order exports were '
                         'named, even when their dates say they are other '
                         'months. Off by default, because modelling a month '
                         'with the wrong orders is worse than not modelling it')
    ap.add_argument('--positive', default=','.join(ORD.POSITIVE), metavar='LIST',
                    help='order status(es) that book money this month '
                         f'(default {", ".join(ORD.POSITIVE)})')
    ap.add_argument('--negative', default=','.join(ORD.NEGATIVE), metavar='LIST',
                    help='status(es) that take money back this month. The '
                         'profit file counts quantity net of returns, so these '
                         'are subtracted rather than dropped (default '
                         f'{", ".join(ORD.NEGATIVE)})')
    ap.add_argument('--booked', default=None, metavar='LIST',
                    help='read the statuses the old way instead: these book, '
                         'cancelled and returned are dropped, the rest carry. '
                         'py tools\\cohort.py scores the two against the month '
                         'they claim to explain')
    ap.add_argument('--currency', metavar='CODE',
                    help='which money column to read from an order export that '
                         'carries several, e.g. USD. The unit figures - and the '
                         'basis, which is built on them - are unaffected')
    ap.add_argument('--skip-sku', metavar='PREFIX', default='',
                    help='product-code prefixes to leave out of the order side, '
                         'e.g. SMC-AU- for service plans that are ordered but '
                         'never reach the profit file')
    ap.add_argument('--drop', action='append', default=[],
                    metavar='LEVEL=VALUE[,VALUE]',
                    help='leave more whole values out of the page, e.g. '
                         '--drop "Div 3=Service,Gift Card". Out of everything '
                         '- the bars, the totals, the line and the workbook - '
                         'because a value hidden from the bars but kept in the '
                         'totals makes the two disagree. The run says how many '
                         'rows and how much revenue went with it. Repeatable. '
                         'Left out by default: ' + ', '.join(DROP_DEFAULT))
    ap.add_argument('--add', action='append', default=[],
                    metavar='LEVEL=VALUE[,VALUE]',
                    help='add one of those defaults back into the page, e.g. '
                         '--add "Biz=(blank)" to see the rows the product '
                         'master could not place. Repeatable')
    ap.add_argument('--add-all', action='store_true',
                    help='add everything back: draw the file as it is')
    ap.add_argument('--no-returns', dest='returns', action='store_false',
                    help='leave out the credits for goods that came back. '
                         'They are in by default, because the export\'s own '
                         'total carries them and a page that quietly differs '
                         'from the file it names is worse than one with an '
                         'awkward month in it. Taking them out makes a ratio '
                         'easier to read and the totals no longer tie')
    ap.set_defaults(returns=True)
    ap.add_argument('--no-promo', action='store_true',
                    help='leave out the promotion split')
    ap.add_argument('--promo-bands', choices=('three', 'all'), default='three',
                    help='three folds "Nation-wide only" and "Not in the plan" '
                         'into "No promotion" (default); all keeps the five '
                         'apart')
    ap.add_argument('--plan', nargs='+', metavar='STEM',
                    default=list(PM.PLAN_STEMS),
                    help='the promotion plan(s) the promotion split is read '
                         'from (default: ' + ' '.join(PM.PLAN_STEMS)
                         + ', a bar between the names one division has gone by)')
    ap.add_argument('--fx', default='fx_rate', metavar='STEM',
                    help='a month-and-rate file, for the currency button '
                         '(default fx_rate)')
    ap.add_argument('--no-fx', action='store_true',
                    help='leave the currency button off')
    ap.add_argument('--no-days', action='store_true',
                    help='leave the daily chart out. It is built from the '
                         'order export, so a build with no order source has '
                         'none anyway')
    ap.add_argument('--day-month', default=None, metavar='YYMM',
                    help='which month the daily chart covers (default: the '
                         'latest month the order export carries, which is '
                         'usually the open one the P&L has not closed)')
    ap.add_argument('--day-basis', choices=('mixed', 'made', 'gi'),
                    default='mixed', metavar='WHICH',
                    help="which day an order line counts on: mixed, last "
                         "month's orders on the day they left and this "
                         "month's on the day they were placed, with what "
                         'leaves after the month drawn apart (the default); '
                         'or made or gi, every line on one of its two dates')
    ap.add_argument('--target', default=None, metavar='NAME',
                    help='the DTC Blue File cut whose Sokbo is the target line '
                         'on the daily chart (default: the newest DTC_S* '
                         'workbook in the folder, e.g. DTC_S0A_T0B_v1.xlsx)')
    ap.add_argument('--target-version', default=None, metavar='S0x',
                    help='which version column to read (default: the S0x in '
                         'the file name)')
    ap.add_argument('--no-target', action='store_true',
                    help='leave the target line off the daily chart')
    ap.add_argument('--gscm', default='gscm', metavar='STEM',
                    help='the GSCM sheet whose prices the open month is '
                         'measured against (default gscm). --plan is the '
                         'promotion plan and is a different file')
    ap.add_argument('--no-gscm', action='store_true',
                    help='leave the planned-price tables off the page')
    ap.add_argument('--no-orders', action='store_true',
                    help='draw sales only, even when an order export is there')
    ap.add_argument('--shipped', metavar='LIST',
                    help='comma-separated order statuses to count as shipped, '
                         'replacing the built-in list. Everything else is open')
    ap.add_argument('--agree', type=float, default=80.0, metavar='PCT',
                    help='how much of the accounts behind a portal group must '
                         'agree before a level is asserted for it (default 80)')
    ap.add_argument('--columns', action='store_true',
                    help='list what every profit export carries, side by side, '
                         'and stop. The quickest way to see why one month draws '
                         'a figure another one does not')
    ap.add_argument('--no-marketplace', action='store_true',
                    help='count only orders carrying the store\'s own '
                         'reference, leaving Amazon, eBay, Myer and MyDeal '
                         'out of the daily chart and the achievement table. '
                         'They are in by default: a customer on the monthly '
                         'chart belongs on the daily one, and Channel and '
                         'Customer name are where that line gets drawn')
    ap.add_argument('--customer-name-column', default=None, metavar='NAME',
                    help='the customer master column that names the customer, '
                         'where the usual spellings miss it. Account Name is '
                         'not it - that one holds E-STORE and off-line')
    ap.add_argument('--no-customer-name', action='store_true',
                    help='leave the customer name out of the drill. It is the '
                         'deepest level and the one that multiplies '
                         'combinations, so this is the switch to reach for if '
                         'the page gets too heavy to send')
    ap.add_argument('--open', action='store_true')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    name_column(folder, args)
    # One page, every month the folder holds. They stay whole rather than
    # merged: a month has its own customers, its own products and its own
    # levels, and merging them would invent a key that was in neither.
    if args.file:
        targets = [pick_file(folder, args.file)]
    else:
        targets, seen = [], set()
        for cand in pick_series(folder, 'profit'):
            key = re.sub(r'\D', '', cand.stem)[:4]
            if key in seen:
                continue
            seen.add(key)
            targets.append(cand)
        targets.reverse()                       # oldest first, so do the buttons
    targets = [t for t in targets if t]
    if args.months:
        want = [w.strip() for w in args.months.split(',') if w.strip()]
        drop = {w.lstrip('-')[-4:] for w in want if w.startswith('-')}
        keep = {w[-4:] for w in want if not w.startswith('-')}
        left = [t for t in targets
                if re.sub(r'\D', '', t.stem)[:4] not in drop
                and (not keep or re.sub(r'\D', '', t.stem)[:4] in keep)]
        gone = [t.name for t in targets if t not in left]
        if gone:
            print(f'--months leaves out {", ".join(gone)}')
        targets = left
        if not targets:
            print(f'--months {args.months} matched no profit export in '
                  f'{folder.resolve()}', file=sys.stderr)
            return 2
    if not targets:
        print(f'no profit export in {folder.resolve()}', file=sys.stderr)
        return 2

    if args.columns:
        return say_columns(targets)

    months = []
    for target in targets:
        if len(targets) > 1:
            print('\n' + '=' * 72)
        got = build_month(folder, target, args)
        if got is None:
            return 1
        months.append(got)

    # The promotion split used to go to a file of its own, so a new page would
    # not replace the one being read that day. It is the page now, and it
    # keeps the plain name; the odd one out is the build without it.
    tag = '_NOPROMO' if args.no_promo else ''
    # A button that disables itself is indistinguishable from a button that is
    # broken, and this one did exactly that for a whole build: the split was
    # only ever read off the store export, so every run SAP answered produced a
    # page whose Promo button was dead and said nothing about why.
    if not args.no_promo and not any(m.get('promoBands') for m in months):
        print('\nStack by Promo will be OFF on this page: nothing was banded '
              'by promotion.\n  It needs an order source (SAP orders_* or the '
              'store export) and a plan\n  (--plan, default '
              + ' '.join(PM.PLAN_STEMS) + ') that lists the products sold.')
    template = (HERE / 'pnl_template.html').read_text(encoding='utf-8')
    # The days come out of the months that read them and go in beside them:
    # the page unifies both sets together so a member is the same number in
    # each, then splits them back into two views of one payload.
    masters = next((m.pop('_masters') for m in reversed(months)
                    if m.get('_masters')), (None, None))
    for m in months:
        m.pop('_masters', None)
    days = (day_chart(folder, args, masters[0], masters[1])
            if masters[0] is not None else [])
    # The currency button, and what it cannot cover. A month drawn without a
    # rate would be the one AUD column in a USD chart, so the page is told
    # which months are short and keeps the button off rather than mixing.
    fx, fx_missing = {}, []
    if not args.no_fx:
        print('\nthe currency button:')
        fx = read_fx(folder, args.fx)
        if fx:
            want = sorted({m['ym'] for m in months if m.get('ym')}
                          | {d['ym'] for d in days if d.get('ym')})
            fx_missing = [m for m in want if m not in fx]
            if fx_missing:
                print('  no rate for ' + ', '.join(str(m) for m in fx_missing)
                      + ' - the button stays off rather than drawing one '
                      'month in\n  a currency the others are not in')
            else:
                print(f'  every month drawn has a rate '
                      f'({", ".join(str(m) for m in want[:3])}'
                      f'{" .." if len(want) > 3 else ""})')
        elif pick_file(folder, args.fx) is None:
            print(f'  no {args.fx}_* file in the folder, so no currency '
                  'button')
    target = None
    if days and not args.no_target:
        tf = TGT.find_target(folder, args.target)
        if tf is None:
            print('\nno DTC_S* Blue File in the folder, so no target line '
                  '(--target names one)')
        else:
            print('\nthe target line:')
            t = TGT.read_target(tf, args.target_version)
            if t is not None:
                dm = {d['ym'] for d in days}
                if t['ym'] not in dm:
                    print(f"  it is for {t['ym']} and the daily chart is "
                          f"{', '.join(str(x) for x in sorted(dm))} - left off")
                else:
                    target = TGT.split(t, months)
    # Named after the month it is about: PNL_OCT.html while October is the
    # month being traded, whatever the profit exports behind it are dated. The
    # open month is the order export's, because that is the month the page is
    # read for - and taking it off the calendar instead would rename the
    # October page to November on the first of the month, which is exactly
    # when October is still being closed. No year in it, so the folder holds
    # one page per month and a rebuild replaces the page it supersedes.
    name = next((d['ym'] for d in reversed(days or []) if d.get('ym')),
                months[-1].get('ym'))
    out = (Path(args.out) if args.out else HERE / (
        f'PNL_{MONTHS[(name % 100) - 1].upper()}{tag}.html' if name
        else f'PNL{tag}.html'))

    # What the open month was planned to sell at, material by material. The
    # Blue File sets the month's target by product group; this is the same
    # plan one level down, and the only place a price per material is written
    # before the month is traded.
    plan = None
    if days and not args.no_gscm:
        pf = PP.find_plan(folder, args.gscm)
        if pf is None:
            print(f'\nno {args.gscm}_* file in the folder, so no planned '
                  'price to compare against')
        else:
            print('\nthe planned prices:')
            # The month the daily chart draws, since that is the month the
            # comparison is about.
            want = sorted({d['ym'] for d in days})[-1]
            got = PP.read_plan(pf, want)
            if got is not None:
                plan = PP.payload(got)
                # Whether the two files are talking about the same codes. A
                # plan whose materials are spelled differently from the order
                # export joins on nothing and draws an empty table, and that
                # is worth knowing here rather than from a blank card.
                sold = {v.upper() for d in days
                        for lv in d.get('levels', [])
                        if lv.get('name') == 'SKU'
                        for v in lv.get('values', [])}
                hit = [k for k in got['items'] if k in sold]
                print(f'  {len(hit):,} of {len(got["items"]):,} planned '
                      f'material(s) are in the order export'
                      + ('' if hit else
                         ' - the two files do not share a code, so the '
                         'tables would be empty'))
                if not hit:
                    plan = None
    html = template.replace('/*__DATA__*/null',
                            json.dumps({'months': months, 'days': days,
                                        'target': target, 'plan': plan,
                                        'fx': {} if fx_missing else fx,
                                        'fxShort': fx_missing,
                                        # When this page was made. It goes in
                                        # the tab, so a reader with three of
                                        # them open can tell which is the one
                                        # that was sent this morning - and a
                                        # saved copy is named by it.
                                        'built': date.today().isoformat()},
                                       ensure_ascii=False,
                                       separators=(',', ':')))
    if not args.cdn:
        f = HERE / 'vendor' / 'chart.umd.js'
        if f.is_file():
            code = f.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
            html = html.replace(
                '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>',
                f'<script>/* chart.umd.js */\n{code}\n</script>')
        else:
            print('vendor/chart.umd.js missing - the page will need a connection')

    out.write_text(html, encoding='utf-8')
    print(f'\n-> {out.resolve()}  ({len(html.encode("utf-8")) / 1024:,.0f} KB'
          f'{", needs a connection" if args.cdn else ", works offline"})')
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def split_money(combos, keys, oi, ym):
    """What the month earned, split by where the order that earned it came from.

    Each combination is a mix of three things - what the month ordered and
    earned, what the month before sent it, and what it sends on - and the page
    reads any one of them through Basis. This prints the same split outright, so
    the carry-over's own profit is a number on the way past rather than
    something to go and switch to.

    The share is of units, applied to the money: it holds exactly as far as the
    units of one key being worth the same as each other, which is the assumption
    the per-unit view already runs on.
    """
    at = {k: keys.index(k) for k in ('gross', 'net', 'profit', 'qty')
          if k in keys}
    if 'profit' not in at:
        return
    rows = {'its own orders': 0, 'carried in': 2, 'carried out': 4}
    out = {}
    for name, slot in rows.items():
        g = n = pr = q = 0.0
        for v in combos.values():
            month = v[oi] + v[oi + 2]
            if not month:
                continue
            f = v[oi + slot] / month
            q += abs(v[at['qty']]) * f if 'qty' in at else 0
            g += v[at['gross']] * f if 'gross' in at else 0
            n += v[at['net']] * f if 'net' in at else 0
            pr += v[at['profit']] * f
        out[name] = (q, g, n, pr)

    # The file's own total, with no share applied to anything. The two attributed
    # rows only cover combinations that carry an order at all, so the rest - an
    # offline row, a marketplace, a code the two files spell differently - is the
    # difference. Printing it as a residual is what keeps the total exactly the
    # export's: the split is made to add back to the file rather than the file
    # being rebuilt out of the split.
    tot = [0.0] * 4
    for v in combos.values():
        tot[0] += abs(v[at['qty']]) if 'qty' in at else 0
        tot[1] += v[at['gross']] if 'gross' in at else 0
        tot[2] += v[at['net']] if 'net' in at else 0
        tot[3] += v[at['profit']]
    out['no order matched'] = tuple(
        tot[i] - out['its own orders'][i] - out['carried in'][i]
        for i in range(4))

    before = month_before(ym) if ym else '-'
    after = (ym + 1 if ym % 100 < 12 else (ym // 100 + 1) * 100 + 1) if ym else '-'
    label = {'its own orders': f'ordered in {ym} and earned in it',
             'carried in': f'ordered in {before}, earned in {ym}',
             'no order matched': 'no order matched (offline, other)',
             'carried out': f'ordered in {ym}, earns in {after}'}
    print(f'\n  what the month earned, by the month the order came from')
    print(f'  {"":<34} {"units":>10} {"gross":>15} {"op profit":>15} {"margin":>8}')
    for name in ('its own orders', 'carried in', 'no order matched'):
        q, g, n, pr = out[name]
        base = n or g
        print(f'  {label[name]:<34} {q:>10,.0f} {g:>15,.0f} {pr:>15,.0f} '
              + (f'{pr / base * 100:>7.1f}%' if base else f'{"-":>8}'))
    q, g, n, pr = tot
    base = n or g
    print(f'  {"= the month as sold":<34} {q:>10,.0f} {g:>15,.0f} {pr:>15,.0f} '
          + (f'{pr / base * 100:>7.1f}%' if base else f'{"-":>8}')
          + '   <- the export\'s own total')
    q, g, n, pr = out['carried out']
    base = n or g
    print(f'  {label["carried out"]:<34} {q:>10,.0f} {g:>15,.0f} {pr:>15,.0f} '
          + (f'{pr / base * 100:>7.1f}%' if base else f'{"-":>8}')
          + '   <- a projection at this month\'s rates')


def say_columns(targets):
    """What each export carries, and what the others carry that it does not.

    A figure the page draws for one month and not another is nearly always this:
    the exports were cut differently, and the column the figure reads is in one
    and not the other - or is in both and empty in one.
    """
    seen = {}
    for t in targets:
        rows, _ = read_any(t)
        head = [h.strip() for h in rows[0]]
        body = rows[1:]
        total = {}
        for i, h in enumerate(head):
            v = 0.0
            hit = False
            for r in body:
                n = parse_number(r[i].strip() if i < len(r) else '')
                if n is not None:
                    v += n
                    hit = True
            total[h] = v if hit else None
        seen[t.name] = total
        print(f'{t.name}: {len(body):,} rows, {len(head)} columns')

    every = []
    for t in targets:
        for h in seen[t.name]:
            if h not in every:
                every.append(h)
    names = [t.name for t in targets]
    w = max(len(h) for h in every) + 2
    print(f'\n{"column":<{w}}' + ''.join(f'{n[:20]:>22}' for n in names))
    for h in every:
        cells = []
        for n in names:
            v = seen[n].get(h, '--')
            cells.append('-- not in it --' if v == '--'
                         else 'text' if v is None
                         else f'{v:,.0f}')
        flag = ''
        vals = [seen[n].get(h, '--') for n in names]
        if any(v == '--' for v in vals):
            flag = '   <- not in every export'
        elif any(isinstance(v, float) and not v for v in vals) and \
                any(isinstance(v, float) and v for v in vals):
            flag = '   <- empty in one of them'
        print(f'{h:<{w}}' + ''.join(f'{c:>22}' for c in cells) + flag)
    print('\nA figure the page draws for one month and not another is one of '
          'those two lines.')
    return 0


def build_month(folder, target, args):
    """One month, as a payload the page can be switched onto."""
    print('reading:')
    rows, info = read_any(target)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    print(f'  {target.name}: {info["format"]}, {len(body):,} rows, {len(head)} columns')

    ym = month_of(head, body, target.stem)
    if ym:
        print(f'  the month it covers: {ym}')

    cols = A.column_profile(head, body)
    measures = [c['pos'] for c in cols if A.is_measure(c, len(body))]
    print(f'  {len(measures)} amount column(s)')

    # ── the structure, so the five figures are named rather than guessed ───
    saved = None
    sp = Path(args.structure)
    if sp.is_file():
        try:
            saved = json.loads(sp.read_text(encoding='utf-8'))
        except ValueError:
            saved = None
    same = (saved and saved.get('file') == target.name
            and [c['header'] for c in saved.get('columns', [])] ==
            [c['header'] for c in cols])
    if same:
        nodes = saved['nodes']
        print(f'  structure: {len(nodes)} relation(s) from {sp}')
    else:
        if saved:
            print(f'  {sp.name} was built from a different export - redoing it')
        nodes = A.analyse(cols, measures, len(body))

    print('\nthe chart\'s figures:')
    series, pos_of = [], {}
    # Every amount column's total, once. A figure that matched a column holding
    # nothing is worse than one that matched nothing at all: it draws as zero
    # and reads as "this month had no sales deduction" rather than as a column
    # that wants looking at - and the money is usually in a column next to it.
    col_total: dict[int, float] = {}
    for i in measures:
        t = 0.0
        for r in body:
            v = parse_number(r[i].strip() if i < len(r) else '')
            if v is not None:
                t += v
        col_total[i] = t

    empty = []
    for key, label, names in SERIES:
        i = find(head, *names)
        total = col_total.get(i, 0.0) if i is not None else 0.0
        if i is not None and i not in col_total:          # not read as a measure
            for r in body:
                v = parse_number(r[i].strip() if i < len(r) else '')
                if v is not None:
                    total += v
        col = head[i] if i is not None else '-- not found --'
        print(f'  {label:17} {col:<24}'
              + ('' if i is None else f'{total:>16,.0f}'
                 + ('' if total else
                    '   <- matched, but every row of it is empty or zero')))
        if i is not None:
            pos_of[key] = i
            series.append({'key': key, 'label': label})
            if not total:
                empty.append((label, head[i]))

    # Where the money went instead: the biggest amount columns no figure claimed.
    if empty:
        claimed = set(pos_of.values())
        spare = sorted(((t, i) for i, t in col_total.items()
                        if i not in claimed and abs(t) > 0),
                       key=lambda x: -abs(x[0]))[:8]
        print(f'\n  {len(empty)} figure(s) matched a column that holds nothing: '
              + ', '.join(f'{lbl} ({c})' for lbl, c in empty))
        if spare:
            print('  the biggest amount columns no figure is reading:')
            for t, i in spare:
                print(f'    {head[i]:<28} {t:>16,.0f}')
            print('  if one of those is the figure, add its name to SERIES in '
                  'dashboard/build_pnl.py.')
    if not {'gross', 'profit'} <= set(pos_of):
        print('\nWithout a gross figure and an operating profit there is nothing '
              'to draw.', file=sys.stderr)
        print('Headers seen:', ', '.join(head[:40]), file=sys.stderr)
        return None

    # Say out loud whether the four bars actually account for the profit line.
    if {'deduction', 'cogs', 'opex'} <= set(pos_of):
        derived = {n['pos'] for n in nodes}
        print('  operating profit '
              + ('is a total the analysis broke down, so the bars and the line '
                 'come from one statement'
                 if pos_of['profit'] in derived else
                 'stands on its own in this export; the bars are not guaranteed '
                 'to account for it exactly'))

    # ── masters ────────────────────────────────────────────────────────────
    # The newest name is not always the readable one: a workbook saved in a
    # format this build cannot open sits in the folder beside a perfectly good
    # csv. So the candidates are tried in turn and the first that reads wins,
    # with the ones passed over named rather than silently skipped.
    def read_master(prefix, keys, want):
        for cand in pick_series(folder, prefix):
            try:
                got = master(cand, keys, want)
            except (ValueError, OSError) as e:
                print(f'  {cand.name}: {e}\n    - trying the next {prefix} '
                      'export')
                continue
            if got:
                return cand, got
        return None, {}

    print()
    want = {slot: names for _, slot, names in CUST.LEVELS if names}
    want['account'] = CUST.ACCOUNT_NAMES
    cp, cust = read_master('customer', ('Sold-To', 'sold To', 'sold_to'), want)
    print(f'customer master: {cp.name}, {len(cust):,} accounts' if cp
          else 'no customer master could be read')
    pp, prod = read_master('product', ('SKU', 'sku', 'Material'),
                           {slot: names for _, slot, names in PRODUCT_LEVELS})
    print(f'product master: {pp.name}, {len(prod):,} products' if pp
          else 'no product master could be read')

    c_key = find(head, 'Payer', 'sold To', 'Sold-To', 'Customer', 'Customer Code',
                 'Payer Code', 'Sold To Party')
    p_key = find(head, 'Material', 'SKU', 'Material Code', 'Product Number',
                 'Model', 'Model Code', 'Material No', 'Item', 'Product',
                 'Product Code')
    print('\njoining on:')
    for what, i in (('customer', c_key), ('product', p_key)):
        print(f'  {what:9} {head[i] if i is not None else "-- no such column --"}'
              + ('' if i is not None else
                 f'  (nothing will match {what}_2608)'))
    if c_key is None or p_key is None:
        print('  columns in the export: ' + ', '.join(head[:30])
              + (' ...' if len(head) > 30 else ''))
    acct_fb = find(head, *CUST.ACCOUNT_NAMES)
    fallback = [find(head, *names) if names else None for _, _, names in FILTERS]

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    if args.find:
        needle = key_norm(args.find)
        hits: dict[int, int] = {}
        for r in body:
            for i, v in enumerate(r):
                if key_norm(v) == needle:
                    hits[i] = hits.get(i, 0) + 1
        print(f'\nfind {args.find!r} in {target.name}:')
        if not hits:
            print('  not in any column - no row of this export carries it')
        for i, n in sorted(hits.items(), key=lambda kv: -kv[1]):
            tag = (' <- the column joined to the customer master' if i == c_key else
                   ' <- the column joined to the product master' if i == p_key else '')
            print(f'  column [{i}] {head[i]}: {n:,} row(s){tag}')
        for name, m in (('customer_2608', cust), ('product_2608', prod)):
            row = m.get(needle)
            print(f'  {name}: ' + (' / '.join(f'{k}={v or "(blank)"}'
                                              for k, v in row.items())
                                   if row else 'not listed'))
        # The levels are only part of what the master holds. Print the whole
        # row: a value that is plainly there but never reaches a filter is
        # sitting in a column no level reads, and this is where that shows.
        for fname, (mhead, mrows) in RAW.items():
            mkey = find(mhead, 'Sold-To', 'sold To', 'sold_to', 'SKU', 'Material')
            if mkey is None:
                continue
            for r in mrows:
                if key_norm(r[mkey] if mkey < len(r) else '') != needle:
                    continue
                print(f'  {fname}, every column of that row:')
                for i, h in enumerate(mhead):
                    v = r[i].strip() if i < len(r) else ''
                    if not v:
                        continue
                    where = [lbl for lbl, _, names in FILTERS
                             if names and find([h], *names) is not None]
                    if not where and find([h], *CUST.ACCOUNT_NAMES) is not None:
                        where = ['Channel (online or offline)']
                    print(f'    {h:22} {v}'
                          + (f'   -> {where[0]}' if where else
                             '   (no filter level reads this column)'))
                break

    # ── roll up: one row per combination of the filter values ──────────────
    keys = [k for k, _, _ in SERIES if k in pos_of]
    combos: dict[tuple, list[float]] = {}
    counts: dict[tuple, int] = {}
    matched_c = matched_p = 0
    from_master = [0] * len(FILTERS)
    from_export = [0] * len(FILTERS)
    # Goods that came back are in, because the file's own total carries them
    # and a page that quietly differs from the export it names is worse than
    # one with an awkward month in it. --no-returns takes them out for a run
    # where a ratio has to be read cleanly; then the run says what went, and
    # the page says it under the menu, because those totals no longer tie.
    sent_back = {'rows': 0, 'qty': 0.0, 'net': 0.0}
    q_at = pos_of.get('qty')
    n_at = pos_of.get('net', pos_of.get('gross'))
    for r in body:
        if not args.returns and q_at is not None:
            q = parse_number(cell(r, q_at))
            n = parse_number(cell(r, n_at)) if n_at is not None else None
            if is_return(q, n):
                sent_back['rows'] += 1
                sent_back['qty'] += q or 0.0
                sent_back['net'] += n or 0.0
                continue
        c = cust.get(key_norm(cell(r, c_key))) or {}
        p = prod.get(key_norm(cell(r, p_key))) or {}
        matched_c += bool(c)
        matched_p += bool(p)
        src = {**c, **p}
        sku = cell(r, p_key)
        key = [CUST.channel_of(c.get('account') or cell(r, acct_fb), bool(c))]
        from_master[0] += bool(c)
        from_export[0] += not c and bool(cell(r, acct_fb))
        for n, ((_, slot, _), fb) in enumerate(zip(FILTERS, fallback)):
            if n == 0:
                continue
            if slot == 'sku':
                from_export[n] += bool(sku)
                key.append(sku or CUST.BLANK)
                continue
            v = src.get(slot)
            if v:
                from_master[n] += 1
            else:
                v = cell(r, fb)
                from_export[n] += bool(v)
            # Nothing anywhere names this account, so its code stands in: a
            # code is still one customer, where (blank) for all of them is a
            # search box with nothing in it.
            if not v and slot == 'name':
                v = cell(r, c_key)
            key.append(v or CUST.BLANK)
        key = tuple(key)
        vals = combos.get(key)
        if vals is None:
            vals = combos[key] = [0.0] * len(keys)
        counts[key] = counts.get(key, 0) + 1
        for j, k in enumerate(keys):
            n = parse_number(cell(r, pos_of[k]))
            if n is not None:
                vals[j] += n
    if sent_back['rows']:
        print(f'\nreturns left out: {sent_back["rows"]:,} row(s), '
              f'{sent_back["qty"]:,.0f} unit(s), {sent_back["net"]:,.0f} in net '
              f'sales   (--no-returns asked for that; the default keeps them)')
    print(f'\njoined: {matched_c:,} of {len(body):,} rows matched a customer, '
          f'{matched_p:,} matched a product')

    # A join that matches nothing is two codes that were never the same code.
    # Print both sides: the mismatch is usually obvious once they sit together.
    for what, n, i, m, mfile in (('customer', matched_c, c_key, cust, 'customer_2608'),
                                 ('product', matched_p, p_key, prod, 'product_2608')):
        if n or not m:
            continue
        keyed = f'{mfile} is keyed on ' + ', '.join(repr(k) for k in list(m)[:4])
        if i is None:
            print(f'  not one row matched {mfile}: the export has no column this '
                  f'build recognises as a {what} key. {keyed}')
            continue
        theirs = [key_norm(cell(r, i)) for r in body[:2000] if cell(r, i)]
        print(f'  not one row matched {mfile}. '
              + (f'{head[i]!r} holds e.g. ' + ', '.join(repr(k) for k in theirs[:4])
                 if theirs else f'{head[i]!r} is empty on every row')
              + f'; {keyed}')
    print(f'{len(combos):,} filter combination(s) from {len(body):,} rows')

    # ── the other half of the month: what was ordered ──────────────────────
    # The order export knows its portal group and its product; it does not know
    # the payer, so it cannot say which Type2 an order belongs to when the
    # accounts behind a group disagree. Keyed at full depth it would therefore
    # never meet the profit file at all.
    #
    # So an order is spread across the sales that are consistent with it - the
    # combinations that agree on every level the order does assert - in
    # proportion to the units each one sold. An order for 100 EPP units of a SKU
    # lands on the EPP rows of that SKU, in the shape those rows already have.
    # That is an allocation and nothing more; it says where an order could have
    # gone, in the proportions the month itself gives.
    n_measures = len(keys)
    carry_in_known = False

    def merge_orders(by_key, drop=(), add_series=None):
        """Add an order side onto the combinations, spreading only what has to be.

        A SAP key is already at full depth - it came from the payer and the
        material, the same two things the profit file is keyed on - so it lands
        on its own combination. A store-export key carries blanks where the
        portal group could not settle a level, and those are spread across the
        sales they are consistent with, in proportion to what each one sold.
        """
        nonlocal keys, series
        # Which series this merge appends, and so how many slots each key
        # carries. The order side and the promotion side are the same shape of
        # problem - a per-key vector that has to be spread over the sales it is
        # consistent with - so they share the one routine rather than growing a
        # second copy of the spreading.
        add_series = ORDER_SERIES if add_series is None else add_series
        n_add = len(add_series)
        wanted = set(by_key)
        if drop:
            sku_at = len(FILTERS) - 1
            wanted = {k for k in wanted
                      if not str(k[sku_at]).upper().startswith(drop)}
        sold_keys = list(combos)
        qi = keys.index('qty') if 'qty' in keys else None
        width = len(keys)
        for vals in combos.values():
            vals.extend([0.0] * n_add)

        # One index per distinct set of levels a key asserts. There are only a
        # handful, and building them once beats walking every combination.
        index: dict[tuple, dict] = {}
        exact = spread_u = orphan_u = 0.0
        orphans = 0
        for ok in wanted:
            v = list(by_key[ok])
            units = sum(v[i] for i in range(0, len(v), 2)) \
                if n_add == N_ORDER else sum(v)
            known = tuple(j for j, x in enumerate(ok) if x != CUST.BLANK)
            idx = index.get(known)
            if idx is None:
                idx = index[known] = {}
                for ck in sold_keys:
                    idx.setdefault(tuple(ck[j] for j in known), []).append(ck)
            hits = idx.get(tuple(ok[j] for j in known)) or []
            if len(hits) == 1 and hits[0] == ok:
                exact += units
            if not hits:
                orphans += 1
                orphan_u += units
                combos[ok] = [0.0] * width + v
                counts.setdefault(ok, 0)
                continue
            spread_u += units if len(hits) > 1 else 0
            weight = [abs(combos[ck][qi]) if qi is not None else 1.0
                      for ck in hits]
            total = sum(weight)
            if not total:
                weight = [1.0] * len(hits)
                total = float(len(hits))
            for ck, w in zip(hits, weight):
                share = w / total
                row = combos[ck]
                for m in range(n_add):
                    row[width + m] += v[m] * share

        keys = keys + [k for k, _ in add_series]
        series = series + [{'key': k, 'label': lbl} for k, lbl in add_series]
        print(f'\n  onto the sales: {exact:,.0f} unit(s) landed on one '
              f'combination exactly, {spread_u:,.0f} had to be\n  spread over '
              'the combinations they were consistent with')
        if orphans:
            print(f'  {orphans:,} combination(s) ({orphan_u:,.0f} units) have no '
                  'sale in the month at all -\n  they chart as orders, and a '
                  'basis other than Sales leaves them out, because there\n  is '
                  'no sale of theirs to take a per-unit cost from')


    # ── the measured basis, where SAP's exports are there ──────────────────
    # SAP carries a despatch date, so which month a unit earned in is read
    # rather than argued for, and it carries the payer, so the key comes out at
    # full depth with nothing spread. Both beat the store export, so it goes
    # first and the store export is the fallback.
    # Built once, before either order source is read, because either of them
    # can be the one that answers: SAP wins where its exports are there and the
    # store export is the fallback, and the promotion split has to come out the
    # same way round. Reading it only off the store export left the split
    # missing - and so the button dead - on every build SAP answered.
    bander = (None if args.no_orders or args.no_promo
              else promo_bander(folder, args.plan))

    banded_any = [False]
    # What each campaign's products did, day by day and either side of the
    # window. Filled as whichever order source answers is read.
    _plan = None if args.no_promo else plan_once(folder, args.plan,
                                                 lambda *a: None)[0]
    _canon = (PM.canon_campaigns(_plan.rows, say=lambda *a: None)
              if _plan else {})
    watch, by_day = campaign_watcher(_plan, _canon)

    def merge_bands(src):
        """Make the promotion two more levels of the key.

        Not an overlay on the bar like "When ordered", but levels of the
        combination - so Stack by Promo is the same mechanism as Customer and
        Product, drawn by the same code: clicking a bar narrows to it and the
        next level splits what is left.

        The profit file has no promotion on it, so each combination is split
        across the promotions its orders came in on, in proportion to the units
        each carried. That is an allocation; it assumes every unit of a product
        earns the same margin whichever promotion brought it in, which is the
        one thing a discount does not do. It ranks promotions; it does not
        price one.
        """
        nonlocal keys, series
        if bander is None:
            return
        # The day-by-day tally rides out of the order source untouched: it is
        # not part of the key and is not split or spread, it is what the
        # campaign sold on each day it ran.
        tokens, by_band = (src.band_rows() if getattr(src, 'band_at', None)
                           else ([], {}))
        if not tokens:
            print('  no unit could be banded by promotion, so Stack by Promo '
                  'will be off on the page')
            return
        banded_any[0] = True
        got = sum(sum(v) for v in by_band.values())
        # Onto the combinations first, by the spreading the order side already
        # uses, so a band lands where its orders could have landed.
        merge_orders(by_band, skip_sku_arg(),
                     add_series=[(f'_pb{i}', t) for i, t in enumerate(tokens)])
        at = len(keys) - len(tokens)
        # Then split each combination by those columns and drop them. What the
        # orders could not band keeps a row of its own, so the month still
        # comes to its own total.
        fold = {} if args.promo_bands == 'all' else PROMO_FOLD
        kept = []
        bands_at: dict = {}
        for key, vals in list(combos.items()):
            share = vals[at:]
            total = sum(share)
            del combos[key]
            n = counts.pop(key, 0)
            head = vals[:at]
            if not total:
                lbl = NO_ORDER if args.promo_bands != 'all' else NO_ORDER_ALL
                kept.append(((key + (lbl, NO_CAMPAIGN, NO_CAMPAIGN)), head, n))
                continue
            per: dict = {}
            bands_at[key] = sum(1 for u in share if u)
            for t, u in zip(tokens, share):
                if not u:
                    continue
                band, c1, c2 = (t if isinstance(t, tuple) and len(t) == 3
                                else (t, NO_CAMPAIGN, NO_CAMPAIGN))
                band = fold.get(band, band)
                lv = (PROMO_LABEL.get(band, band), c1, c2)
                per[lv] = per.get(lv, 0.0) + u
            for lv, u in per.items():
                kept.append((key + lv, [x * u / total for x in head], n))
        for key, vals, n in kept:
            row = combos.get(key)
            if row is None:
                combos[key] = list(vals)
                counts[key] = n
            else:
                for i, x in enumerate(vals):
                    row[i] += x
                counts[key] = counts.get(key, 0) + n
        keys = keys[:at]
        series = series[:at]
        print(f'  promotion: {got:,.0f} unit(s) banded, over '
              f'{len({k[-3] for k in combos}):,} band(s), '
              f'{len({k[-2] for k in combos}):,} campaign 1 value(s) and '
              f'{len({k[-1] for k in combos}):,} campaign 2 value(s)')
        # How much of the money had to be divided at all. A combination whose
        # orders are all on one band is not divided - its share is 1.0 and the
        # figure is the profit file's own. Only a combination carrying two
        # bands at once has to be split, and there the split goes by units,
        # which assumes a promoted unit earns what an unpromoted one does.
        # That is worth a number rather than a warning.
        ni = keys.index('net') if 'net' in keys else None
        if ni is not None:
            whole = mixed = 0.0
            for key, vals in combos.items():
                amt = abs(vals[ni])
                whole += amt
                if bands_at.get(key[:-3], 0) > 1:
                    mixed += amt
            if whole:
                print(f'  of that, {mixed / whole * 100:.1f}% of net sales sits '
                      f'on a combination whose orders came\n  in on more than '
                      f'one band and so had to be divided between them, by '
                      f'units.\n  The other {100 - mixed / whole * 100:.1f}% is '
                      f'the profit file\'s own figure, undivided.')

    def skip_sku_arg():
        return tuple(t.strip().upper()
                     for t in args.skip_sku.split(',') if t.strip())

    got_sap = None
    if not args.no_orders and not args.no_sap and ym:
        sap_files = pick_series(folder, args.sap)
        seen_stem = set()
        sap_files = [f for f in sap_files
                     if not (f.stem.lower() in seen_stem
                             or seen_stem.add(f.stem.lower()))]
        if sap_files:
            print('\nreading SAP orders:')
            got_sap = SAP.load(
                sap_files, month=ym, cust_levels=CUST.LEVELS,
                prod_levels=PRODUCT_LEVELS, customers=cust, products=prod,
                currency=args.currency,
                skip_sku=tuple(t.strip().upper()
                               for t in args.skip_sku.split(',') if t.strip()),
                band_of=bander, watch=watch,
                marketplace=not args.no_marketplace)
            if got_sap:
                SAP.report(got_sap, ym)
                carry_in_known = any(
                    f for f in sap_files
                    if month_before(ym) == month_of([], [], f.stem,
                                                    say=lambda *a: None))
                if not carry_in_known:
                    print(f'  no {month_before(ym)} export, so what that month '
                          'carried into this one is not nil - it is unknown, '
                          'and\n  the page says so rather than charting a zero')
                merge_orders(got_sap.by_key)
                merge_bands(got_sap)
                oi = n_measures
                own = sum(v[oi] for k, v in combos.items())
                came = sum(v[oi + 2] for v in combos.values())
                sold = (abs(sum(v[keys.index('qty')] for k, v in combos.items()
                                if k[0] == CUST.ONLINE))
                        if 'qty' in keys else 0)
                model = own + came
                print(f'\n  the month off SAP: {own:,.0f} booked + {came:,.0f} '
                      f'carried in = {model:,.0f} units')
                if sold:
                    print(f'  the month as sold, {CUST.ONLINE} only: '
                          f'{sold:,.0f} units  ({model / sold * 100:.0f}% of it '
                          'accounted for)')
                    if abs(model - sold) > sold * 0.2:
                        print('  that is a wide gap - py tools\\link.py scores '
                              'the same figures product by product')
                split_money(combos, keys, n_measures, ym)

    # Which two exports model this month: the one named for it, and the one
    # named for the month before, unless both were named on the command line.
    want_now = args.orders or (month_name(ym) if ym else None)
    want_was = args.orders_before or (month_name(month_before(ym)) if ym else None)
    op = (None if args.no_orders or got_sap or not want_now
          else pick_file(folder, want_now))
    # The store export is the fallback, and a fallback that is sitting in the
    # folder unread is worth saying out loud: otherwise the only way to know
    # which source a page was built on is to read this file.
    if got_sap and want_now:
        spare = pick_file(folder, want_now)
        if spare is not None:
            print(f'  {spare.name} is in the folder and was not read - SAP '
                  f'answered. --no-sap builds off the store export instead')
    bp = (None if args.no_orders or got_sap or not want_was
          else pick_file(folder, want_was))
    if not args.no_orders and not got_sap and op is None and want_now:
        print(f'\nno order export named like {want_now!r}, so the page is sales '
              'only. Name one with --orders.')
        here = sorted(q.name for q in folder.iterdir()
                      if q.is_file() and 'dtc' in q.stem.lower())
        if here:
            print('  order-looking files in the folder: ' + ', '.join(here))
    if op is not None:
        print('\nreading orders:')
        drop = tuple(t.strip().upper() for t in args.skip_sku.split(',')
                     if t.strip())
        load = dict(cust_levels=CUST.LEVELS, prod_levels=PRODUCT_LEVELS,
                    customer_master=cp, products=prod, agree=args.agree,
                    currency=args.currency, signed=args.booked is None,
                    positive=tuple(t.strip().upper()
                                   for t in args.positive.split(',') if t.strip()),
                    negative=tuple(t.strip().upper()
                                   for t in args.negative.split(',') if t.strip()),
                    booked=({t.strip().upper() for t in args.booked.split(',')
                             if t.strip()} if args.booked else None))
        if bander is not None:
            load = dict(load, band_of=bander)
        if watch is not None:
            load = dict(load, watch=watch)
        this = ORD.load(op, **load)
        before = ORD.load(bp, **load) if bp is not None else None
        if bp is None:
            print(f'  no file named like {want_was!r}, so the page cannot say '
                  'what was carried into this month')

        # Modelling a month with another month's orders is worse than not
        # modelling it, and nothing downstream would show that it happened.
        if ym and not args.any_month:
            for who, side, expect in (('orders', this, ym),
                                      ('orders-before', before, month_before(ym))):
                if side is None:
                    continue
                got = side.month()
                if got == expect:
                    continue
                lo, hi = side.span()
                print(f'\n  {side.path.name} is not the {expect} export: its '
                      + (f'orders run {lo} .. {hi}' if lo else
                         'order dates could not be read')
                      + f'.\n  The profit file covers {ym}, so --{who} wants '
                      f'the {expect} export. Nothing is modelled from orders '
                      'until they line up;\n  --any-month overrides this.')
                this = None
                break
        if this is not None:
            ORD.report(this)
            if before is not None:
                ORD.report(before)

            # Six slots per key: what this month's own orders booked, what the
            # month before carried in, and what this month carries on.
            carry_in_known = before is not None
            by_key_store = {}
            for key in set(this.by_key) | (set(before.by_key) if before else set()):
                own = this.by_key.get(key) or [0.0] * 4
                came = ((before.by_key.get(key) or [0.0] * 4) if before
                        else [0.0] * 4)
                by_key_store[key] = [own[0], own[1], came[2], came[3],
                                     own[2], own[3]]
            merge_orders(by_key_store, skip_sku_arg())
            # The promotion split rides the same spreading, so it lands on the
            # same combinations in the same proportions as the orders it is a
            # property of. Both months, because a bar is the month as sold and
            # what carried in is part of it.
            # Both months' bands onto one source, because a bar is the
            # month as sold and what carried into it is part of that.
            if bander is not None and before is not None:
                for k, v in before.by_band.items():
                    for token, i in before.band_at.items():
                        if i < len(v) and v[i]:
                            this.add_band(k, token, v[i])
            merge_bands(this)
            # The month as the orders model it, beside the month as sold. A
            # wide gap between them means the booking rule does not describe
            # this export, and py tools\cohort.py is where to find out why.
            oi = n_measures
            own = sum(v[oi] for v in combos.values())
            came = sum(v[oi + 2] for v in combos.values())
            goes = sum(v[oi + 4] for v in combos.values())
            # The orders are the online store's, so the only sales they can
            # account for are the online ones. Comparing against the whole file
            # would charge them with the offline business as well.
            qi = keys.index('qty') if 'qty' in keys else None
            sold = abs(sum(v[qi] for k, v in combos.items()
                           if k[0] == CUST.ONLINE)) if qi is not None else 0
            model = own + came
            # The basis is built on units; money rides along for the tooltips
            # and the stacked chart, so where it comes from is worth saying.
            print(f'\n  units from the order exports, money from '
                  + (repr(this.amount_col) if this.amount_col else 'nowhere')
                  + f'; the profit side is {head[pos_of["qty"]]!r} and '
                  + (repr(head[pos_of['net']]) if 'net' in pos_of
                     else repr(head[pos_of['gross']])))
            print(f'  the month as the orders model it: {own:,.0f} booked on '
                  f'its own orders + {came:,.0f} carried in = {model:,.0f} units')
            if sold:
                print(f'  the month as sold, {CUST.ONLINE} only: {sold:,.0f} '
                      f'units  ({model / sold * 100:.0f}% of it modelled)')
                if abs(model - sold) > sold * 0.15:
                    print('  that is a wide gap. The booking rule may not '
                          'describe this export - run py tools\\cohort.py, '
                          'which scores it against the alternatives')
            print(f'  carried on to the month after: {goes:,.0f} units'
                  + (f'  ({goes / sold * 100:.0f}% of the month)' if sold else ''))

    dropped = apply_drops(combos, counts, drop_rules(args), keys)
    if sent_back['rows']:
        dropped = dropped + [f'returns ({sent_back["rows"]:,} row(s), '
                             f'{abs(sent_back["qty"]):,.0f} unit(s))']
    if not combos:
        print('  that is everything this export had. Nothing is left to draw - '
              'check the --drop values against the levels above')

    # ── what the filters ended up holding ──────────────────────────────────
    levels = []
    print('\nfilter values:')
    # The promotion levels are only there when something was banded, so they
    # are appended here rather than being part of FILTERS - a page built
    # without them must not carry two empty filters.
    shown = FILTERS + (PROMO_LEVELS if banded_any[0] else [])
    for n, (label, slot, names) in enumerate(shown):
        seen = sorted({k[n] for k in combos})
        levels.append({'name': label, 'values': seen})
        known = ({v for m in (cust, prod) for row in m.values()
                  if (v := row.get(slot))}
                 if n and n < len(FILTERS) else set())
        missing = sorted(known - set(seen))
        src = []
        if n >= len(FILTERS):
            print(f'  {label}: {len(seen)} value(s)  (from the promotion plan)')
            print('    ' + ', '.join(seen[:14])
                  + (' ...' if len(seen) > 14 else ''))
            continue
        if from_master[n]:
            src.append(f'{from_master[n]:,} row(s) from the master')
        if from_export[n]:
            col = (head[fallback[n]] if fallback[n] is not None
                   else head[acct_fb] if n == 0 and acct_fb is not None
                   else head[p_key] if slot == 'sku' and p_key is not None
                   else None)
            src.append(f'{from_export[n]:,} from '
                       + (f'{col!r} in the export' if col else 'the export'))
        print(f'  {label}: {len(seen)} value(s)  ({"; ".join(src) or "nothing"})')
        print('    ' + ', '.join(seen[:14]) + (' ...' if len(seen) > 14 else ''))
        if missing:
            print('    not in this export, though the master lists them: '
                  + ', '.join(missing[:10]) + (' ...' if len(missing) > 10 else ''))

    # ── where does one filter value sit? ───────────────────────────────────
    # The page's selects cascade, so a value under a channel or type that is
    # narrowed away is simply not listed - which reads like it is not in the
    # file at all. This says which paths actually carry it.
    if args.where:
        want = args.where.strip().upper()
        print(f'\nwhere {args.where!r} sits:')
        found = False
        for n, lv in enumerate(levels):
            hits = {k[:n]: 0 for k in combos if k[n].strip().upper() == want}
            if not hits:
                continue
            found = True
            for k in combos:
                if k[n].strip().upper() == want:
                    hits[k[:n]] += counts[k]
            total = sum(hits.values())
            print(f'  as a {lv["name"]}: {total:,} row(s) over {len(hits)} path(s)')
            for path, n_rows in sorted(hits.items(), key=lambda kv: -kv[1])[:8]:
                trail = ' / '.join(path) if path else '(top level)'
                print(f'    {trail}: {n_rows:,} row(s)')
            if len(hits) > 8:
                print(f'    ... and {len(hits) - 8} more path(s)')
        if not found:
            print('  no filter level carries it')
        # A value can be perfectly real and still never reach a filter, because
        # it sits in a column no level reads. Name the column rather than leave
        # "not there" to mean two different things.
        wired = {n for _, _, names in FILTERS + [('', '', CUST.ACCOUNT_NAMES)]
                 for n in names}
        for name, (mhead, mrows) in RAW.items():
            for i, h in enumerate(mhead):
                n = sum(1 for r in mrows
                        if i < len(r) and r[i].strip().upper() == want)
                if not n:
                    continue
                read = any(find([h], alias) is not None for alias in wired)
                print(f'  {name} column {h!r}: {n:,} row(s)'
                      + ('' if read else
                         '   <- no filter level reads this column'))

    index = {lv['name']: {v: i for i, v in enumerate(lv['values'])} for lv in levels}
    start = args.start_channel or ''
    if start and start not in levels[0]['values']:
        print(f'\n--start-channel {start!r} is not a channel in the data; opening '
              f'on all of them. Seen: {", ".join(levels[0]["values"])}')
        start = ''
    elif start:
        print(f'\nopens on: {start}  (set Channel to All to bring '
              f'{", ".join(v for v in levels[0]["values"] if v != start)} back in)')

    # The list price of every SKU the month holds, so the workbook can put what
    # was meant to be charged beside what was. Read whether or not the
    # promotion split is on: --no-orders switches the split off because there
    # are no order dates to band, which says nothing about the list price.
    skus = next((lv['values'] for lv in levels if lv['name'] == 'SKU'), [])
    rrp = {}
    if not args.no_promo:
        plan = plan_once(folder, args.plan)[0]
        rrp = rrp_by_sku(plan, skus, ym)
        if args.rrp:
            say_rrp(plan, args.rrp, ym)

    payload = {
        'ym': ym,
        'month': (f'{MONTHS[(ym % 100) - 1]} {ym // 100}' if ym else target.stem),
        'title': args.title or (f'{MONTHS_LONG[(ym % 100) - 1]} {ym // 100} '
                                'Profit' if ym else 'Profit'),
        'file': target.name,
        'rows': len(body),
        # Named rather than derived in the page: the carry-in came from a real
        # month, and "rolled in from Jul" reads where "rolled in" does not.
        'before': (MONTHS[(month_before(ym) % 100) - 1] if ym else ''),
        'custDepth': CUST_DEPTH,
        # Whether the month before's orders were read at all. Without them the
        # carry-in is not nil, it is unknown, and a page that charts it as nil
        # says the month earned all its own revenue - which is a finding, and a
        # wrong one.
        'carryIn': carry_in_known,
        # Whether anything could be banded by promotion. Carried out of the
        # month build so the run can say, once and at the end, that Stack by
        # Promo will be off - a disabled button looks the same as a broken one.
        'promoBands': banded_any[0],
        # Where the promotion chain starts, so the page can split the levels
        # into three chains the way it already splits them into two.
        'promoAt': PROMO_AT if banded_any[0] else None,
        'levels': levels,
        'series': series,
        # What --drop took out. Carried into the page because a report that
        # quietly leaves a business out is the one kind of wrong a reader
        # cannot see: it says so under the menu and on the Scope sheet.
        'dropped': dropped,
        # By SKU rather than by combination: a list price is a property of the
        # product, and writing it once per product keeps a page over nine
        # months and forty thousand combinations the size it is.
        'rrp': rrp,
        # What each campaign sold on each day it ran, and the window it ran
        # between. Not part of the key and not split by anything: the month chart
        # is the month, and this is the campaign.
        'campaigns': campaign_payload(by_day, folder, args),
        # The masters this month was joined on, so the daily chart can be read
        # on the same key without reading them again. Popped before the payload
        # is written - they are not part of the page.
        '_masters': (cust, prod),
        'start': index[levels[0]['name']].get(start, -1) if start else -1,
        # Rounded to whole units: the chart is drawn in millions and the table
        # in whole amounts, so cents would only make the file bigger.
        'combos': [{'k': [index[lv['name']][k[n]] for n, lv in enumerate(levels)],
                    'n': counts[k], 'v': [round(x) for x in v]}
                   for k, v in combos.items()],
    }
    return payload


if __name__ == '__main__':
    sys.exit(main())

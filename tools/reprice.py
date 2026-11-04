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
import dtc as DTC                                               # noqa: E402
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
# How many months of its own a product needs before its ASP is read one
# month one vote rather than pooled. Two numbers are not an average.
MIN_MONTHS = 3

# What each nudge did to each product, for --explain. A re-price that comes
# out wrong by a level rather than a scatter is one term over-firing for a
# whole division, and the only way to see which is to keep the terms apart
# instead of summing them into a price and guessing afterwards.
BREAKDOWN: list = []
# How many product-days a campaign needs before its pull on volume is read.
# A campaign seen on two days is an anecdote about two days.
MIN_DAYS = 3
# How many of a group's own products must have a discount before the group
# can answer for one that has none.
MIN_SKUS = 3
# The product levels this borrows by, coarsest last.
PROD_COLS = {'div3': ('Div 3', 'Div3', 'Category', 'Prod_group'),
             'div1': ('Div 1', 'Div1', 'Division 1', 'Division'),
             'biz': ('Biz', 'Business', 'Business Unit')}
NO_CAMP = ''                     # the key for a day with no campaign on it
ANY = '\x00any'                  # the tally that ignores which campaign it was

# How far the discount may be borrowed from, nearest first. Stopping short of
# the end of this ladder is a real choice: a discount read off `all` is the
# whole book's, and multiplying a fridge's own list price by what televisions
# and phones came off theirs is not a forecast about fridges. Where that is
# refused the product falls through to its own ASP, and failing that keeps the
# price the sheet already had - both of which say less, and neither of which
# invents a number.
SCOPES = ('sku', 'range', 'div3', 'div1', 'all')
# `div1` is the default: a product may borrow from its own history, its
# product group, or its division, and not from the book entire. That last
# rung was measurably doing harm - a category the GSCM sheet had priced
# tightly came back scattered, and one product group's deviation collapsed to
# six hundredths of a dollar, which is every model in it sharing one borrowed
# number rather than a model that fits. `all` restores it.


def set_min_units(n: int) -> None:
    """How many units a product needs before its own record is used.

    A product that sold three scatters ten points around its own range and
    one that sold a hundred sits within two, so the gate is really asking
    how noisy an estimate is allowed to be before the family answers
    instead.
    """
    global MIN_UNITS
    MIN_UNITS = max(1, int(n or 1))


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


# Campaigns that are not ordinary trading, named so in the plan.
# `--campaigns` on the real window shows them as the deep ones - APS
# Clearance at 56.9% off and Accessories Clearance at 50.6% against 33.3%
# for a nationwide day, REF's Early EOFY at 46.5% against 38.2% for a
# Samsung Week - and a window that averages one in carries it forward into
# a month that is not running it.
#
# Matched **by kind**, so a month running a Secret Sale keeps a product's
# past Secret Sales and still drops its past EOFY. One list, one place.
SPECIAL = ('clearance', 'secret', 'eofy')


def special_kinds(camp: str) -> frozenset:
    """Which of them this campaign's name claims to be, if any."""
    low = (camp or '').lower()
    return frozenset(w for w in SPECIAL if w in low)


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

    Four depths of the same question, because a product that sold five units
    last quarter cannot answer it alone: the product's own discount, its
    division's, and the whole book's. Each is read only where there are enough
    units behind it to mean anything.

    `half` is a half-life in months. At nought every month in the window
    counts alike, which is the flat average this started as. Set, a line
    `half` months old counts half as much as one from last month, and one
    twice that age a quarter. It is there because a category that discounts
    deeper as a model ages - tablets and handsets do - has its early, shallow
    months pulling the average up, and a flat window predicts a price the
    month will not sell at. The weighting moves what is averaged, never what
    is counted: the units gate below stays on the raw quantity, so a thin
    history cannot be made to look sufficient by weighting it.
    """

    def __init__(self, half: float = 0.0, ref: int | None = None,
                 pooled: bool = False, by_units: bool = True):
        self.half = max(0.0, half or 0.0)
        self.pooled = pooled
        # True pools a group's promoted lines against its unpromoted ones;
        # False averages the members' own gaps instead, which is cleaner in
        # principle - pooling compares two different sets of products - and
        # measured worse on TV, so it is behind --by-members until a run
        # says otherwise.
        self.by_units = by_units
        self.ref = ref
        self.by: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        self.skus: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # The same tally kept month by month, because an ASP pooled over a
        # window is weighted by units and a product sells most when it is
        # cheapest. See `asp`.
        self.smon: dict = collections.defaultdict(lambda: [0.0, 0.0])
        # (campaign, product, month) -> [units, paid, listed]. Enough to
        # ask, of a campaign, how much of what it shifted was a product on
        # its way out - see `campaign_report`.
        self.cm: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # product -> {(month, on a promotion?, channel): [units, paid]}.
        # The ASP kept apart by promotion and by channel, so a month can be
        # answered in its own terms - what this product fetches under a
        # promotion and without one, to B2B and to B2C - see `sides`.
        self.sc: dict = collections.defaultdict(
            lambda: collections.defaultdict(lambda: [0.0, 0.0]))
        # The same tally split by channel, which is the only way to see what
        # the B2B half of a month costs that the consumer half does not.
        self.ch: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # Units and product-days under each campaign. Dividing one by the
        # other gives the rate a campaign sells at, and the ratio of that to
        # the off-promotion rate is how much harder a promotion pulls. It
        # takes every line, including those with no list price, because this
        # is about volume and not about discount.
        self.vol: dict = collections.defaultdict(float)
        self.days: dict = collections.defaultdict(float)
        # Which products sit in each group, so a group can be asked for the
        # average of its members rather than the average of its units.
        self.members: dict = collections.defaultdict(set)
        self._lent: dict = {}
        self._gap: dict = {}
        # For the simple model: the same money split three ways at group
        # level - on a campaign or not, on an unplanned deal or not, and by
        # month so a penetration can be read recently rather than flat.
        self.cg: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        self.pr: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        self.pen: dict = collections.defaultdict(lambda: [0.0, 0.0])
        self.mon: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])

    def weight(self, day) -> float:
        if not self.half or self.ref is None or day is None:
            return 1.0
        age = ((self.ref // 100 - day.year) * 12
               + (self.ref % 100 - day.month))
        return 0.5 ** (max(0, age) / self.half)

    def add(self, code, level, camp, qty, amt, rrp, day=None, chan=None,
            deal=False, ym=None):
        if qty <= 0:
            return
        w = self.weight(day)
        if rrp:
            on = 'on' if camp else 'off'
            kind = 'deal' if deal else 'clean'
            for scope in self.scopes(code, level):
                for key in ((scope, on), (scope, kind)):
                    t = self.cg[key] if key[1] in ('on', 'off') else \
                        self.pr[key]
                    t[0] += amt
                    t[1] += qty * rrp
                    t[2] += qty
                if ym is not None:
                    t = self.pen[(scope, ym)]
                    t[0] += qty if deal else 0.0
                    t[1] += qty
                    # Off-campaign lines only. The campaign nudge
                    # already answers for how much promotion October
                    # carries; if this counted the promoted lines too, a
                    # window that was deep *because* it was busy would be
                    # charged for twice.
                    if not camp:
                        t = self.mon[(scope, ym)]
                        t[0] += amt
                        t[1] += qty * rrp
                        t[2] += qty
        # The ASP tally takes every line; the discount tally takes only the
        # lines that have a list price to be a discount off. Mixing them put
        # money in the numerator with nothing in the denominator and read as a
        # product selling above its own RRP.
        self.skus[code][0] += qty * w
        self.skus[code][1] += amt * w
        self.skus[code][2] += qty
        if ym is not None:
            t = self.smon[(code, ym)]
            t[0] += qty * w
            t[1] += amt * w
            t = self.sc[code][(ym, bool(camp), chan or '')]
            t[0] += qty * w
            t[1] += amt * w
            if rrp:
                t = self.cm[(camp, code, ym)]
                t[0] += qty
                t[1] += amt
                t[2] += qty * rrp
        for scope in self.scopes(code, level):
            self.vol[(scope, camp)] += qty
            if scope[0] != 'sku':
                self.members[scope].add(code)
        if not rrp:
            return
        for scope in self.scopes(code, level):
            for key in ((scope, camp), (scope, ANY)):
                t = self.by[key]
                t[0] += qty * w
                t[1] += amt * w
                t[2] += qty * rrp * w
                t[3] += qty
            if chan:
                t = self.ch[(scope, chan)]
                t[0] += amt * w
                t[1] += qty * rrp * w
                t[2] += qty

    def discount(self, scope, camp):
        """1 - what was collected over what was listed, or None.

        Never below nought. A price over its own list price is a bundle, a
        freight line or a mistyped RRP, and re-pricing a product *above* its
        list because of one is not a forecast anyone would stand behind.
        """
        t = self.by.get((scope, camp))
        if not t or t[3] < MIN_UNITS or t[2] <= 0:
            return None
        return max(0.0, 1.0 - (t[1] / t[2]))

    def _cell(self, got, on, chan):
        """One month one vote over the months that fill one cell."""
        live = [t for (_, o, c), t in got.items()
                if o is on and (chan is None or c == chan)
                and t[0] >= MIN_UNITS and t[1] > 0]
        if not live:
            return None
        if len(live) >= MIN_MONTHS:
            return sum(t[1] / t[0] for t in live) / len(live)
        q = sum(t[0] for t in live)
        return (sum(t[1] for t in live) / q) if q else None

    def sides(self, code, b2b=None):
        """(what it fetches on a promotion, and without one) - and how.

        One month one vote inside each cell, for the reason the blended ASP
        takes one; a cell without MIN_MONTHS of its own is pooled over its
        units, and a cell with no month at all is None.

        Each side is asked **by channel** where both channels answer, and
        re-mixed at the share of the month's units the plan puts through
        B2B. B2B runs several points deeper than B2C, so a product whose
        own channel mix moves is wrong by that difference with no campaign
        having changed - and this is the only place that difference can be
        caught per product rather than per group.

        This is what lets a month be answered in its own terms. A Fold8
        sold its whole window under a pre-order at 47% off and sells
        October at 9% off; a blended ASP carries the pre-order forward and
        is 20% light, while the quiet side of the same window says what it
        fetches when nothing is running.
        """
        got = self.sc.get(code)
        if not got:
            return None, None, False
        out, split = [], False
        for on in (True, False):
            if b2b is not None:
                bb = self._cell(got, on, 'B2B')
                cc = self._cell(got, on, 'B2C')
                if bb is not None and cc is not None:
                    out.append(bb * b2b + cc * (1.0 - b2b))
                    split = True
                    continue
            out.append(self._cell(got, on, None))
        return out[0], out[1], split

    def asp(self, code):
        """What the product fetched over the window, one month one vote.

        **A product sells most when it is cheapest.** An ASP pooled over a
        window - all the revenue over all the units - is therefore weighted
        towards its own cheap months, and what is being predicted is not a
        unit but a *month*. So the window over-states the discount, and it
        over-states it in the same direction every time: on October the
        backtest puts a flat pooled window 4.2 points deep per product,
        never the other way.

        That is also why a half-life appears to fix it and does not. The
        bias is selection, not age; shortening the window drops whichever
        heavy months happen to sit at the back, which works for a quiet
        month like October and reverses for a loud one like November, so
        the fitted half-life would have to be re-fitted every month. One
        month one vote needs no fitting and holds whatever the month is.

        A month under MIN_UNITS does not get a vote - averaging a month of
        three units beside a month of three hundred trades a bias for a
        variance - and a product without MIN_MONTHS of them keeps the
        pooled figure it always had. Two numbers are not an average: a
        colour variant selling eight a month clears the bar in two months
        of six and the mean of those two carries more noise than the bias
        it removes, which showed up as MX's scatter rising while its level
        fell.
        """
        q, a, raw = self.skus.get(code, [0.0, 0.0, 0.0])
        if raw < MIN_UNITS or q <= 0:
            return None
        if self.pooled:
            return a / q
        each = [t[1] / t[0] for (c, _), t in self.smon.items()
                if c == code and t[0] >= MIN_UNITS and t[1] > 0]
        return sum(each) / len(each) if len(each) >= MIN_MONTHS else a / q

    def own(self, code):
        """This product's own discount over the window, campaigns together.

        What it has been coming off its list price lately, whatever was on at
        the time. It is the answer for a day October puts no campaign on, and
        for a campaign this product has never run before: its own behaviour
        under a different promotion is a better guide to its price than
        another product's behaviour under this one.
        """
        return self.discount(('sku', code), ANY)

    def sold(self, code):
        return self.skus.get(code, [0.0, 0.0, 0.0])[2]

    @staticmethod
    def scopes(code, level):
        """Every bucket a line belongs to, narrowest first.

        `range` is the model family - one phone's colours and capacities. It
        is the level a thin product has any business borrowing from: a SKU
        that sold a hundred units sits within two points of its own range
        and one that sold three scatters ten points around it, so the range
        is what the thin one wants, and a division is far too coarse to be
        it.
        """
        out = [('sku', code)]
        for n in ('range', 'div3', 'div1'):
            if level.get(n):
                out.append((n, level[n]))
        out.append(('all', ''))
        return out

    def saw(self, code, level, camp):
        """One product-day, under whatever campaign covered it."""
        for scope in self.scopes(code, level):
            self.days[(scope, camp)] += 1

    def pull(self, scope, camp):
        """How much harder this campaign sells than an ordinary day.

        Units per product-day under the campaign, over units per product-day
        with no campaign on. One means a promotion that shifts no more than
        a quiet day; two means it shifts twice as much, and a day like that
        is worth twice as much of the month's price.

        Clamped, because a campaign that ran over one freak weekend should
        move a month's price and not define it.
        """
        on_u, on_d = self.vol.get((scope, camp), 0.0), \
            self.days.get((scope, camp), 0.0)
        off_u, off_d = self.vol.get((scope, NO_CAMP), 0.0), \
            self.days.get((scope, NO_CAMP), 0.0)
        if on_d < MIN_DAYS or off_d < MIN_DAYS or on_u <= 0 or off_u <= 0:
            return None
        return min(5.0, max(0.2, (on_u / on_d) / (off_u / off_d)))

    def tilt(self, scope):
        """Units per promoted day over units per quiet day, for a bucket.

        `pull` answers it for one named campaign; this answers it for
        promotion in general, which is what turns a month's **days** into
        the share of its **units** that will be sold under one. A promotion
        is not worth its share of the calendar - it is worth what it sells,
        and a promoted day shifts two to three times a quiet one.

        Clamped, because a campaign that ran over one freak weekend should
        move a month's price and not define it.
        """
        on_u = sum(v for (sc, c), v in self.vol.items() if sc == scope and c)
        on_d = sum(v for (sc, c), v in self.days.items() if sc == scope and c)
        off_u = self.vol.get((scope, NO_CAMP), 0.0)
        off_d = self.days.get((scope, NO_CAMP), 0.0)
        if on_d < MIN_DAYS or off_d < MIN_DAYS or on_u <= 0 or off_u <= 0:
            return None
        return min(3.0, max(0.8, (on_u / on_d) / (off_u / off_d)))

    def lent(self, scope, camp, by_units=False):
        """What a group answers with when a product has nothing of its own.

        Two different questions, and the right one depends on what is being
        got right. `by_units` gives the group's realised discount - the
        average of its **units**, which its bestseller dominates. The
        default averages its **products**, one vote each.

        The product doing the borrowing is nearly always a thin one, and a
        thin product does not behave like its family's bestseller: measured
        on October, products selling 1-4 units came in 1.9 points shallower
        than their family's unit-weighted discount while those selling 100+
        came in 0.7 deeper. So for pricing a product rather than a pound,
        the members are the better population to ask.
        """
        if by_units:
            return self.discount(scope, camp)
        key = (scope, camp)
        if key in self._lent:
            return self._lent[key]
        ds = []
        for code in self.members.get(scope, ()):
            d = self.discount(('sku', code), camp)
            if d is not None:
                ds.append(d)
        out = (sum(ds) / len(ds)) if len(ds) >= MIN_SKUS else None
        self._lent[key] = out
        return out

    def _gaps(self, scope):
        """The mean of the members' own promoted-to-quiet gaps, or None.

        Only products that sold MIN_UNITS either side of the line can say
        anything, and under MIN_SKUS of them is not a group average - both
        fall back to the pooled figure, which is wrong in a known direction
        rather than unknown.
        """
        if scope[0] == 'sku':
            return None
        if scope in self._gap:
            return self._gap[scope]
        out = []
        for code in self.members.get(scope, ()):
            on = self.cg.get((('sku', code), 'on'))
            off = self.cg.get((('sku', code), 'off'))
            if not on or not off or on[2] < MIN_UNITS or off[2] < MIN_UNITS:
                continue
            a, b = self._rate(on), self._rate(off)
            if a is not None and b is not None:
                out.append(a - b)
        got = (sum(out) / len(out)) if len(out) >= MIN_SKUS else None
        self._gap[scope] = got
        return got

    @staticmethod
    def _rate(t):
        return (1 - t[0] / t[1]) if t and t[1] > 0 else None

    def coverage(self, scope):
        """What share of this bucket's product-days carried a campaign.

        Days need no unit threshold - a day a product was live is a day,
        whether it sold or not - so this is answerable for every product
        individually and **is never borrowed**. That matters because the
        two halves of the campaign nudge are not alike: what a campaign is
        worth is a price fact, thin for one product and fairly taken from
        its group; how much of the month a product spends on promotion is a
        calendar fact, and its group's is simply somebody else's calendar.

        A fridge is on promotion most of the month, every month. Borrowing
        a coverage figure from a book where promotions are occasional said
        its October was far more promoted than its past, and priced it
        about 8% under what it sold for - every REF line out the same way,
        a level and not a scatter.
        """
        don = sum(v for (sc, c), v in self.days.items() if sc == scope and c)
        doff = self.days.get((scope, NO_CAMP), 0.0)
        return don / (don + doff) if don + doff > 0 else None

    def campaign(self, scope):
        """(share of product-days on a campaign, what a campaign is worth).

        **Days, not units.** The other side of this comparison is October's
        planned calendar, which can only be counted in days - the month has
        not happened, so it has no units. A campaign sells two and a half
        times an ordinary day, so its share of the units always runs well
        above its share of the days, and comparing the one against the other
        reads a difference where there is none and misses one where there
        is. The discount either side of it is unit-weighted, as a realised
        discount has to be; only the coverage is counted in days.
        """
        on, off = self.cg.get((scope, 'on')), self.cg.get((scope, 'off'))
        if not on or not off or on[2] < MIN_UNITS or off[2] < MIN_UNITS:
            return None
        a, b = self._rate(on), self._rate(off)
        if a is None or b is None:
            return None
        # What a campaign is worth, **one product one vote**. Pooling a
        # group's promoted lines against its unpromoted ones compares two
        # different sets of products, so whatever else differs between them
        # - a dearer model promoted, a cheaper one not - is read as the
        # promotion's doing. Measured on October, REF pools to 24.4pp where
        # the same fridges measured one at a time say 1.0pp.
        each = None if self.by_units else self._gaps(scope)
        if each is not None:
            a, b = b + each, b
        don = sum(v for (sc, c), v in self.days.items()
                  if sc == scope and c)
        doff = self.days.get((scope, NO_CAMP), 0.0)
        if don + doff <= 0:
            return None
        return don / (don + doff), a - b

    def deals(self, scope, months):
        """(penetration lately, penetration over the window, what it costs).

        A voucher, a trade-in, an e-promoter code. They are the biggest
        single thing between MX's list price and what was paid - October
        sold 5,409 MX units clean at 31.7% off and 5,336 on a voucher at
        40.0%, with a trade-in beside it at 43.7% and both at 49.4% - and
        **all of it is already inside the revenue**, so the window ASP
        carries it at whatever rate that window ran. What does not carry is
        the rate itself, which swings hard month to month.

        The unplanned discounts - a voucher, a trade-in, an e-promoter code.
        They are not in any plan and never will be, so nothing forecasts
        them; what can be done is to notice the group has been running them
        harder lately than the window's average and move the price by the
        difference.
        """
        d, c = self.pr.get((scope, 'deal')), self.pr.get((scope, 'clean'))
        if not d or not c or d[2] < MIN_UNITS or c[2] < MIN_UNITS:
            return None
        a, b = self._rate(d), self._rate(c)
        if a is None or b is None:
            return None
        got = [(m, self.pen.get((scope, m))) for m in months]
        got = [(m, t) for m, t in got if t and t[1] > 0]
        if not got:
            return None
        # One month one vote on both sides, for the same reason the ASP
        # takes one: pooling the window's units lets its busiest months
        # decide, and a busy month is busy because it was discounting, so
        # the window reads a higher penetration than a typical month has.
        late = got[-1][1][0] / got[-1][1][1]
        each = [t[0] / t[1] for _, t in got]
        flat = sum(each) / len(each) if each else late
        return late, flat, a - b

    def mix(self, scope):
        """(B2B's share of the units, how much deeper its discount is).

        Both off the same lines, so the pair describes one population: how
        much of it went out on the B2B side, and what that side costs over
        the consumer one. None where either side is too thin to mean
        anything - a gap read off three units is not a gap.
        """
        b = self.ch.get((scope, 'B2B'))
        c = self.ch.get((scope, 'B2C'))
        if not b or not c or b[2] < MIN_UNITS or c[2] < MIN_UNITS:
            return None
        if b[1] <= 0 or c[1] <= 0:
            return None
        return (b[2] / (b[2] + c[2]),
                (1 - b[0] / b[1]) - (1 - c[0] / c[1]))


def read_history(folder: Path, plan, canon, months: list, levels: dict,
                 say=print, half: float = 0.0, source: str = 'auto',
                 want_days: bool = True, pooled: bool = False,
                 by_units: bool = True, skip=None) -> History:
    """Every order line of those months, priced and banded by its campaign.

    The DTC export is preferred where the folder has one, because it carries
    the list price on the line itself - about 99 lines in 100 against the
    seven products in ten the promotion plan quotes an RRP for. A discount is
    what came off a list price, so a line with no list price is a line the
    discount tally cannot use at all, and that coverage is the whole input to
    this.

    The campaign is still read off the plan by date, on both sides, so the
    history and the month being priced are speaking of the same campaigns.
    The export's own `promotion_rule` is the more accurate account of what
    applied, but October has not happened yet and has only the plan to be
    described by; keying one side on each would join on nothing.
    """
    h = History(half, months[-1] if months else None, pooled=pooled,
                by_units=by_units)
    if source != 'orders':
        want = set(months)
        rows = DTC.read(folder, want, say=say) if DTC.files(folder) else []
        if rows:
            miss = 0
            dropped = [0, 0.0]
            for r in rows:
                code = PM.code_norm(r['code'])
                # The export names the model family itself, which the
                # product master does not, and it is the level a thin
                # product borrows from. Taken here so it rides in `levels`
                # with the rest of the chain.
                if r.get('range'):
                    levels.setdefault(code, {}).setdefault('range',
                                                           r['range'])
                rrp = r['rrp'] or rrp_of(plan, r['code'])
                camp = campaign_at(plan, canon, code, r['day'])
                if skip is not None and skip(code, camp):
                    dropped[0] += 1
                    dropped[1] += r['qty']
                    continue
                if not rrp:
                    miss += 1
                h.add(code, levels.get(code, {}), camp,
                      r['qty'], r['amt'], rrp, r['day'],
                      chan=(r['dist'] or '').upper() or None,
                      deal=bool(r.get('trade') or r.get('vouch')),
                      ym=r.get('ym'))
            # One pass over every product and every day of the window,
            # so a campaign's days are counted whether or not it sold on
            # them - a promotion that sold nothing is still a day it was on.
            if want_days:
                span = [d for m in months for d in month_days(m)]
                for code in list(h.skus):
                    lv = levels.get(code, {})
                    for d in span:
                        camp = campaign_at(plan, canon, code, d)
                        # A day whose sales were dropped is not a day the
                        # product traded, or its coverage would count a
                        # window the discount tally never saw.
                        if skip is not None and skip(code, camp):
                            continue
                        h.saw(code, lv, camp)
            say(f'  {len(rows):,} DTC line(s); {len(h.skus):,} product(s) '
                'with a realised price')
            if dropped[0]:
                say(f'  {dropped[0]:,} line(s), {dropped[1]:,.0f} unit(s) '
                    'left out: a clearance, secret sale or EOFY the month '
                    'being priced is not running')
            if miss:
                say(f'  {miss:,} line(s) with no list price anywhere - they '
                    'count towards the ASP and not the discount')
            camps = {c for (_, c) in h.by
                     if c and c != ANY and c != '(nationwide)'}
            say(f'  {len(camps)} campaign(s) in that history: '
                + ', '.join(sorted(camps)[:6]) + (' ...' if len(camps) > 6
                                                  else ''))
            return h
        if source == 'dtc':
            say('  no DTC export for those months - nothing to read')
            return h
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
                  rrp_cache[code], day)
            used += 1
    say(f'  {used:,} of {lines:,} order line(s) in '
        + ', '.join(str(m) for m in months)
        + f'; {len(h.skus):,} product(s) with a realised price')
    camps = {c for (_, c) in h.by
             if c and c != ANY and c != '(nationwide)'}
    say(f'  {len(camps)} campaign(s) in that history: '
        + ', '.join(sorted(camps)[:6]) + (' ...' if len(camps) > 6 else ''))
    return h


def nearest(k, lv, rrp, hist, levels, rrp_at):
    """The product most like this one that has actually been sold.

    A code the window has never seen has no discount and no ASP of its own,
    and the honest thing is to say so and name what was used instead. The
    neighbour is looked for in the same product group first and the same
    division after - a kettle is no guide to a fridge - and among those, the
    one whose code runs alongside it longest and whose list price is nearest.

    Codes carry their own family: SM-S948BZKAATS and SM-S948BZVAATS are one
    phone in two colours, and they are priced alike because they are the same
    thing. The shared prefix finds that where a division cannot.
    """
    best, score = None, None
    for other in hist.skus:
        if other == k or hist.sold(other) < MIN_UNITS:
            continue
        olv = levels.get(other, {})
        for n, tier in (('range', 3), ('div3', 2), ('div1', 1)):
            mine, theirs = lv.get(n), olv.get(n)
            if mine and theirs and mine == theirs:
                break
        else:
            continue
        run = 0
        for a, b in zip(k, other):
            if a != b:
                break
            run += 1
        gap = 0.0
        if rrp:
            o_rrp = rrp_at(other)
            # Nearest list price, as a ratio - 100 off a 200 phone is not the
            # same distance as 100 off a 4,000 fridge.
            gap = -abs((o_rrp or rrp) / rrp - 1.0)
        here = (tier, run, gap)
        if score is None or here > score:
            best, score = other, here
    return best


def simple_price(code, plan, canon, hist, levels, days, gscm,
                 months, b2b=None, plan_mix=None):
    """One price per product: its own ASP, then promotion on top.

    **The ASP comes first and the promotion second.** The product's own
    window ASP is the base and stays the base; everything after it is a
    *difference* between what the month being priced is planned to be and
    what the window actually was. So where the month looks like the past,
    every term is nought and the price is simply the ASP - the model's
    resting state is to not move, which is what keeps it from swinging.

    An earlier version re-mixed the base itself, splitting the ASP into its
    promoted and quiet halves and re-blending them at the month's own
    calendar. The algebra of that is sound - re-blend an unchanged calendar
    with a selling strength measured on the same window and the window ASP
    comes back exactly - but what it rests on is not. The blend needs a
    promoted day's selling strength; that is estimated per product and
    **clamped to 0.8-3.0**, and where the clamp binds or the estimate is
    borrowed the identity breaks and the base moves on its own. A base with
    no resting state is the thing to avoid, and the error it makes is the
    full promoted-to-quiet price gap times the blend error, which on a
    deeply promoted product is a lot of money.

    As a nudge the same evidence passes through a gentler transform: a
    difference in coverage times a difference in discount points, divided
    by what was left of the list price. Nothing was lost putting it back -
    the scope ladder already prefers a product's own campaign rate wherever
    it sold five units either side of the line.

    The three nudges:

        campaign   the month's promotion days against **its own** past
                   coverage, at its own rate where it has one and its
                   group's where it does not
        deals      voucher, trade-in and the like, lately against the window
        B2B        the plan's B2B share against the plan's own for its group

    They are summed, so the order is the reader's convenience and not the
    arithmetic's: the price is the same whichever way round they go.

    Coverage is never borrowed. What a campaign is worth is a price fact,
    thin for one product and fairly taken from its group; how much of a
    month a product spends on promotion is a calendar fact, and a group's
    calendar is somebody else's. Days carry no unit threshold, so a
    product's own is always countable.
    """
    k = PM.code_norm(code)
    lv = levels.get(k, {})
    blended = hist.asp(k)
    promo, clean, by_chan = hist.sides(k, b2b)
    if not blended and promo is None and clean is None:
        # Nothing of its own, and nothing borrowed: a neighbour's ASP
        # is a guess dressed as a measurement, and the sheet's own
        # price is the better answer where there is no record.
        return gscm, 'kept', None, 0.0, ['no ASP of its own']
    on = sum(1 for d in days if campaign_at(plan, canon, k, d)) / len(days)

    # A product that sold enough either side of the line to measure its
    # own ratio uses its own; the rest climb to their group, which moves
    # every member alike and so adds no scatter. The thresholds inside each
    # ratio are what decide that, which is why the ladder starts at the
    # product and is not floored at the group.
    def group(fn):
        for sc in History.scopes(k, lv):
            got = fn(sc)
            if got is not None:
                return got, sc[1] or 'the whole book'
        return None, None

    adj, why = 0.0, []
    parts = {'code': k, 'on': on, 'by_chan': by_chan}

    # Days become units first. A promotion is not worth its share of the
    # calendar, it is worth what it sells, and a promoted day shifts two to
    # three times a quiet one - nine days of promotion is nearer a fifth of
    # a month's units than a third.
    c, pull_from = group(hist.tilt)
    c = c if c else 1.0
    up = (lambda f: (f * c) / (f * c + 1.0 - f)) if c != 1.0 else (
        lambda f: f)
    w = up(on)
    parts.update(tilt=c, on_units=w)

    # (1) The promotion answers first, out of what this product fetched
    # under one, and the rest of the month out of what it fetched without
    # one - each already mixed to the plan's B2B share where both channels
    # answer, because the B2B half of a window is EPP-priced and the
    # consumer half is not. Where the month runs no promotion the quiet
    # side is the whole of it, which is the point: a Fold8 whose window is
    # a pre-order at 47% off and whose October is 9% off is priced off its
    # quiet days and not off its launch.
    mixed = f' at {b2b * 100:.0f}% B2B' if by_chan else ''
    asp = None
    if promo is not None and clean is not None:
        asp = promo * w + clean * (1.0 - w)
        why.append(f'{on * 100:.0f}% of days on promotion is '
                   f'{w * 100:.0f}% of the units at {c:.1f}x ({pull_from}): '
                   f'{promo:,.0f} on one, {clean:,.0f} off one{mixed}')
    elif clean is not None and w < 0.5:
        asp = clean
        why.append(f'{on * 100:.0f}% of days on promotion, and nothing of '
                   f'its own under one: {clean:,.0f} off one{mixed}')
    elif promo is not None and w >= 0.5:
        asp = promo
        why.append(f'{on * 100:.0f}% of days on promotion, and nothing of '
                   f'its own without one: {promo:,.0f}{mixed}')

    if asp is None:
        # Neither side is its own, so the blended ASP stands in and the
        # group's campaign rate corrects it, as it did before.
        asp = blended
        got, where = group(hist.campaign)
        if got:
            mine = hist.coverage(('sku', k))
            was = mine if mine is not None else got[0]
            whose = 'its own past' if mine is not None else where
            b = up(was)
            d = (w - b) * got[1]
            adj += d
            parts.update(was=b, gap=got[1], campaign=d, rate_from=where)
            why.append(f'{on * 100:.0f}% of days on promotion is '
                       f'{w * 100:.0f}% of the units at {c:.1f}x, against '
                       f'{b * 100:.0f}% over {whose}, at {where} rates: '
                       f'{d * 100:+.1f}pp')
    parts.update(asp=asp, promo=promo, clean=clean)

    # (3) B2B, only where the base could not already carry it per product.
    if b2b is not None and not by_chan:
        got, where = group(hist.mix)
        if got:
            # What B2B costs comes from the history, which is the only place
            # a realised discount lives. What it is measured against comes
            # from the **plan**, because the plan's B2B share is an
            # allocation and the history's is a realisation, and subtracting
            # one from the other reads a shift where there is none. Over the
            # whole book the two agree to a point, but by division they do
            # not: October's plan put REF at 41% B2B and REF sold 29%, the
            # widest gap in the sheet, and the nudge charged REF for a
            # twelve-point shift that never happened. Against its own
            # plan-side group the same row reads nearly flat.
            was, whose = None, where
            if plan_mix is not None:
                for sc in History.scopes(k, lv):
                    if sc in plan_mix:
                        was, whose = plan_mix[sc], sc[1] or 'the whole plan'
                        break
            if was is None:
                was = got[0]
            d = (b2b - was) * got[1]
            adj += d
            parts.update(b2b=b2b, b2b_was=was, b2b_nudge=d)
            why.append(f'{b2b * 100:.0f}% B2B planned against '
                       f'{was * 100:.0f}% planned for {whose}: '
                       f'{d * 100:+.1f}pp')
    base = hist.own(k)
    if base is None:
        got, _ = group(lambda sc: History._rate(hist.cg.get((sc, 'off'))))
        base = got
    room = 1.0 - (base if base is not None else 0.0)
    price = asp * (1.0 - adj / room) if room > 0.05 else asp
    price = max(price, asp * 0.5)
    parts.update(room=room, adj=adj, price=price)
    BREAKDOWN.append(parts)
    return price, 'asp', None, on, why or ['its own ASP, nothing to nudge']


def campaign_report(hist, levels, say, level='div3'):
    """What each named campaign sold at, and how much of it was a run-out.

    The model reduces a campaign to on-or-off, which is all a **forecast**
    can use: the month being priced is a calendar and not a sale. The
    window knows more. A clearance week and an ordinary trading week are
    both 'on' and they are not the same discount, and where a group is
    promoted every day of every month - REF is - the flag says nothing at
    all and this is the only place left to look.

    Two numbers per campaign. What came off the list, and **what share of
    its units were products in their last two live months** - a product
    that sold on and then stopped. A campaign that is deep *and* full of
    products on their way out is a run-out; a campaign that is deep and
    full of products still selling is a trading promotion. The flag cannot
    tell them apart and the pair of numbers can.
    """
    months = sorted({ym for (_, ym) in hist.smon})
    newest = months[-1] if months else None
    live = collections.defaultdict(list)
    for (code, ym), t in hist.smon.items():
        if t[0] >= 3:
            live[code].append(ym)
    out_months = {}
    for code, ms in live.items():
        ms.sort()
        if len(ms) >= 4 and ms[-1] != newest:
            out_months[code] = set(ms[-2:])

    rows = collections.defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for (camp, code, ym), t in hist.cm.items():
        if not camp:
            continue
        lv = levels.get(code, {})
        grp = lv.get(level) or lv.get('div1') or '(unknown)'
        r = rows[(grp, camp)]
        r[0] += t[1]
        r[1] += t[2]
        r[2] += t[0]
        if ym in out_months.get(code, ()):
            r[3] += t[0]

    say(f'\n  what each campaign sold at, by {level}:')
    say(f"    {'group':12}{'units':>8}{'off list':>10}{'run-out':>9}  "
        f"campaign")
    grps = collections.defaultdict(float)
    for (grp, _), r in rows.items():
        grps[grp] += r[2]
    for grp in sorted(grps, key=lambda g: -grps[g]):
        mine = [(c, r) for (g, c), r in rows.items() if g == grp and r[2] >= 20]
        if not mine:
            continue
        mine.sort(key=lambda x: -(1 - x[1][0] / x[1][1]) if x[1][1] else 0)
        for i, (c, r) in enumerate(mine):
            d = (1 - r[0] / r[1]) * 100 if r[1] > 0 else 0.0
            say(f"    {(grp[:12] if i == 0 else ''):12}{r[2]:8,.0f}"
                f"{d:9.1f}%{r[3] / r[2] * 100:8.0f}%  {c[:52]}")
    say('    run-out is the share of the campaign\u2019s units that were '
        'products in')
    say('    their last two live months. deep and high is a clearance; '
        'deep and low')
    say('    is a trading promotion, and the on-or-off flag reads them the '
        'same.')


def why_one(codes, hist, out, levels, say):
    """Every step of one material's price, with the months it came from.

    A pivot says a product came out wrong; it cannot say which of four
    numbers did it. This prints the lot for one material - the months that
    made its ASP, each nudge with what it was measured against, and the
    arithmetic that turns points of discount into dollars.
    """
    parts = {p['code']: p for p in BREAKDOWN}
    for raw in codes:
        k = PM.code_norm(raw)
        p, row = parts.get(k), None
        for c, v in out.items():
            if PM.code_norm(c) == k:
                row = v
                break
        say(f'\n  {raw}')
        if row is None:
            say('    not in the month\u2019s plan')
            continue
        if p is None:
            say(f"    {row['how']}: {'; '.join(row['why'] or ())}")
            say(f"    GSCM {row['gscm']:,.0f} -> {row['price']:,.0f}")
            continue

        each = sorted((ym, t) for (c, ym), t in hist.smon.items() if c == k)
        say(f"    {'month':>9}{'units':>8}{'ASP':>11}   vote")
        for ym, t in each:
            v = ('yes' if t[0] >= MIN_UNITS else f'no (under {MIN_UNITS})')
            asp = t[1] / t[0] if t[0] else 0.0
            say(f'    {ym:>9}{t[0]:8,.0f}{asp:11,.0f}   {v}')
        votes = [t[1] / t[0] for _, t in each if t[0] >= MIN_UNITS and t[1] > 0]
        if len(votes) >= MIN_MONTHS:
            say(f"    {'':9}{'':8}{p['asp']:11,.0f}   <- the average of "
                f'{len(votes)} month(s), one vote each')
        else:
            say(f"    {'':9}{'':8}{p['asp']:11,.0f}   <- under "
                f'{MIN_MONTHS} month(s) with a vote, so pooled over units')

        say(f"    promotion   {p['on'] * 100:.0f}% of the month\u2019s days"
            f" = {p.get('on_units', p['on']) * 100:.0f}% of its units "
            f"at {p.get('tilt', 1.0):.2f}x")
        pr, cl = p.get('promo'), p.get('clean')
        chan = ' (mixed B2B/B2C)' if p.get('by_chan') else ''
        if pr is not None or cl is not None:
            a = f'{pr:,.0f}' if pr is not None else '-'
            b = f'{cl:,.0f}' if cl is not None else '-'
            say(f'                on a promotion {a:>9}'
                f'   without one {b:>9}{chan}')
            say(f"                -> base {p['asp']:,.0f}")
        else:
            say(f"                neither side is its own, so the blended "
                f"{p['asp']:,.0f} stands in")
        if 'campaign' in p:
            say(f"                against {p['was'] * 100:.0f}% over its "
                f"past, at {p.get('gap', 0) * 100:.1f}pp a campaign"
                f"  ->{p['campaign'] * 100:+7.2f}pp")
        if 'deals_nudge' in p:
            say(f"    deals       {p['deals'] * 100:.0f}% of units lately "
                f"against {p['deals_was'] * 100:.0f}%"
                f"            ->{p['deals_nudge'] * 100:+7.2f}pp")
        if 'b2b_nudge' in p:
            say(f"    B2B         {p['b2b'] * 100:.0f}% planned against "
                f"{p['b2b_was'] * 100:.0f}% planned for its group"
                f"  ->{p['b2b_nudge'] * 100:+7.2f}pp")
            # What the nudge compares is plan against plan, which is
            # group-relative on purpose - a sheet that allocates a division
            # 41% B2B where it sells 29% is not forecasting a shift. But
            # that leaves a product whose **own** channel mix moved with
            # nothing to correct it, so what its window actually ran is
            # printed beside it, and a wide gap is worth knowing about.
            own = hist.mix(('sku', k))
            if own:
                say(f"                its own window ran "
                    f"{own[0] * 100:.0f}% B2B at {own[1] * 100:+.1f}pp "
                    f"on the discount"
                    + ('   <-- mix moved'
                       if abs(own[0] - p['b2b']) > 0.15 else ''))
        say(f"    {'':54}{'':4}{'-' * 9}")
        say(f"    {'':54}{'':4}{p['adj'] * 100:+8.2f}pp")
        say(f"    price       {p['asp']:,.0f} x (1 - "
            f"{p['adj'] * 100:.2f} / {p['room'] * 100:.1f}) = "
            f"{p['price']:,.0f}")
        say(f"    the sheet says {row['gscm']:,.0f}; "
            f"{row['qty']:,.0f} unit(s) planned")


def explain_terms(out, levels, say):
    """Each nudge's own contribution, per division.

    A re-price that is wrong by a *level* for a whole division is one term
    firing too hard for that division, and a price is the sum of four
    things - there is no reading it back out of the total. So the terms are
    kept apart on the way through and averaged here, in points of discount,
    unit-weighted, beside the price move they add up to.
    """
    by = {p['code']: p for p in BREAKDOWN}
    agg = {}
    for code, v in out.items():
        p = by.get(PM.code_norm(code))
        if p is None:
            continue
        lv = levels.get(PM.code_norm(code), {})
        d = lv.get('div3') or lv.get('div1') or '?'
        w = max(v['qty'], 0.0) or 1.0
        a = agg.setdefault(d, collections.defaultdict(float))
        a['w'] += w
        a['n'] += 1
        for key in ('on', 'on_units', 'campaign', 'b2b_nudge',
                    'deals_nudge', 'room'):
            a[key] += p.get(key, 0.0) * w
        a['own'] += w if p.get('promo') is not None or \
            p.get('clean') is not None else 0.0
        a['chan'] += w if p.get('by_chan') else 0.0
        a['move'] += (p['price'] / p['asp'] - 1.0) * w

    say('\n  what each nudge did, unit-weighted, in points of discount:')
    say(f"    {'division':14}{'skus':>5}{'plan days':>11}{'as units':>10}"
        f"{'own base':>10}{'by chan':>9}{'campaign':>10}{'deals':>8}"
        f"{'B2B':>8}{'room':>7}{'price move':>12}")
    for d, a in sorted(agg.items(), key=lambda x: -x[1]['w']):
        w = a['w'] or 1.0
        say(f"    {d[:14]:14}{a['n']:5.0f}{a['on'] / w * 100:10.0f}%"
            f"{a['on_units'] / w * 100:9.0f}%{a['own'] / w * 100:9.0f}%"
            f"{a['chan'] / w * 100:8.0f}%{a['campaign'] / w * 100:9.1f}pp"
            f"{a['deals_nudge'] / w * 100:7.1f}pp"
            f"{a['b2b_nudge'] / w * 100:7.1f}pp{a['room'] / w * 100:6.0f}%"
            f"{a['move'] / w * 100:11.1f}%")
    say('    plan days are the month\u2019s calendar and as units is '
        'the same after a')
    say('    promoted day\u2019s selling strength. own base is the share '
        'priced off its')
    say('    own promoted and quiet days, by chan the share of those '
        'mixed B2B/B2C;')
    say('    the campaign nudge only fires on what is left.')
    say('    a positive nudge is a deeper discount, so a cheaper price;')
    say('    the move is what the three come to once divided by the room.')


def price_for(code, plan, canon, hist, levels, days, gscm, say_why=None,
              scope: str = 'range', rrp_at=None, new_cap: float = 0.0,
              b2b: float = None, flat_days: bool = False,
              by_units: bool = True):
    """One material's re-priced month, and how it was arrived at.

    The month is walked a day at a time because a campaign covers days, not
    months: a product on Boost Week for nine days of October is not the same
    price as one on it for all thirty-one.
    """
    rrp = rrp_of(plan, code)
    lv = levels.get(PM.code_norm(code), {})
    k = PM.code_norm(code)
    where = []

    deep = SCOPES.index(scope if scope in SCOPES else 'sku')
    own = hist.own(k)

    # The plan says what share of this material's October is meant to go out
    # on the B2B account, and the history says what share went that way
    # before and how much deeper that side discounts. Where the two shares
    # differ, the blended discount the history gives is the discount of the
    # wrong mix, and the difference is worth exactly (shift x gap).
    #
    # It stays one price. The sheet quotes one price per material across both
    # accounts and so does this - what moves is how much of the B2B discount
    # is carried in it, in proportion to how much B2B the month is planning.
    shift = 0.0
    if b2b is not None:
        for sc in History.scopes(k, lv):
            m = hist.mix(sc)
            if m is not None:
                shift = (b2b - m[0]) * m[1]
                break

    def disc(camp):
        """This product under this campaign, then the ways round not having it.

        The order is the point. What this product came off its list price the
        last time this same campaign ran is the thing being asked for. Where
        it has never run it, its own recent discount under anything else
        comes next - a product's own behaviour beats another product's,
        whatever promotion that other one was on. Borrowing from a group at
        all is off unless --scope asks for it.
        """
        d = hist.discount(('sku', k), camp)
        if d is not None:
            return d, 'this product, same promotion'
        ladder = ((('range', lv.get('range')), lv.get('range')),
                  (('div3', lv.get('div3')), lv.get('div3')),
                  (('div1', lv.get('div1')), lv.get('div1')),
                  (('all', ''), 'the whole book'))
        for sc, name in ladder[:deep]:
            if sc[1] is None:
                continue
            d = hist.lent(sc, camp, by_units)
            if d is not None:
                return d, f'{name}, same promotion'
        if own is not None:
            return own, 'this product, six-month average'
        return None, None

    def pull_for(camp):
        """How much of the month's selling this day is worth, against one.

        A promotion day is not a thirty-first of the month. It sells harder
        than a quiet one, so it carries more of the month's price, and the
        calendar average that treats them alike prices the month as though
        nobody waited for the sale.
        """
        if flat_days or not camp:
            return 1.0
        for sc in History.scopes(k, lv):
            p = hist.pull(sc, camp)
            if p is not None:
                return p
        return 1.0

    if rrp and (own is not None or hist.discount(('sku', k), ANY) is not None
                or deep):
        total, wsum, on = 0.0, 0.0, 0
        used = collections.Counter()
        for day in days:
            camp = campaign_at(plan, canon, k, day)
            if camp:
                on += 1
            d, from_ = disc(camp)
            if d is None:
                total = None
                break
            used[(camp or '(no campaign)', from_)] += 1
            w = pull_for(camp)
            wsum += w
            total += w * rrp * (1.0 - min(0.95, max(0.0, d + shift)))
        if total is not None:
            price = total / (wsum or len(days))
            where = [f'{c} x{n} ({f})' for (c, f), n in used.most_common(4)]
            if abs(shift) >= 0.001:
                where.append(f'{shift * 100:+.1f}pp for a '
                             f'{b2b * 100:.0f}% B2B plan')
            return price, 'rrp', rrp, on / len(days), where
    # Its own ASP, where it has one and no list price to discount.
    asp = hist.asp(k)
    if asp:
        return asp, 'asp', rrp, 0.0, ['six-month ASP']

    # Nothing of its own at all: a product this window has never seen. Say so,
    # name what was leant on, and price off that rather than quietly keeping a
    # number the sheet already had.
    near = nearest(k, lv, rrp, hist, levels, rrp_at or (lambda c: None))
    if near:
        d = hist.own(near)
        if rrp and d is not None:
            # The neighbour a launch resembles is usually the model it
            # replaces, and that model is at the end of its life and at its
            # deepest discount. Inheriting it prices a new phone as a
            # run-out. The cap is off by default because how much of this is
            # real is a measurement, not a guess - `price_spread` breaks the
            # error out by `how` and the `new` row is where it would show.
            capped = min(d, new_cap) if new_cap else d
            note = (f'new SKU; nearest {near} at {d * 100:.1f}% off list'
                    + (f', capped to {capped * 100:.1f}%'
                       if capped < d else ''))
            # The neighbour's discount is at the neighbour's own mix, so it
            # needs the same correction as any other - otherwise a new SKU
            # is the one row on the sheet priced at somebody else's B2B
            # share.
            if abs(shift) >= 0.001:
                note += f'; {shift * 100:+.1f}pp for a {b2b * 100:.0f}% B2B plan'
            out = min(0.95, max(0.0, capped + shift))
            return rrp * (1.0 - out), 'new', rrp, 0.0, [note]
        a = hist.asp(near)
        if a:
            return a, 'new', rrp, 0.0, [f'new SKU; ASP of nearest {near}']
    return gscm, 'kept', rrp, 0.0, ['no list price and no history']


def reprice(folder: Path, ym: int, back: int, plan_stems, say=print,
            scope: str = 'range', decay: float = 0.0, also=None,
            source: str = 'auto', new_cap: float = 0.0,
            no_mix: bool = False, flat_days: bool = False,
            by_units: bool = True, model: str = 'simple',
            explain: bool = False, pooled: bool = False,
            campaigns: str = '', clearance: bool = True,
            why=()) -> dict:
    """{code: {...}} - the re-priced month, with how each price was reached.

    `also` is {code: price} for materials the month's plan leaves out but
    that are quoted a price all the same - the sheet carries three months,
    and one planned for the later two still has an October price on its row.
    A price can be worked out for them like any other, and a product that
    sells without a plan line is exactly the one somebody wants a number
    for.
    """
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

    # A clearance is a shelf being emptied, not a sale being run, and a
    # window that averages one in carries a run-out forward into a month
    # that is not running one. So where the month being priced has no
    # clearance for a product, that product's past clearances come out of
    # the window entirely - the days as well as the sales, or its coverage
    # would count a stretch the discount tally never saw.
    skip = None
    if clearance:
        span = month_days(ym)
        keep = collections.defaultdict(set)
        for c in planned['items']:
            k = PM.code_norm(c)
            for d in span:
                keep[k] |= special_kinds(campaign_at(plan, canon, k, d))
        on_one = sum(1 for v in keep.values() if v)
        kinds = sorted({w for v in keep.values() for w in v})
        say(f'  {on_one:,} of {len(planned["items"]):,} material(s) are on '
            f'a {"/".join(kinds) if kinds else "special"} campaign in the '
            f'month being priced; for the rest, what they sold under one '
            f'is left out of the window')

        def skip(code, camp):
            got = special_kinds(camp)
            return bool(got) and not (got & keep.get(code, frozenset()))

    months = months_back(ym, back)
    say(f'\nreading what those products sold at over '
        f'{MONTHS[(months[0] % 100) - 1]} .. '
        f'{MONTHS[(months[-1] % 100) - 1]}:')
    hist = read_history(folder, plan, canon, months, levels, say=say,
                        half=decay, source=source, want_days=True,
                        pooled=pooled, by_units=by_units, skip=skip)
    if decay:
        say(f'  weighted towards the recent: a line {decay:g} month(s) older '
            'counts half as much')
    if model == 'simple':
        c = hist.campaign(('all', ''))
        if c:
            say(f'  a campaign covered {c[0] * 100:.0f}% of the window\u2019s '
                f'product-days and went {c[1] * 100:+.1f}pp deeper')
    elif flat_days:
        say('  every day of the month weighted alike')
    else:
        got = sorted(p for p in (hist.pull(('all', ''), c)
                                 for c in {c for (sc, c) in hist.vol
                                           if sc == ('all', '') and c})
                     if p is not None)
        if got:
            say(f'  {len(got)} campaign(s) with a measurable pull on volume, '
                f'median {got[len(got) // 2]:.2f}x an ordinary day -')
            say('  a day that sells twice as hard carries twice as much of '
                'the month\u2019s price')
        else:
            say('  no campaign sold on enough days to weight by, so every '
                'day counts alike')
    if not no_mix:
        m = hist.mix(('all', ''))
        if m is None:
            say('  no channel on the history, so the plan\u2019s B2B share '
                'cannot be applied')
        else:
            say(f'  B2B took {m[0] * 100:.1f}% of the history\u2019s units '
                f'at {m[1] * 100:+.1f}pp on the discount; the plan\u2019s '
                'own')
            say('  share per material moves each price by the difference')
    if model == 'simple':
        say('  each product off its own six-month ASP, nudged by its '
            'group\u2019s ratios - nothing borrowed')
    elif scope != 'all':
        say(f'  the discount may be borrowed no further than {scope} - '
            'past that a product falls to its own ASP, then to the sheet')
    else:
        say('  the discount may be borrowed from the whole book - a list '
            'price times what every other category came off theirs')

    extra = 0
    for code, px in (also or {}).items():
        if code in planned['items'] or not px:
            continue
        planned['items'][code] = {
            'qty': 0.0, 'amt_aud': 0.0, 'amt_usd': 0.0,
            'aud': px, 'usd': 0.0, 'chain': ['', '', '', ''],
        }
        extra += 1
    if extra:
        say(f'  {extra:,} more material(s) the month does not plan but does '
            'price - re-priced too, at nought planned units')

    # The plan's own B2B share, per group, so the B2B nudge can measure a
    # planned share against a planned share. A sheet that allocates a
    # division 41% B2B where it sells 29% is not forecasting a shift; it is
    # allocating, and both sides of the subtraction have to come from the
    # same side of that fence.
    plan_mix = {}
    if not no_mix:
        tally = collections.defaultdict(lambda: [0.0, 0.0, 0])
        for code, it in planned['items'].items():
            q, b = it.get('qty') or 0.0, it.get('b2b')
            if q <= 0 or b is None:
                continue
            for sc in History.scopes(PM.code_norm(code),
                                     levels.get(PM.code_norm(code), {})):
                t = tally[sc]
                t[0] += q * b
                t[1] += q
                t[2] += 1
        plan_mix = {sc: t[0] / t[1] for sc, t in tally.items()
                    if t[1] > 0 and t[2] >= MIN_SKUS}

    days = month_days(ym)
    # One lookup per code, shared with the nearest-neighbour search, which
    # asks for a lot of them.
    rrp_cache: dict = {}

    def rrp_at(c):
        if c not in rrp_cache:
            rrp_cache[c] = rrp_of(plan, c)
        return rrp_cache[c]

    out = {}
    how = collections.Counter()
    for code, it in planned['items'].items():
        if model == 'simple':
            price, kind, rrp, promo, where = simple_price(
                code, plan, canon, hist, levels, days, it['aud'], months,
                b2b=(None if no_mix else it.get('b2b')),
                plan_mix=plan_mix)
        else:
            price, kind, rrp, promo, where = price_for(
                code, plan, canon, hist, levels, days, it['aud'],
                scope=scope, rrp_at=rrp_at, new_cap=new_cap,
                flat_days=flat_days, by_units=by_units,
                b2b=(None if no_mix else it.get('b2b')))
        how[kind] += 1
        # The nearest SKU is named on the row, not only in the prose, so a
        # sheet can filter on it: a new product priced off a neighbour is a
        # judgement someone may want to overrule one line at a time.
        near = ''
        if kind == 'new' and where:
            near = where[0].split('nearest ')[-1].split(' ')[0].rstrip(';')
        out[code] = {
            'gscm': it['aud'], 'price': round(price, 2), 'how': kind,
            'rrp': rrp, 'promo_days': round(promo, 3), 'qty': it['qty'],
            'near': near, 'why': '; '.join(where),
            'chain': it['chain'],
        }
    say(f'\nre-priced {len(out):,} material(s): '
        + ', '.join(f'{n:,} {k}' for k, n in how.most_common()))
    if model == 'simple':
        say('  asp  = its own ASP, then nudged by what its promotion, '
            'B2B share and unplanned deals do differently this '
            'month than they did over the window')
        say('  kept = no six-month ASP of its own, so the GSCM price is '
            'unchanged')
        fresh = [(c, v) for c, v in out.items() if v['how'] == 'kept']
        if fresh:
            say(f'\n  {len(fresh):,} material(s) with no record to price '
                f'from, {sum(v["qty"] for _, v in fresh):,.0f} planned '
                'unit(s)')
        if explain:
            explain_terms(out, levels, say)
        if campaigns:
            campaign_report(hist, levels, say, level=campaigns)
        if why:
            why_one(why, hist, out, levels, say)
        return out
    say('  rrp  = list price x what this product came off it under the same')
    say('         promotion, and its own six-month discount on the rest')
    say('  asp  = no list price in the plan, so its six-month ASP stands in')
    say('  new  = nothing of its own in the window - priced off the nearest')
    say('         product, which is named on the row')
    say('  kept = not even that, so the GSCM price is unchanged')
    fresh = [(c, v) for c, v in out.items() if v['how'] == 'new']
    if fresh:
        say(f'\n  {len(fresh):,} new SKU(s), '
            f'{sum(v["qty"] for _, v in fresh):,.0f} planned unit(s):')
        for c, v in sorted(fresh, key=lambda kv: -kv[1]['qty'])[:12]:
            say(f'    {c:<24}{v["qty"]:>8,.0f}  {v["why"]}')
        if len(fresh) > 12:
            say(f'    ... and {len(fresh) - 12:,} more')
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
    ap.add_argument('--model', default='simple',
                    choices=('simple', 'campaign'),
                    help='simple: each product\u2019s own six-month ASP, '
                         'nudged by three group ratios. campaign: the older '
                         'per-product per-campaign discount off RRP, with '
                         'its borrowing ladder')
    ap.add_argument('--scope', default='range', choices=SCOPES,
                    help='how far a discount may be borrowed from when the '
                         'product has none of its own (default div1, which '
                         'blocks only the whole book; all restores the '
                         'behaviour before this flag existed)')
    ap.add_argument('--flat-days', action='store_true',
                    help='weight every day of the month alike instead of '
                         'by how hard each campaign sells')
    ap.add_argument('--no-mix', action='store_true',
                    help='ignore the plan\u2019s B2B share and price every '
                         'material at the mix the history happened to have')
    ap.add_argument('--by-members', dest='by_units', action='store_false',
                    default=True,
                    help='when a group answers for a product that has none '
                         'of its own, give it the average of its products '
                         'rather than of its units. Measured, that is about '
                         'a point shallower, so it raises a price')
    ap.add_argument('--min-units', type=int, default=MIN_UNITS,
                    metavar='N',
                    help=f'units a product needs before its own discount is '
                         f'read rather than its range\u2019s (default '
                         f'{MIN_UNITS})')
    ap.add_argument('--new-cap', type=float, default=0.0, metavar='PCT',
                    help='the deepest discount a new SKU may inherit from '
                         'the product it is priced off, e.g. 25 for a '
                         'quarter off list (default 0: no cap)')
    ap.add_argument('--source', default='auto',
                    choices=('auto', 'dtc', 'orders'),
                    help='where the history comes from: the DTC export where '
                         'the folder has one (default), or the order export')
    ap.add_argument('--pooled-asp', dest='pooled', action='store_true',
                    help="the window's ASP pooled over its units, as it was "
                         'before - a product sells most when it is cheapest, '
                         'so this reads the window a couple of points too '
                         'cheap')
    ap.add_argument('--why', nargs='+', default=(), metavar='CODE',
                    help='every step of one material\u2019s price - the '
                         'months that made its ASP and each nudge with '
                         'what it was measured against')
    ap.add_argument('--keep-clearance', dest='clearance',
                    action='store_false',
                    help='leave a product\u2019s past clearances, secret '
                         'sales and EOFY in the window even where the '
                         'month being priced is running none - as before')
    ap.add_argument('--campaigns', nargs='?', const='div3', default='',
                    choices=('range', 'div3', 'div1'),
                    help='what each named campaign sold at, and how much of '
                         'it was a product on its way out - which is how a '
                         'clearance is told from a trading promotion')
    ap.add_argument('--explain', action='store_true',
                    help='what each nudge did to each division, in points '
                         'of discount - for a month that comes out wrong by '
                         'a level rather than a scatter')
    ap.add_argument('--decay', type=float, default=0.0, metavar='MONTHS',
                    help='half-life: a line this much older counts half as '
                         'much (default 0, every month alike)')
    ap.add_argument('--out', default=None, metavar='FILE',
                    help='default docs/reprice_<month>.csv')
    args = ap.parse_args()

    set_min_units(args.min_units)
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

    out = reprice(folder, full, args.back, args.plan, explain=args.explain,
                  pooled=args.pooled, campaigns=args.campaigns,
                  clearance=args.clearance, why=args.why,
                  scope=args.scope, decay=args.decay, source=args.source,
                  new_cap=args.new_cap / 100.0, no_mix=args.no_mix,
                  flat_days=args.flat_days, by_units=args.by_units,
                  model=args.model)

    path = Path(args.out) if args.out else ROOT / 'docs' / f'reprice_{ym}.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Material', 'Biz', 'Div 1', 'Div 2', 'Div 3',
                    'Planned qty', 'GSCM price', 'Re-priced', 'Change %',
                    'RRP', 'Promo days', 'From', 'Nearest SKU', 'Why'])
        for code, v in sorted(out.items(),
                              key=lambda kv: -abs((kv[1]['price']
                                                   - kv[1]['gscm'])
                                                  * kv[1]['qty'])):
            ch = (v['price'] / v['gscm'] - 1) * 100 if v['gscm'] else None
            w.writerow([code, *(v['chain'] + [''] * 4)[:4], v['qty'],
                        f"{v['gscm']:.2f}", f"{v['price']:.2f}",
                        '' if ch is None else f'{ch:+.1f}',
                        '' if v['rrp'] is None else f"{v['rrp']:.2f}",
                        f"{v['promo_days'] * 100:.0f}%", v['how'],
                        v.get('near', ''), v['why']])
    print(f'\n-> {path}  ({len(out):,} material(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

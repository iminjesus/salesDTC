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
import re
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


def set_min_months(n: int) -> None:
    """How many months a product needs before one month one vote applies.

    Three was measured better than two when every month of a window was in
    it. Leaving a month's clearances, EOFY and launches out takes months
    away, so a product that had four can be left with two and drop to the
    pooled figure - which weights its heaviest month hardest, and a heavy
    month is heavy because it was discounting. That is the bias the vote
    exists to remove, so the bar is worth re-measuring now that the window
    is cut: `--min-months 2`.
    """
    global MIN_MONTHS
    MIN_MONTHS = max(1, int(n or 1))


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
# A launch belongs with them and for the same reason, which one product
# showed plainly: a Fold8's whole window is its pre-order, its B2C side
# sold at about 2,300 where October's S.COM price is 3,271.82, and the
# promotion split could not reach it because the launch offers were on the
# quiet days too. A launch happens once.
#
# Matched **by kind**, so a month running a Secret Sale keeps a product's
# past Secret Sales and still drops its past EOFY, and a product on Tab S12
# Launch in October keeps its own launch months. One list, one place.
SPECIAL = ('clearance', 'secret', 'eofy', 'launch', 'pre-order')


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


def rrp_of(plan, code: str, since=None):
    """The list price the plan quotes for a product.

    The RRP column where there is one, and the plan has several price columns
    that are not it - S.COM_Price, T1_Price, a promo price. Reading those as a
    list price would put the discount at nought on exactly the products that
    were discounted, so where there is no RRP the highest price quoted stands
    in: in a promotion plan, the list price is the one nothing is off.

    Commonest value wins among the lines: the same product is planned many
    times over, and one mistyped cell should not become the price.

    `since` is the start of the history window, and holds the vote to the
    lines that reach into it. The plan files carry every campaign they have
    ever held, so the commonest RRP was the commonest **over all time**, and
    a price that was in force for a year outvoted the one in force now on a
    product that has had one price change. Everything else in this module is
    read over the same six months; the list price was the one figure that
    was not.

    A line with no date is kept either way. Undated is not old - it is
    unsaid - and dropping it would lose the plans that carry no window at
    all. Where the window leaves nothing, the whole file answers rather than
    the product losing its price.
    """
    cands, _ = plan.candidates(PM.code_norm(code))
    if since is not None and cands:
        live = [c for c in cands
                if (c.get('end') or c.get('start')) is None
                or (c.get('end') or c.get('start')) >= since]
        if live:
            cands = live
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
        # (bucket, channel) -> [paid, listed, units] on days with no
        # campaign on them. What a product fetches off its list price when
        # nothing is running, which is a group fact and a steady one - see
        # `quiet`.
        self.qc: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # The same tally over days that carried **no live offer**, which is
        # a different and much better definition of a quiet day than the
        # one above. `qc` reads the plan's campaign column, and that column
        # is worth 1.1 points book-wide - a day the plan names no campaign
        # is routinely a day a launch offer or a standing EPP rule was
        # running at full depth, which is how a Fold8 in its pre-order came
        # out at 44.9% off as its *ordinary* price. `bq` keys on whether
        # `Offer_Detail` put money on the table that day instead, which the
        # plan states exactly.
        self.bq: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # And its mirror, the days an offer was live. A month running one
        # wants this side; the two are different questions and the window
        # answers neither.
        self.oq: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        # And the ASP over those same days, month by month, so it can take
        # one month one vote exactly as `asp` does.
        self.bs: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        self.bmon: dict = collections.defaultdict(lambda: [0.0, 0.0])
        # And its mirror: the days an offer **was** live. A month that is
        # running a promotion wants this one, exactly as a month that is
        # not wants the other; the window ASP is the two of them averaged
        # together at whatever mix the window happened to have, which is
        # neither answer.
        self.os: dict = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
        self.omon: dict = collections.defaultdict(lambda: [0.0, 0.0])
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
            deal=False, ym=None, bare=None):
        """`bare` is True where no offer was live that day.

        It is read off the plan's `Offer_Detail` windows, not off its
        campaign column, and where the caller does not supply it the
        campaign column stands in - so a history built without the plan's
        offer text behaves exactly as it always did.
        """
        if qty <= 0:
            return
        if bare is None:
            bare = not camp
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
        side = self.bs if bare else self.os
        side[code][0] += qty * w
        side[code][1] += amt * w
        side[code][2] += qty
        if ym is not None:
            t = self.smon[(code, ym)]
            t[0] += qty * w
            t[1] += amt * w
            t = (self.bmon if bare else self.omon)[(code, ym)]
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
            if not camp:
                for c in (chan, ''):
                    if c is None:
                        continue
                    t = self.qc[(scope, c)]
                    t[0] += amt * w
                    t[1] += qty * rrp * w
                    t[2] += qty
            for c in (chan, ''):
                if c is None:
                    continue
                t = (self.bq if bare else self.oq)[(scope, c)]
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

    def quiet(self, scope, chan=''):
        """What this bucket comes off its list price with nothing running.

        **A group fact, and deliberately not a product one.** The quiet
        price of a product in its launch months is a launch price - a Fold8
        sold at about 2,300 on days no campaign covered, where October's
        S.COM price is 3,271.82 - so reading it per product reads the
        launch again by another name. A whole group's ordinary markdown off
        list is steady, and applied to the month's own list price it says
        what the product will fetch when nothing is on.
        """
        t = self.qc.get((scope, chan))
        if not t or t[2] < MIN_UNITS or t[1] <= 0:
            return None
        return max(0.0, 1.0 - t[0] / t[1])

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

    def onoff(self, scope, chan=''):
        """What this bucket comes off list on days an offer WAS live.

        The mirror of `bare`. A month running a promotion is priced off
        this side and a month running none off the other; the window
        pools them at whatever mix the window happened to have, which is
        the mix of the past and not of the month being priced.
        """
        t = self.oq.get((scope, chan))
        if not t or t[2] < MIN_UNITS or t[1] <= 0:
            return None
        return max(0.0, 1.0 - t[0] / t[1])

    def bare(self, scope, chan=''):
        """What this bucket comes off list on days that carried no offer.

        The same question `quiet` asks, with the day picked by whether the
        plan put **money** on the table rather than by whether it wrote a
        campaign name. That distinction is the whole of it: book-wide a day
        the plan calls a campaign is only 1.1 points deeper than a day it
        does not, because the days it calls quiet are routinely running a
        launch offer or a standing EPP rule at full depth.

        Unlike `quiet` this is safe to read **per product**. `quiet` is a
        group fact on purpose, because a product's plan-quiet days inside
        its launch are launch days and reading them per product reads the
        launch again under another name - a Fold8 at 2,300 on days no
        campaign covered, against an October store price of 3,271.82. Here
        those days are not quiet at all: the pre-order offer was live on
        them and they are excluded, so what is left really is the product
        trading with nothing on.
        """
        t = self.bq.get((scope, chan))
        if not t or t[2] < MIN_UNITS or t[1] <= 0:
            return None
        return max(0.0, 1.0 - t[0] / t[1])

    # Unit-weighted, and deliberately, where `asp` takes one month one
    # vote. The vote exists because a product sells most when it is
    # cheapest, so a pooled window leans on its own cheap months - but
    # that bias is in the *pollution*, and `--floor` removes the
    # pollution rather than averaging around it. On
    # SM-F971BZWGATS the floor took August's clean ASP from 1,538 to
    # 1,776; weighting that corrected August by its real volume is the
    # right answer, and voting it down a second time would correct the
    # same thing twice. Pooled 1,834 against a voted 1,937 on that
    # product, and the pooled one is the one kept.

    def offer_asp(self, code):
        """The product's ASP over its offer days, one month one vote.

        `bare_asp` with the sides swapped. What it fetches **while a
        promotion is on**, which is the right base for pricing a month
        that is running one - the window ASP mixes the two sides at
        whatever share the window happened to have, and that share is not
        the share the month being priced will have.
        """
        return self._vote(self.os, self.omon, code)

    def _vote(self, tot, mon, code):
        q, a, raw = tot.get(code, [0.0, 0.0, 0.0])
        if raw < MIN_UNITS or q <= 0:
            return None
        if self.pooled:
            return a / q
        each = [t[1] / t[0] for (c, _), t in mon.items()
                if c == code and t[0] >= MIN_UNITS and t[1] > 0]
        return sum(each) / len(each) if len(each) >= MIN_MONTHS else a / q

    def bare_asp(self, code):
        """The product's ASP over its no-offer days, one month one vote.

        `asp` with the offer days taken out. The window ASP is a promotion
        average rather than an ordinary price - book-wide the median
        product sold 67% of its window under a live offer - and this is
        the part of it that was not.
        """
        return self._vote(self.bs, self.bmon, code)

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


def launch_span(plan, grace: int = 0,
                kinds=('launch', 'pre-order')) -> dict:
    """`code -> {days inside a launch}`, its written end pushed out by `grace`.

    There is **no launch price** anywhere in these files. The promotion
    plan writes a campaign name, a start and an end, and - on a pre-order
    line - usually no price at all. So a rule that wants to leave a launch
    out has only its dates to go on, and that is all this uses.

    The dates alone are not quite enough, and the gap is the point of
    `grace`. `SM-F971BZWGATS` ran FF8 Pre-Order from 16 July to 5 August.
    The plan stops there; the realised price does not. August 6th to 31st
    came in at 1,538 against a 2,999 list - 48.7% off, where the pre-order
    itself realised 48.9% - and September at 2,072, 30.9% off. On the
    plan's own dates those 200 August units are an ordinary month, and
    they outweigh September's 29 by seven to one.

    `grace` is how many days past the written end the launch is treated as
    still running. It is a **fitted number and nothing else** - the files
    carry no fact that sets it - so it is off by default and the way to
    choose it is to measure several, not to reason about one.
    """
    out: dict = {}
    for r in plan.rows:
        name = ' '.join(x for x in (r.get('camp') or ()) if x).lower()
        if not any(w in name for w in kinds):
            continue
        a, b = r.get('start'), r.get('end')
        if not a or not b or b < a:
            continue
        b += timedelta(days=max(0, grace))
        days = out.setdefault(PM.code_norm(r.get('code') or ''), set())
        d = a
        while d <= b:
            days.add(d)
            d += timedelta(days=1)
    return out


def read_history(folder: Path, plan, canon, months: list, levels: dict,
                 say=print, half: float = 0.0, source: str = 'auto',
                 want_days: bool = True, pooled: bool = False,
                 by_units: bool = True, skip=None,
                 clean_quiet: bool = False, drop_day=None,
                 band=None, no_deals: bool = False,
                 no_vouch=(), floor=None, ceil=None,
                 trim_in=None, learn=None) -> History:
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
    # Which days the plan put money on the table for, product by product.
    # Built once; `History.add` keys its no-offer tallies on it rather than
    # on the campaign column.
    live: dict = {}
    if source != 'orders':
        want = set(months)
        rows = DTC.read(folder, want, say=say) if DTC.files(folder) else []
        if rows and clean_quiet:
            mine: dict = {}
            for r in plan.rows:
                mine.setdefault(PM.code_norm(r.get('code') or ''),
                                []).append(r)
            live = offer_live(mine,
                              {chan_key(r) for r in rows if r['qty'] > 0},
                              {r['code'] for r in rows}, say=say,
                              named=plan_names(plan))
        if rows:
            miss = 0
            dropped = [0, 0.0]
            # The middle of each product's own price distribution. A
            # voucher, a staff order or a bundle allocation sits in the
            # tail of it, and an ASP is money over units, so one line at
            # 300 against a 2,999 list cancels several at full price.
            #
            # It is a judgement, not a fact, so it is off by default and
            # the run says what it costs. A 30-70 band keeps the middle
            # 40% of a product's units by construction, so the drop is
            # large on purpose - what matters is whether the prices it
            # keeps predict the month better, which is a --compare
            # question.
            odd = [0, 0.0]
            trimmed = price_band(rows, *band) if band else set()
            # The narrower instrument for the same problem. A band guesses
            # from the price that a line was disturbed; these two columns
            # say so. A voucher and a trade-in bonus are both Samsung's
            # money off the line, so both go - what sits outside a price
            # is the traded phone's own value, and that is already outside
            # the revenue a discount is measured from.
            gift = [0, 0.0]
            want_v = {str(v).strip().upper() for v in no_vouch or ()
                      if str(v).strip()}
            deep = deep_cut(rows, floor or 0.0, ceil or 0.0,
                            only=trim_in)
            # What the floor caught, turned into a rule about the
            # mechanic that caught it. See `learn_stems`.
            learnt: set = set()
            if learn is not None and deep:
                learnt = learn_stems(rows, deep, learn)
                if learnt:
                    was = len(deep)
                    for i, r in enumerate(rows):
                        if trim_in is not None and not trim_in(r['code']):
                            continue
                        if learnt & {voucher_stem(c) for c in
                                     voucher_codes(r.get('vcode'))}:
                            deep.add(i)
                    grew = len(deep) - was
            for i, r in enumerate(rows):
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
                if (skip is not None and skip(code, camp, r.get('ym'))) \
                        or (drop_day is not None and r['day'] is not None
                            and r['day'] in drop_day.get(code, ())):
                    dropped[0] += 1
                    dropped[1] += r['qty']
                    continue
                if i in trimmed or i in deep:
                    odd[0] += 1
                    odd[1] += r['qty']
                    continue
                if no_deals and (r.get('vouch') or r.get('trade')):
                    gift[0] += 1
                    gift[1] += r['qty']
                    continue
                if want_v and voucher_hit(voucher_codes(r.get('vcode')),
                                          want_v):
                    gift[0] += 1
                    gift[1] += r['qty']
                    continue
                if not rrp:
                    miss += 1
                h.add(code, levels.get(code, {}), camp,
                      r['qty'], r['amt'], rrp, r['day'],
                      chan=(r['dist'] or '').upper() or None,
                      deal=bool(r.get('trade') or r.get('vouch')),
                      ym=r.get('ym'),
                      # A line at nil revenue is never a quiet day,
                      # whatever the plan says. It is a gift with
                      # purchase, observed - no model name to parse, no
                      # bracket to read, no line to match. The plan is
                      # needed only to say whether a gift will run in the
                      # month being priced; for the window it already
                      # happened and the export shows it.
                      bare=((r['day'] is not None and r['amt'] > 0
                             and not offer_on(live, code, r['day'],
                                              chan_key(r)))
                            if clean_quiet else None))
            # One pass over every product and every day of the window,
            # so a campaign's days are counted whether or not it sold on
            # them - a promotion that sold nothing is still a day it was on.
            if want_days:
                span = [(m, d) for m in months for d in month_days(m)]
                for code in list(h.skus):
                    lv = levels.get(code, {})
                    for m, d in span:
                        camp = campaign_at(plan, canon, code, d)
                        # A day whose sales were dropped is not a day the
                        # product traded, or its coverage would count a
                        # window the discount tally never saw.
                        if skip is not None and skip(code, camp, m):
                            continue
                        if drop_day is not None and d in drop_day.get(code,
                                                                      ()):
                            continue
                        h.saw(code, lv, camp)
            say(f'  {len(rows):,} DTC line(s); {len(h.skus):,} product(s) '
                'with a realised price')
            if band:
                tot = len(rows) or 1
                say(f'  price band {band[0] * 100:.0f}-{band[1] * 100:.0f}'
                    f' of each product\u2019s own prices, by rank: '
                    f'{odd[0]:,} line(s) '
                    f'({odd[0] / tot * 100:.1f}%), {odd[1]:,.0f} unit(s) '
                    'left out of every ASP and every discount')
            if floor or ceil:
                tot = len(rows) or 1
                ends = ' and '.join(
                    x for x in ((f'{floor * 100:.0f}% below' if floor
                                 else ''),
                                (f'{ceil * 100:.0f}% above' if ceil
                                 else '')) if x)
                say(f'  more than {ends} what the product fetches '
                    f'voucher-free: {len(deep):,} line(s) '
                    f'({len(deep) / tot * 100:.1f}%) left out of every ASP '
                    'and every discount')
                if trim_in is not None and not deep:
                    say('  nothing was trimmed - no line matched the '
                        'group(s) given to --trim-in')
                if learn is not None:
                    if learnt:
                        say(f'  {len(learnt):,} voucher stem(s) have '
                            f'{learn * 100:.0f}%+ of their lines below '
                            f'the floor, so the rest of those lines went '
                            f'too ({grew:,} more): '
                            + ', '.join(sorted(learnt)[:12]))
                    else:
                        say('  no voucher stem has enough of its lines '
                            'below the floor to be condemned as a whole')
                # And what they were. The point of a floor is that it
                # needs no list - nobody can hunt a book of 1,500
                # products for the odd mechanic by hand - so the list
                # comes out as **output**. What it names is a finding,
                # not a setting: it says what the floor caught, and the
                # next month's floor catches that month's.
                who: dict = collections.defaultdict(lambda: [0, set()])
                for i in deep:
                    r = rows[i]
                    got = voucher_codes(r.get('vcode'))
                    for n in ({voucher_stem(c) for c in got}
                              or {'(no voucher code)'}):
                        who[n][0] += 1
                        who[n][1].add(PM.code_norm(r['code']))
                if who:
                    rank = sorted(who.items(),
                                  key=lambda kv: -kv[1][0])[:8]
                    say('  what it caught, by voucher stem: '
                        + ', '.join(f'{n} ({c:,} line(s), '
                                    f'{len(ps):,} product(s))'
                                    for n, (c, ps) in rank))
            if no_deals or want_v:
                tot = len(rows) or 1
                what = ('voucher and trade-in' if no_deals
                        else 'voucher ' + ', '.join(sorted(want_v)))
                say(f'  {what} line(s) left out of every ASP and every '
                    f'discount: {gift[0]:,} ({gift[0] / tot * 100:.1f}%), '
                    f'{gift[1]:,.0f} unit(s)')
            if dropped[0]:
                say(f'  {dropped[0]:,} line(s), {dropped[1]:,.0f} unit(s) '
                    'left out: a clearance, secret sale, EOFY or launch '
                    'the month '
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


HOLD_AT = ('biz', 'div1', 'div2', 'div3', 'range')


VOUCH_SPLIT = re.compile(r'[,;|/]+')


def voucher_codes(text) -> list:
    """The codes on one line. The column is `Voucher Code(s)` and plural."""
    return [c.strip().upper() for c in VOUCH_SPLIT.split(text or '')
            if c.strip()]


def voucher_hit(codes, want) -> bool:
    """Does any code on this line match any name asked for?

    Substring and case-insensitive, so a family of codes can be named by
    its stem without listing every suffix the site minted.
    """
    return any(w in c for c in codes for w in want)


def voucher_stem(code: str) -> str:
    """The family a voucher code belongs to: its first token.

    The codes are not arbitrary. One product's November reads

        FF8F-ERGE-8TYB-EL1B    1,635.909
        FF8R-T2TL-T162-AALL    1,635.909
        FF8C-17SB-3B8B-RBT1    2,115.264
        LS-FOLD8               2,817.273

    and the depth goes with the **stem**, not with the code: every
    `FF8F-` and `FF8R-` line came in at 1,636 or below while `FF8C-`,
    `FF8E-` and `FF8S-` traded normally. There are a handful of stems
    where there are thousands of codes, which is what makes this
    nameable at all - `--drop-voucher FF8F FF8R` is a standing rule and
    not a list to re-keep every month.
    """
    return (code or '').split('-')[0].strip().upper()


def voucher_report(rows, say=print, top: int = 25, least: int = 20) -> None:
    """Which voucher codes move a price, and by how much.

    Not every voucher disturbs an ASP. A $50 site credit on a 3,000 phone
    is 1.7% and belongs in the average; a staff code at half price is a
    different transaction wearing the same column. Dropping all of them
    throws the first away to catch the second, and dropping none leaves
    the second in - so the first thing to do is **name them**.

    Each code is read two ways. Against the **list price**, which says how
    deep the line went; and against **what the same product fetched on
    its own voucher-free lines**, which is the number that matters here,
    because it is this product's own ordinary price and not a book-wide
    average. A code 2% under that is noise in the ASP. A code 40% under
    it is the thing being hunted.
    """
    def table(keyed, head, show):
        units = sum(t[0] for t in keyed.values())
        say(f'\n  {len(keyed):,} {head} over {units:,.0f} unit(s)')
        say(f"    {'':<26}{'units':>8}{'products':>10}{'off list':>10}"
            f"{'under its own clean price':>27}")
        for c, t in sorted(keyed.items(), key=lambda kv: -kv[1][0])[:show]:
            off = (f'{(1 - t[1] / t[2]) * 100:8.1f}%' if t[2] > 0
                   else f"{'-':>9}")
            under = (f'{(1 - (t[1] / t[0]) / (t[3] / t[4])) * 100:25.1f}%'
                     if t[4] >= least and t[3] > 0 else f"{'too thin':>26}")
            say(f'    {c[:25]:<26}{t[0]:8,.0f}{len(t[5]):10,}{off}{under}')
        if len(keyed) > show:
            say(f'    ... and {len(keyed) - show:,} more')

    base: dict = {}
    for r in rows:
        if (r['qty'] <= 0 or r['amt'] <= 0
                or r.get('vouch') or r.get('trade')):
            continue
        t = base.setdefault(PM.code_norm(r['code']), [0.0, 0.0])
        t[0] += r['qty']
        t[1] += r['amt']
    clean = {c: t[1] / t[0] for c, t in base.items() if t[0] > 0}

    by: dict = {}
    stem: dict = {}
    for r in rows:
        if r['qty'] <= 0:
            continue
        got = voucher_codes(r.get('vcode'))
        if not got:
            continue
        own = clean.get(PM.code_norm(r['code']))
        for keyed, names in ((by, got),
                             (stem, {voucher_stem(c) for c in got})):
            for c in names:
                t = keyed.setdefault(c, [0.0, 0.0, 0.0, 0.0, 0.0, set()])
                t[0] += r['qty']
                t[1] += r['amt']
                t[2] += r['qty'] * (r['rrp'] or 0.0)
                t[5].add(PM.code_norm(r['code']))
                if own:
                    t[3] += r['qty'] * own
                    t[4] += r['qty']

    if not by:
        say('  no line carries a voucher code - the column is empty or '
            'not in the export')
        return
    # The stems first: that is the unit a rule can be written in. A
    # code is minted per order and there are thousands of them; the
    # family it belongs to is a handful, and the depth goes with the
    # family.
    table(stem, 'voucher stem(s)', top)
    table(by, 'voucher code(s)', min(top, 12))
    wide = [c for c, t in stem.items()
            if len(t[5]) > 1 and t[4] >= least and t[3] > 0
            and (1 - (t[1] / t[0]) / (t[3] / t[4])) > 0.20]
    one = sum(1 for t in stem.values() if len(t[5]) == 1)
    say(f'\n  the `products` column is what decides whether a stem is a '
        'rule or a code.\n  A stem on one product is that product\u2019s '
        'own voucher and naming it buys one\n  product; a stem across '
        f'hundreds is a mechanic. {one:,} of {len(stem):,} stem(s) '
        'touch\n  one product only.')
    if wide:
        say('\n  deep (20+ points under) AND on more than one product - '
            'the ones worth naming:')
        say('    ' + ', '.join(sorted(wide, key=lambda c: -stem[c][0])[:20]))
    else:
        say('\n  no stem is both deep and spread over several products, '
            'so a stem list would\n  be a list of individual products. '
            '--floor is the rule that needs no names')
    say(f'\n  "under its own clean price" compares each code against what '
        f'the same\n  products fetched on their voucher-free lines, over '
        f'the codes with {least}+\n  unit(s) of that comparison. Deep and '
        'heavy is what --drop-voucher is for;\n  a code a point or two '
        'under is part of the price and should stay')
    both = sum(1 for r in rows if len(voucher_codes(r.get('vcode'))) > 1)
    if both:
        say(f'\n  {both:,} line(s) carry more than one code and are '
            'counted under each of them,\n  because which of them took '
            'the money is not in the file. A deep code can\n  therefore '
            'make a shallow one it travels with look deeper than it is')


def deep_cut(rows, floor: float = 0.0, ceil: float = 0.0,
             least: int = MIN_UNITS, only=None) -> set:
    """Indices of lines far below what the product fetches voucher-free.

    The answer to "not every voucher disturbs a price, but some do" that
    does **not** require naming them. A voucher code is minted per
    campaign and per product, the same shape as `promotion_rule`, which
    four attempts at classifying failed at; and a hand-kept list of deep
    codes would have to be re-kept every month.

    So the depth is read instead of the label. Each product's own
    voucher-free, trade-in-free lines give the price it ordinarily
    fetches, and a line more than `floor` below that is dropped -
    whichever voucher did it, or none.

    Two properties the band does not have. A product with nothing odd in
    it loses **nothing**, where a 40:95 band throws away its cheapest 40%
    regardless; and the cut is in the units of the problem - "more than
    30% under its own price" - rather than in a rank that happens to land
    somewhere useful.

    `only` narrows it to one or more groups. The trim is not equally
    good everywhere - across October and November MX improved on both
    months while DA and VD each improved on one and lost on the other -
    and a tool that can only apply a rule to the whole book has to take
    the average of those.

    `ceil` is the same cut at the other end, and it is not symmetry for
    its own sake. A floor only ever pushes a price **up**: it removes
    cheap lines, every ASP rises, and the month is forecast dearer. Where
    the model is already dearer than the month turns out - which
    book-wide it is, by 62 on November - that makes the level worse
    whatever it does to the scatter. A ceiling pushes the other way, so
    the two together can take both tails off without moving the middle.

    A product whose voucher-free lines come to fewer than `least` units
    has no reliable base and is left alone: its odd lines may be the only
    lines it has.
    """
    if not floor and not ceil:
        return set()
    base: dict = {}
    for r in rows:
        # `amt > 0`: a gift with purchase goes out at nil and is kept in
        # every ASP, but it is not a price and must not help set the one
        # that "far below its own price" is measured against.
        if (r['qty'] > 0 and r['amt'] > 0
                and not r.get('vouch') and not r.get('trade')):
            t = base.setdefault(PM.code_norm(r['code']), [0.0, 0.0])
            t[0] += r['qty']
            t[1] += r['amt']
    own = {c: t[1] / t[0] for c, t in base.items()
           if t[0] >= least and t[1] > 0}
    out: set = set()
    for i, r in enumerate(rows):
        if r['qty'] <= 0:
            continue
        # A nil-revenue line is 100% under its own price and would be
        # caught by any floor at all - but it is a gift with purchase,
        # kept on purpose, and the day split puts it on the offer side
        # where it belongs. The floor is for prices nobody can account
        # for; this one is accounted for.
        if r['amt'] <= 0:
            continue
        if only is not None and not only(r['code']):
            continue
        p = own.get(PM.code_norm(r['code']))
        if not p:
            continue
        at = r['amt'] / r['qty']
        if floor and at < p * (1.0 - floor):
            out.add(i)
        elif ceil and at > p * (1.0 + ceil):
            out.add(i)
    return out


def learn_stems(rows, deep, share: float = 0.5,
                least: int = 5) -> set:
    """Voucher stems whose lines are **mostly** below the floor.

    The floor catches a line because of what it cost. This asks the
    next question: when a line is deep, does the voucher on it make a
    habit of it? A stem whose lines are nearly all deep is a mechanic
    that discounts, and its shallower lines belong with the rest of them
    - a `FF8F` that happens to land a point above the floor is still an
    `FF8F`.

    That is what lets the effective threshold differ by mechanic without
    anybody setting one per mechanic. A stem that is always 45% under
    goes entirely; a stem that is 12% under goes nowhere near the floor
    and is never condemned; a stem that straddles it is condemned only
    if most of it is below.

    `share` is how much of a stem has to be deep before the rest follows
    it, and `least` keeps a stem of one or two lines from being judged
    at all - one unlucky line should not condemn a mechanic.
    """
    tot: dict = collections.defaultdict(int)
    bad: dict = collections.defaultdict(int)
    for i, r in enumerate(rows):
        for st in {voucher_stem(c) for c in voucher_codes(r.get('vcode'))}:
            tot[st] += 1
            if i in deep:
                bad[st] += 1
    return {st for st, n in tot.items()
            if n >= least and bad[st] / n >= share}


def band_of(band):
    """`--band 30 70` as the pair of fractions the reader wants, or None."""
    if not band:
        return None
    lo, hi = sorted(float(v) for v in band)
    if hi > 1.5:                       # given in percent, as the help says
        lo, hi = lo / 100.0, hi / 100.0
    if not (0 <= lo < hi <= 1.0):
        raise SystemExit(f'--band {band[0]} {band[1]}: they are percentiles '
                         'of the product\u2019s own prices, so LO must be '
                         'below HI and both inside 0-100')
    return lo, hi


def price_band(rows, lo: float, hi: float, least: int = 5) -> set:
    """The indices of `rows` to leave out: each product\u2019s cheapest and
    dearest slice.

    A voucher, a staff order or a bundle allocation sits in the **tail**
    of a product\u2019s own price distribution. An ASP is money over units,
    so one line at 300 against a 2,999 list cancels several at full
    price, and the average it produces is not a price the product ever
    sold at. Cutting the tails and averaging what is left needs no theory
    about what the line was - only that it is far from everything else
    the product did.

    **Trimmed by rank, not by value**, and the difference is not small. A
    product that sold 7 of its 25 lines at exactly 1,635.909 has its 30th
    and its 40th percentile both land *on* that price, so a band that
    keeps everything from the 30th percentile upwards keeps all seven -
    asked to drop the cheapest 30%, it drops 8%. By rank the cheapest 30%
    of units go whatever they cost, and a tie at the boundary is split
    rather than kept whole.

    Units, not lines: a line of three hundred is three hundred units of
    evidence and a line of one is one. A product with fewer than `least`
    lines is not trimmed at all - cutting the middle out of four numbers
    leaves noise, not a median - and no product is ever trimmed to
    nothing.
    """
    by: dict = {}
    for i, r in enumerate(rows):
        if r['qty'] > 0 and r['amt'] > 0:
            by.setdefault(PM.code_norm(r['code']), []).append(
                (r['amt'] / r['qty'], r['qty'], i))
    out: set = set()
    for got in by.values():
        if len(got) < least:
            continue
        got.sort()
        tot = sum(q for _, q, _ in got)
        drop_lo, drop_hi = tot * lo, tot * (1.0 - hi)
        gone = set()
        acc = 0.0
        for _, qty, i in got:                      # the cheap end
            if acc >= drop_lo:
                break
            gone.add(i)
            acc += qty
        acc = 0.0
        for _, qty, i in reversed(got):            # the dear end
            if acc >= drop_hi:
                break
            gone.add(i)
            acc += qty
        if len(gone) >= len(got):                  # never trim to nothing
            continue
        out |= gone
    return out


def held_by(levels: dict, keep, planned=None) -> callable:
    """A test for "is this material in one of these groups".

    Matched against every level a product has a name at, so one flag
    covers `MX` (a Biz or a Div 1), `REF` (a Div 3) and a range alike,
    and the caller does not have to say which kind of name it is giving.

    **The GSCM sheet's own chain is a fallback.** The product master does
    not know every code the plan prices, and where it does not, the
    material had no group name at all here - so `--keep MX` matched
    nothing, held nothing, and produced a column identical to the one
    beside it while looking as though it had done the work. The sheet
    carries Biz / Div 1 / Div 2 / Div 3 on its own rows and that is
    enough to answer the question. It is used for this test only; the
    pricing ladder still reads `levels`, so nothing about how a product
    is priced changes.
    """
    hold = {str(n).strip().upper() for n in keep or () if str(n).strip()}
    if not hold:
        return lambda code: False
    chain: dict = {}
    for code, it in ((planned or {}).get('items') or {}).items():
        got = [str(v or '').strip().upper() for v in (it.get('chain') or ())]
        if any(got):
            chain[PM.code_norm(code)] = got

    def is_held(code):
        k = PM.code_norm(code)
        lv = levels.get(k) or {}
        if any((lv.get(n) or '').strip().upper() in hold for n in HOLD_AT):
            return True
        return any(v in hold for v in chain.get(k, ()))
    return is_held


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
                 months, b2b=None, plan_mix=None, rrp_at=None,
                 quiet_list=False, promo_first=True):
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
    # The promotion is answered first and the quiet days second. A month
    # being priced is a calendar of promoted and unpromoted days, and the
    # product's own record holds both, so each part is answered out of the
    # part of its past that matches - rather than taking one blended ASP
    # and nudging it towards the month.
    #
    # It is the costlier of the two on October: 191 against 177 for the
    # blended ASP with a nudge, over the same rows. `--asp-first` is that
    # older arrangement, kept to compare against.
    promo, own_quiet, by_chan = (
        hist.sides(k, b2b) if promo_first else (None, None, False))

    # (2) The quiet part of the month. By default it is what the product
    # itself fetched on days no campaign covered; `--quiet-list` takes the
    # sheet's own planned price for the month instead, which is the better
    # answer for a product too new to have a past worth averaging.
    rrp = (rrp_at(k) if rrp_at else None) or rrp_of(plan, code)
    clean, quiet_from = None, None
    if not quiet_list:
        clean, quiet_from = own_quiet, 'its own quiet days'
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

    sheet_price = bool(quiet_list and gscm)
    if sheet_price:
        # The month's own planned price, as the sheet writes it. A product
        # that is not on promotion sells at the price that was set for it,
        # and that price is already there for a product too new to have a
        # past worth averaging - which is the case this is for.
        #
        # No markdown is read off anybody. A group's markdown comes from
        # the products that have been selling longest, and dragging a new
        # model down to those is reading their age as its discount. The
        # sheet carries one price per material across E-STORE and
        # E-STORE_B2B, and over October it landed within 1.4% of what the
        # portals actually realised, so it needs no channel mix either.
        clean, quiet_from = gscm, "the sheet's own price"
    parts.update(clean_from=quiet_from, rrp=rrp)

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
                   f'{promo:,.0f} of its own on one{mixed}, '
                   f'{clean:,.0f} off one'
                   + (f' ({quiet_from})' if sheet_price or not rrp
                      else f' - {rrp:,.0f} list at {quiet_from}'))
    elif clean is not None:
        asp = clean
        why.append(f'{on * 100:.0f}% of days on promotion and nothing of '
                   f'its own under one: '
                   + ('' if sheet_price or not rrp
                      else f'{rrp:,.0f} list at {quiet_from} = ')
                   + f'{clean:,.0f}'
                   + (f' ({quiet_from})' if sheet_price else ''))
    elif promo is not None and w >= 0.5:
        asp = promo
        why.append(f'{on * 100:.0f}% of days on promotion, and no list '
                   f'price to work from: {promo:,.0f}{mixed}')

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

    # (3) The discounts no plan will ever carry: a voucher, a trade-in, an
    # e-promoter code. They are standing offers, so nothing forecasts them;
    # what can be done is to notice a group has been running them harder
    # lately than its window average and move the price by the difference.
    got, where = group(lambda sc: hist.deals(sc, months))
    if got:
        d = (got[0] - got[1]) * got[2]
        adj += d
        parts.update(deals=got[0], deals_was=got[1], deals_nudge=d)
        why.append(f'unplanned deals on {got[0] * 100:.0f}% of units lately '
                   f'against {got[1] * 100:.0f}% ({where}): {d * 100:+.1f}pp')

    # (4) B2B, only where the base could not already carry it per product.
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


def why_one(codes, hist, out, levels, say, clearance: bool = True):
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
        if p.get('model') == 'rrp':
            say(f"    list price {p['rrp']:,.2f}, over the window\u2019s plan "
                f"lines")
            say(f"    {p['on'] * 100:.0f}% of the month\u2019s days carry a "
                'campaign name')
            if p.get('bare') is not None:
                say(f"    {p['bare'] * 100:.0f}% of them carry no live "
                    'offer, which is what the no-offer rungs ask.')
                say('    The two differ because a day with no '
                    'campaign name on it routinely has a\n    '
                    'launch offer or a standing EPP rule running '
                    'at full depth')
            say('\n    the month a day at a time. Every day of it is '
                'priced on its own and the\n    month is their average, '
                'weighted by how hard each sells:')
            say('      what was on   what the plan had live that day')
            say('      days          how many days of the month that was')
            say('      pull          how hard such a day sells against an '
                'ordinary one')
            say('      priced off    which rung answered. "days like these" '
                'means days with the\n                    same campaign on, '
                'or with nothing on')
            if p.get('bare') is not None:
                say('                    with --clean-quiet the day is '
                    'sorted by whether an offer\n                    was '
                    'live instead, and answered from the window days '
                    'that\n                    were the same way')
            say(f"\n    {'what was on':<30}{'days':>5}{'pull':>6}  "
                f"{'priced off':<32}{'the day':>11}")
            for camp, from_, n, kind, d, pull in p['rows']:
                camp = 'nothing on' if camp == '(no campaign)' else camp
                if kind == 'at':
                    at, shown = d, f'{d:,.2f}'
                else:
                    at = p['rrp'] * (1 - min(0.95, max(0.0, d + p['shift'])))
                    shown = f'{d * 100:.1f}% off'
                say(f'    {camp[:29]:<30}{n:>5}{pull:>6.2f}'
                    f'  {from_[:31]:<32}{at:>11,.2f}'
                    + ('' if kind == 'at' else f'   ({shown})'))
            if abs(p['shift']) >= 0.001:
                say(f"\n    B2B {p['b2b'] * 100:.0f}% planned moves every "
                    f"discount day by {p['shift'] * 100:+.1f}pp")
            say(f"\n    the month is those days averaged by pull "
                f"-> {p['price']:,.2f}")
            say(f"    GSCM {row['gscm']:,.2f} -> {row['price']:,.2f}"
                f"  ({(row['price'] / row['gscm'] - 1) * 100:+.1f}%)")
            if p.get('bare') is not None:
                mine = sorted({ym for (c, ym) in hist.bmon if c == k}
                              | {ym for (c, ym) in hist.omon if c == k})
                say('\n    the window split by whether an offer was live, '
                    'month by month. A month\n    that is running a '
                    'promotion wants the offer side; a month that is not '
                    'wants\n    the other. The window ASP is the two '
                    'averaged at whatever mix the window\n    happened to '
                    'have, which is neither answer:')
                say(f"    {'month':>9}{'offer units':>13}{'offer ASP':>12}"
                    f"{'clean units':>13}{'clean ASP':>12}"
                    f"{'all units':>11}{'window ASP':>12}")
                whole = dict(each)
                for ym in mine:
                    o = hist.omon.get((k, ym), [0.0, 0.0])
                    c2 = hist.bmon.get((k, ym), [0.0, 0.0])
                    w = whole.get(ym, [0.0, 0.0])
                    say(f'    {ym:>9}{o[0]:13,.0f}'
                        f'{(o[1] / o[0] if o[0] else 0):12,.0f}'
                        f'{c2[0]:13,.0f}'
                        f'{(c2[1] / c2[0] if c2[0] else 0):12,.0f}'
                        f'{w[0]:11,.0f}'
                        f'{(w[1] / w[0] if w[0] else 0):12,.0f}')
                oa, ba, wa = (hist.offer_asp(k), hist.bare_asp(k),
                              hist.asp(k))
                # "too thin" and "not there at all" are different
                # answers and the second one is actionable. The clearance
                # drop deletes a launch's days from the window before the
                # offer split ever runs, so on a product whose promotion
                # WAS its launch the offer side is empty by construction,
                # not for want of units - and --keep-clearance is what
                # brings it back.
                gone = (clearance
                        and not any(c == k for c, _ in hist.omon))

                def dash(v, side=''):
                    if v:
                        return f'{v:,.2f}'
                    if side == 'offer' and gone:
                        return 'left out of the window'
                    return f'too thin to read'
                say(f"\n    {'on offer':<26}{dash(oa, 'offer'):>24}")
                say(f"    {'with no offer live':<26}{dash(ba):>24}")
                say(f"    {'the whole window':<26}{dash(wa):>24}")
                if gone:
                    say('    the offer side is empty because this '
                        'product\u2019s promotion was its launch, and a '
                        'launch\n    the priced month is not running is '
                        'dropped from the window before the\n    split '
                        'runs. --keep-clearance leaves it in')
                say('    one month one vote in each, a month under '
                    f'{MIN_UNITS} units getting none')
            if any(k2 == 'at' for _, _, _, k2, _, _ in p['rows']):
                say(f"\n    a rung reading `at` is a **price**, not a "
                    'discount, so the list price does not enter it. Where '
                    'that\n    price is the six-month ASP, the months '
                    'behind it are:')
                say(f"    {'month':>9}{'units':>8}{'ASP':>11}   vote")
                for ym, t in each:
                    v = ('yes' if t[0] >= MIN_UNITS
                         else f'no (under {MIN_UNITS})')
                    asp = t[1] / t[0] if t[0] else 0.0
                    say(f'    {ym:>9}{t[0]:8,.0f}{asp:11,.0f}   {v}')
            continue
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
            if pr is not None:
                say(f'                under a promotion {pr:>12,.0f}'
                    f'   its own{chan}')
                got = hist.sc.get(k) or {}
                for ch in ('B2B', 'B2C', None):
                    live = [t for (_, o, c), t in got.items()
                            if o and (c == ch if ch else True) and t[0] > 0]
                    if not live:
                        continue
                    q = sum(t[0] for t in live)
                    say(f"      {'':16}{'on ' + (ch or 'both'):>12}"
                        f"{len([t for t in live if t[0] >= MIN_UNITS]):>4}"
                        f" month(s){q:>8,.0f}u"
                        f"{(sum(t[1] for t in live) / q if q else 0):>10,.0f}")
            else:
                say('                under a promotion            -'
                    '   nothing of its own')
            if cl is not None:
                how = p.get('clean_from') or '-'
                lead = ('' if 'sheet' in how or not p.get('rrp')
                        else f"{p['rrp']:,.0f} list at ")
                say(f"                without one       {cl:>12,.0f}"
                    f"   {lead}{how}")
            say(f"                -> base {p['asp']:,.0f}")
        else:
            say(f"                neither side answers, so the blended "
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
              by_units: bool = True, plan_mix=None, gscm_at=None,
              new_from: str = 'sheet', quote_first: bool = False,
              clean_quiet: bool = False):
    """One material's re-priced month, and how it was arrived at.

    The month is walked a day at a time because a campaign covers days, not
    months: a product on Boost Week for nine days of October is not the same
    price as one on it for all thirty-one.
    """
    # Through the cache, so this model reads the same windowed list price
    # the rest of the module does rather than a vote over every line.
    rrp = (rrp_at(code) if rrp_at else None) or rrp_of(plan, code)
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
            if m is None:
                continue
            # Plan against plan. What B2B costs comes from the history,
            # which is the only place a realised discount lives; what it is
            # measured against comes from the plan, because the sheet's
            # share is an allocation and the history's is a realisation.
            # October's plan put REF at 41% B2B where REF sold 29%, and
            # measuring one against the other charged it for a shift that
            # never happened.
            was = m[0]
            if plan_mix is not None:
                for sc2 in History.scopes(k, lv):
                    if sc2 in plan_mix:
                        was = plan_mix[sc2]
                        break
            shift = (b2b - was) * m[1]
            break

    # The product's own six-month ASP, which is a price and not a discount
    # off one. It is the rung under the promotion, so a day it answers is
    # priced at it rather than at the list price less something.
    own_asp = hist.asp(k)

    # And the nearest product's, for a code the window has never seen. Found
    # on the first day that asks for it and not before: the search walks
    # every product in the history, and a month of materials that all have a
    # record of their own would pay for it once each for nothing.
    lean = {}

    def near_asp():
        """The nearest product's price, brought to this product's level.

        **Off by default, because every form of it was measured and lost.**
        On October's 22 such materials the sheet's own price came in at a
        deviation of 244 and the three ways of leaning on a neighbour at
        293 (its ASP flat), 543 (its ASP at its rate off the sheet) and
        worse again (its discount off list). A product with no record and
        no quote is one somebody priced deliberately, and nothing here
        beats that.

        Why each form fails, since the reasoning looks sound until it is
        measured. The neighbour is nearly always the model being replaced:

            its discount    the deeper that model was cut on its way out,
                            the cheaper the launch
            its ASP flat    that model lists lower, so the launch comes out
                            cheap by the whole gap
            its rate off
            the sheet       the numerator is a six-month ASP and the
                            denominator is an October sheet price, and for
                            a model being run out those are two different
                            periods of its life. The ratio runs over 1 and
                            prices a launch above its own sheet

        Scaling by the **list** price is not a fourth option, it is the
        first one written differently:

            its ASP x (my list / its list)
              = its list x (1 - d) x my list / its list
              = my list x (1 - d)

        `--new-from asp` and `--new-from rate` turn the other two back on
        to be measured again.
        """
        if 'who' not in lean:
            lean['who'] = lean['asp'] = None
            lean['how'] = 'nearest'
            if new_from != 'sheet':
                who = nearest(k, lv, rrp, hist, levels,
                              rrp_at or (lambda c: None))
                a = hist.asp(who) if who else None
                if a and new_from == 'rate' and gscm_at and gscm:
                    theirs = gscm_at(who)
                    if theirs and theirs > 0:
                        a *= gscm / theirs
                        lean['how'] = 'at its sheet rate, nearest'
                lean['who'], lean['asp'] = who, a
        return lean['who'], lean['asp']

    def quoted(day):
        """What the plan itself quotes this product at on this day.

        A **launch campaign has no past by definition**. Tab S12 Launch has
        never run before, so neither the product nor its family has a record
        of it, and every rung above this one is silent - which is why a
        launch kept falling all the way to another product’s ASP. The plan
        line for that campaign carries its own price, and for this product
        under this campaign that is the best evidence there is.

        It is what was **quoted**, not what was collected: a voucher, a
        trade-in or a stacked offer moves the two apart, and a realised
        price beats a quoted one wherever there is one. That is the whole
        reason this sits below every rung that has one, and above the rungs
        that borrow from another product.

        `S.COM_Price` is the store’s own column, which is the channel being
        priced. Where a day carries two live lines the cheaper quote wins:
        that is the offer a customer would take.
        """
        live, _, _ = PM.plan_state(plan, k, day)
        got = [p for c in live for col, p in (c.get('prices') or {}).items()
               if col == 'S.COM_Price' and p and p > 0]
        return min(got) if got else None

    def offered(day):
        """Did the plan have money on the table for this product that day?

        The priced month's own side of the no-offer rung. `campaign_at`
        answers whether a **name** was in force, which is a different
        question and worth 1.1 points book-wide.
        """
        live, _, _ = PM.plan_state(plan, k, day)
        return any(offer_values(c.get('detail') or '') for c in live)

    def disc(camp, day=None, live=None):
        """This product under this campaign, then the ways round not having it.

        Returns `(kind, value, from_)`. `kind` is 'off' for a discount off
        the list price and 'at' for a price in its own right, because the
        rungs are not all the same shape: the promotion rungs say what comes
        off list, and the one under them says what the product has simply
        been fetching.

        The order is the point:

            1  what this product came off list the last time **this same
               campaign** ran - the thing actually being asked
            2  never run it: the same campaign at its model family, then
               Div 3, then Div 1, as far as --scope allows
            3  no group answer either: this product's own **six-month ASP**,
               as a price. Its own record beats another product's, whatever
               promotion that other one was on
            4  a quiet day for a product with no record at all: its group's
               ordinary markdown off list

        Rung 4 is the one a new product lands on, and the only one that can
        answer for it - a group's ordinary markdown is a group fact by
        design (see History.quiet), where a *promoted* rate borrowed for a
        quiet day would price the month as a sale. Without it the whole day
        walk gave up on the first quiet day and the product fell through to
        a nearest-neighbour's blended discount, which on a launch is the
        discount of the model it replaces - at the end of its life and at
        its deepest.
        """
        ladder = ((('range', lv.get('range')), lv.get('range')),
                  (('div3', lv.get('div3')), lv.get('div3')),
                  (('div1', lv.get('div1')), lv.get('div1')),
                  (('all', ''), 'the whole book'))
        # The day sorted by whether the plan had **money** on the table,
        # and answered from the days of the window that were the same way.
        #
        # Not by whether the plan wrote a campaign name. That column is
        # worth 1.1 points book-wide, and keying on it got this wrong in
        # both directions on one product: SM-F971BZWGATS has no campaign
        # name on any day of October, so every one of its 31 days took
        # the no-offer rung - including the seven that were running
        # `[S.COM] Save $300`. A day with an offer on it is not a quiet
        # day because nobody wrote a name for it.
        #
        # Both sides are read, because they are two questions and the
        # window answers neither: the median product sold 67% of its
        # window under a live offer, and its no-offer price came out
        # dearer on 75% of the book.
        if clean_quiet:
            if live is None:
                live = offered(day) if day is not None else False
            ask, word = ((hist.onoff, 'an offer live') if live
                         else (hist.bare, 'no offer live'))
            d = ask(('sku', k))
            if d is not None:
                return 'off', d, f'this product, days with {word}'
            for sc, name in ladder[:deep]:
                if sc[1] is None:
                    continue
                d = ask(sc)
                if d is not None:
                    return 'off', d, f'{name}, days with {word}'
            a = (hist.offer_asp if live else hist.bare_asp)(k)
            if a:
                return 'at', a, ('this product\u2019s ASP over its '
                                 + ('offer' if live else 'no-offer')
                                 + ' days')
        d = hist.discount(('sku', k), camp)
        if d is not None:
            return 'off', d, 'this product, days like these'
        for sc, name in ladder[:deep]:
            if sc[1] is None:
                continue
            d = hist.lent(sc, camp, by_units)
            if d is not None:
                return 'off', d, f'{name}, days like these'
        # Below the realised rungs, two answers for a day whose campaign
        # nobody has a record of: what this product fetches in an ordinary
        # month, and what the plan quotes for that campaign.
        #
        # Which of them goes first is a real question and the two months
        # disagree, so it is a switch. The ASP is realised and the quote is
        # not, which is the case for the ASP. Against it: a campaign with
        # no record anywhere is usually one that has not run inside the
        # window, and the clearest example is **Black Friday** - the
        # deepest discounting month of the year, named in the cumulative
        # plan from 2025 but with no sales in a six-month window and no
        # `25 DTC Nov` in the folder to put there. Pricing it at an
        # ordinary month's ASP prices the year's cheapest month as an
        # average one, and November came out dear by about as much as
        # October came out cheap.
        q = quoted(day) if day is not None else None
        if quote_first and q:
            return 'at', q, "the plan’s quoted price"
        if own_asp:
            return 'at', own_asp, "this product’s six-month ASP"
        if q:
            return 'at', q, "the plan’s quoted price"
        # Nothing of its own: a new product. The promotion rungs above have
        # already had their turn - they are tried first for a new product
        # exactly as for an old one, and a launch is usually on a campaign
        # its family has run - so what is left is a day no promotion rule
        # covers, and the answer for that is **what something similar
        # fetches**, not what something similar comes off list.
        #
        # Those are not the same thing, and the difference is the whole
        # reason this rung is a price. The product a launch most resembles
        # is the model it replaces, and that model is at the end of its life
        # and at its deepest discount: inheriting its *discount* prices a
        # new phone as a run-out, and the deeper the neighbour has been cut
        # the cheaper the launch comes out. Its ASP carries no such slope.
        who, a = near_asp()
        if a:
            return 'at', a, f'{lean["how"]} {who}'
        if not camp:
            for sc in History.scopes(k, lv):
                q = hist.quiet(sc)
                if q is not None:
                    return 'off', q, (f'{sc[1] or "the whole book"}, '
                                      'its ordinary markdown')
        return None, None, None

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

    if rrp and (own is not None or own_asp
                or hist.discount(('sku', k), ANY) is not None or deep):
        total, wsum, on = 0.0, 0.0, 0
        used = collections.Counter()
        gave: dict = {}
        for day in days:
            camp = campaign_at(plan, canon, k, day)
            if camp:
                on += 1
            live = offered(day) if clean_quiet else False
            kind, d, from_ = disc(camp, day, live)
            if d is None:
                total = None
                break
            # What the day is called on the row. A day the plan writes no
            # campaign name on is not therefore a quiet day - it can be
            # running an offer with money in it and no name, which is how
            # SM-F971BZWGATS spends the first week of October. Saying
            # "nothing on" of such a day and then pricing it off days
            # with an offer live reads as a contradiction, and is not one.
            tag = camp or ('an unnamed offer' if live else '(no campaign)')
            used[(tag, from_)] += 1
            gave[(tag, from_)] = (kind, d)
            w = pull_for(camp)
            wsum += w
            if kind == 'at':
                # An ASP already has the product's own discount in it, so
                # the B2B shift is the only thing left to apply - and it is
                # measured in points off the list price, which is what it
                # is worth here too. `rrp * (1 - d - shift)` is
                # `rrp * (1 - d)` less `rrp * shift`, so a price rung takes
                # the same money off and the two rungs stay comparable.
                total += w * max(d * 0.5, d - rrp * shift)
            else:
                total += w * rrp * (1.0 - min(0.95, max(0.0, d + shift)))
        if total is not None:
            price = total / (wsum or len(days))
            # Spelled out rather than coded. `Boost Week x9 (this product,
            # same promotion)` needed three things explaining - that x9 was
            # days, that the bracket was where the number came from, and
            # what "same promotion" meant on a day with no promotion on it.
            where = [f'{n} day(s) '
                     + ('with nothing on' if c == '(no campaign)'
                        else f'under {c}')
                     + f', priced off {f}'
                     for (c, f), n in used.most_common(4)]
            if abs(shift) >= 0.001:
                where.append(f'{shift * 100:+.1f}pp for a '
                             f'{b2b * 100:.0f}% B2B plan')
            # A month that leaned on a neighbour for any of its days is a
            # new product's month, whatever the promotion rungs covered, and
            # the row says so: `price_spread --by how` breaks the error out
            # by rung, and a launch hidden inside `rrp` is the one row it
            # most needs to see on its own.
            leaned = any('nearest' in f for _, f in used)
            # `plan` where the plan's own quote carried a day and no
            # neighbour was needed: it is neither a realised price nor
            # somebody else's, and a rung that cannot be told apart cannot
            # be measured. `price_spread --by how` is where it shows.
            told = any('quoted price' in f for _, f in used)
            BREAKDOWN.append({
                'code': k, 'model': 'rrp', 'rrp': rrp, 'shift': shift,
                'b2b': b2b, 'price': price, 'on': on / len(days),
                'bare': ((sum(0 if offered(d) else 1 for d in days)
                          / len(days)) if clean_quiet else None),
                'tilt': not flat_days, 'days': len(days),
                'rows': [(c, f, n, *gave[(c, f)], pull_for(
                    '' if c in ('(no campaign)', 'an unnamed offer')
                    else c))
                         for (c, f), n in used.most_common()],
            })
            return (price, 'new' if leaned else 'plan' if told else 'rrp',
                    rrp, on / len(days), where)
    # Its own ASP, where it has one and no list price to discount.
    asp = hist.asp(k)
    if asp:
        return asp, 'asp', rrp, 0.0, ['six-month ASP']

    # Nothing of its own at all: a product this window has never seen. Say so,
    # name what was leant on, and price off that rather than quietly keeping a
    # number the sheet already had.
    near, a = near_asp()
    if near:
        # Its ASP before its discount, for the reason given at the rung
        # above: a neighbour's discount is its own position in its own life
        # and a launch inheriting one is priced as a run-out.
        if a:
            note = f'new SKU; {lean["how"]} {near}'
            if abs(shift) >= 0.001:
                note += (f'; {shift * 100:+.1f}pp for a '
                         f'{b2b * 100:.0f}% B2B plan')
                a = max(a * 0.5, a - (rrp or a) * shift)
            return a, 'new', rrp, 0.0, [note]
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
    return gscm, 'kept', rrp, 0.0, ['no list price and no history']


def reprice(folder: Path, ym: int, back: int, plan_stems, say=print,
            scope: str = 'range', decay: float = 0.0, also=None,
            source: str = 'auto', new_cap: float = 0.0,
            no_mix: bool = False, flat_days: bool = False,
            by_units: bool = True, model: str = 'simple',
            explain: bool = False, pooled: bool = False,
            campaigns: str = '', clearance: bool = True,
            why=(), quiet_list: bool = False,
            promo_first: bool = True, actual: bool = False,
            new_from: str = 'sheet', keep=(),
            drop_launch: bool = False,
            clean_quiet: bool = False,
            grace: int | None = None, band=None,
            no_deals: bool = False, no_vouch=(),
            floor=None, ceil=None, trim_in=(), learn=None) -> dict:
    """{code: {...}} - the re-priced month, with how each price was reached.

    `also` is {code: price} for materials the month's plan leaves out but
    that are quoted a price all the same - the sheet carries three months,
    and one planned for the later two still has an October price on its row.
    A price can be worked out for them like any other, and a product that
    sells without a plan line is exactly the one somebody wants a number
    for.
    """
    import plan_price as PP

    say('reading the plan to re-price:')
    # Whichever sheet carries this month. The folder holds one a month now,
    # and the first one its name turns up is not always the one being
    # priced.
    gf, _ = PP.pick_month(folder, 'gscm', ym % 10000, say=say)
    if gf is None:
        raise SystemExit(f'no gscm_* sheet in {folder} prices that month')
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

        def skip(code, camp, at=None):
            got = special_kinds(camp)
            return bool(got) and not (got & keep.get(code, frozenset()))

    # The launch, by date. `skip` above drops the days the plan names a
    # launch on; this pushes that end out by `grace` days, because the
    # plan stops writing the offer before the price moves. Only for
    # products the priced month is not launching itself - for those the
    # launch is the thing being forecast.
    drop_day = None
    if grace is not None:
        lspan = launch_span(plan, grace)
        hot = {'launch', 'pre-order'}
        drop_day = ({c: d for c, d in lspan.items()
                     if not (keep.get(c, frozenset()) & hot)}
                    if clearance else lspan)
        n = sum(len(d) for d in drop_day.values())
        say(f'  the launch left out by date, its written end pushed out '
            f'{grace} day(s): {len(drop_day):,} product(s), {n:,} '
            'product-day(s)')

    months = months_back(ym, back)
    # A launch does not end where the plan stops naming it. A product in
    # its pre-order sells at the pre-order price on the days the plan calls
    # quiet as well, because the offer covered them - the campaign column
    # says what was *named*, and the launch price was simply the price.
    #
    # `skip` above drops the days the plan names, which leaves the quiet
    # ones behind as though they were the product trading normally. On a
    # product whose whole window is its launch that is the only history
    # there is, and it becomes the ordinary price: SM-F971BZWGATS came out
    # at 45% off a 2,999 list in a November running nothing.
    #
    # So where a month carried a launch for a product at all, the whole of
    # that month goes - unless the month being priced is running one too,
    # in which case the launch is the thing being forecast.
    launch_out: dict = {}
    if clearance and drop_launch:
        base = skip
        hot = {'launch', 'pre-order'}
        for c in planned['items']:
            k = PM.code_norm(c)
            if keep.get(k, frozenset()) & hot:
                continue              # the priced month is a launch as well
            for m in months:
                for d in month_days(m):
                    if special_kinds(campaign_at(plan, canon, k, d)) & hot:
                        launch_out.setdefault(k, set()).add(m)
                        break
        if launch_out:
            say(f'  {len(launch_out):,} material(s) had a launch or a '
                'pre-order inside the window and are not launching this '
                f'month - the\n  {sum(len(v) for v in launch_out.values()):,} '
                'month(s) that carried one come out whole, quiet days and '
                'all (--drop-launch-months)')

        def skip(code, camp, at=None):              # noqa: F811
            if at is not None and at in launch_out.get(code, ()):
                return True
            return base(code, camp)
    say(f'\nreading what those products sold at over '
        f'{MONTHS[(months[0] % 100) - 1]} .. '
        f'{MONTHS[(months[-1] % 100) - 1]}:')
    hist = read_history(folder, plan, canon, months, levels, say=say,
                        half=decay, source=source, want_days=True,
                        pooled=pooled, by_units=by_units, skip=skip,
                        clean_quiet=clean_quiet, drop_day=drop_day,
                        band=band, no_deals=no_deals,
                        no_vouch=no_vouch, floor=floor, ceil=ceil,
                        trim_in=(held_by(levels, trim_in, planned)
                                 if trim_in else None),
                        learn=learn)
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

    # The list price over the same six months as everything else. See
    # rrp_of: the vote used to run over every line the plan files hold,
    # whatever year it was written in.
    since = month_days(months[0])[0]

    def rrp_at(c):
        if c not in rrp_cache:
            rrp_cache[c] = rrp_of(plan, c, since)
        return rrp_cache[c]

    moved = 0
    for code in planned['items']:
        if rrp_at(code) != rrp_of(plan, code):
            moved += 1
    say(f'\n  the list price is read over {MONTHS[(months[0] % 100) - 1]} '
        f'onwards, like the rest: {moved:,} of '
        f'{len(planned["items"]):,} material(s) take a different one from '
        'the vote over every line the plan files hold')

    # Groups the sheet already prices better than anything here can. Named
    # rather than inferred: which they are is a measurement, and it is made
    # with `price_spread --compare`, not guessed at run time.
    #
    # On October and November both, MX was the one division the model made
    # worse. November's sheet put it at a mean of -7 and a deviation of 78
    # over 19,652 units, where the model came in at 97 - a sheet set that
    # carefully has nothing left in it to find, while DA's was out by 272
    # and the model more than halved its deviation. The model earns its
    # place where the sheet is stale and not where it is not.
    hold = {str(n).strip().upper() for n in keep if str(n).strip()}
    is_held = held_by(levels, keep, planned)
    held = 0

    out = {}
    how = collections.Counter()
    for code, it in planned['items'].items():
        if is_held(code):
            held += 1
            out[code] = {
                'gscm': it['aud'], 'price': round(it['aud'], 2),
                'how': 'kept', 'rrp': None, 'promo_days': 0.0,
                'qty': it['qty'], 'chain': it['chain'], 'near': '',
                'why': '--keep: the sheet prices this group better',
            }
            how['kept'] += 1
            continue
        if model == 'simple':
            price, kind, rrp, promo, where = simple_price(
                code, plan, canon, hist, levels, days, it['aud'], months,
                b2b=(None if no_mix else it.get('b2b')),
                plan_mix=plan_mix, rrp_at=rrp_at,
                quiet_list=quiet_list, promo_first=promo_first)
        else:
            price, kind, rrp, promo, where = price_for(
                code, plan, canon, hist, levels, days, it['aud'],
                scope=scope, rrp_at=rrp_at, new_cap=new_cap,
                flat_days=flat_days, by_units=by_units,
                plan_mix=plan_mix,
                new_from=new_from, quote_first=model == 'quote',
                clean_quiet=clean_quiet,
                gscm_at=lambda c: (planned['items'].get(c)
                                   or planned['items'].get(PM.code_norm(c))
                                   or {}).get('aud'),
                b2b=(None if no_mix else it.get('b2b')))
        how[kind] += 1
        # The nearest SKU is named on the row, not only in the prose, so a
        # sheet can filter on it: a new product priced off a neighbour is a
        # judgement someone may want to overrule one line at a time.
        near = ''
        if kind == 'new' and where:
            # The code is written three ways now - `nearest X at ...`,
            # `ASP of nearest X` and, inside a day walk, `... (ASP of
            # nearest X)` - so the trailing bracket comes off with the
            # semicolon rather than riding into the column.
            for w in where:
                if 'nearest ' in w:
                    near = w.split('nearest ')[-1].split(' ')[0].rstrip(';)')
                    break
        out[code] = {
            'gscm': it['aud'], 'price': round(price, 2), 'how': kind,
            'rrp': rrp, 'promo_days': round(promo, 3), 'qty': it['qty'],
            'near': near, 'why': '; '.join(where),
            'chain': it['chain'],
        }
    # What the month actually went out at, where the month has happened
    # enough to say. Off by default: it is another read of the order export
    # and the page's own build already has one, so only a caller that wants
    # the comparison pays for it.
    #
    # It is the realised price **to date**, not for the whole month - the
    # export stops where it stops - so a part-month reads against a full
    # month's forecast and the gap is partly calendar. The CSV says so in
    # its header.
    if actual:
        import price_spread as PS
        say('')
        sold = PS.read_month(folder, ym, say=say, source=source)
        hit = 0
        for code, v in out.items():
            got = sold.get(PM.code_norm(code))
            if got and got[0] > 0:
                v['sold'] = got[0]
                v['amt'] = got[1]
                v['asp'] = got[1] / got[0]
                hit += 1
        say(f'  {hit:,} of {len(out):,} re-priced material(s) sold in '
            f'{ym} and carry a realised price; the rest were planned and '
            'not sold')

    if held:
        say(f'\n  {held:,} material(s) in ' + ', '.join(sorted(hold))
            + ' kept at the sheet price (--keep)')
    elif hold:
        # A --keep that matches nothing used to be silent, and a silent
        # --keep is worse than a refused one: the run looks like it did
        # what was asked and the column it produces is identical to the
        # one beside it, which reads as "holding this group changes
        # nothing" when the truth is "nothing was held".
        seen: dict = {}
        for code in planned['items']:
            lv = levels.get(PM.code_norm(code)) or {}
            for n in HOLD_AT:
                v = (lv.get(n) or '').strip()
                if v:
                    seen.setdefault(n, set()).add(v)
        say(f"\n  --keep {', '.join(sorted(hold))} matched NO material - "
            'nothing was held and this run is the')
        say('  same as one without it')
        if not seen:
            say('  no product master in the folder, so no material has a '
                'group name to match on')
        else:
            for n in HOLD_AT:
                if seen.get(n):
                    got = sorted(seen[n])
                    say(f"    {n:<6} {', '.join(got[:12])}"
                        + (f' ... and {len(got) - 12} more'
                           if len(got) > 12 else ''))
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
        report(out, levels, hist, explain, campaigns, why, say,
               clearance=clearance)
        return out
    say('  rrp  = the promotion table\u2019s list price, day by day, less')
    say('         what the same promotion has been running at: this')
    say('         product\u2019s own record of it first, then its '
        f'group\u2019s as far as {scope}.')
    say('         A day neither can answer is priced at the product\u2019s')
    say('         own six-month ASP; a quiet day for a product with no')
    say('         record at all, at its group\u2019s ordinary markdown')
    say('  plan = a campaign with no past anywhere - a launch is one by')
    say('         definition - so the plan\u2019s own quoted price for the')
    say('         day stands, which is this product under this campaign')
    say('  asp  = no list price in the plan at all, so the six-month ASP')
    say('         is the whole of it')
    say('  new  = nothing of its own and no group answer either - priced')
    say('         off the nearest product, which is named on the row')
    say('         (--new-from asp or rate; off by default, both measured')
    say('         worse than leaving the sheet alone)')
    say('  kept = no record, no quote and no group - the GSCM price is')
    say('         unchanged, which on October beat every way of guessing')
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
    report(out, levels, hist, explain, campaigns, why, say,
           clearance=clearance)
    return out


# A gift with purchase puts no money in the words - `GWP music studio`
# has no dollar and no percentage - but it is the deepest offer there is:
# the unit goes out at nil. Without this a GWP day reads as a quiet day
# and its free units land on the clean side of the split, which is the
# one place they do the most harm.
GIFT = re.compile(r'\bgwp\b|gift\s*with\s*purchase|free\s*gift'
                  r'|bonus\s*gift', re.I)
OFFER_TAG = re.compile(r'\[([A-Z.\s]{2,10})\]')
OFFER_PCT = re.compile(r'(\d{1,2}(?:\.\d+)?)\s*%')
OFFER_AUD = re.compile(r'\$\s?([\d,]+(?:\.\d+)?)')


def offer_values(detail: str) -> dict:
    """{channel: [what the words say it is worth]} out of one Offer_Detail.

    The plan writes the offer in words, tagged by the channel it is for:

        [S.COM] Fold8 $150 Trade-in Bonus OR $150 Site
        [EPP] Fold8 Save 25%
        [S.COM] Save $300 [EPP] Save $200 on Z Fold8

    So one line can carry two offers for two channels, and the amounts are
    plain - dollars or a percentage. Reading them is the only way to size
    what a launch gave away *over* what the channel gives anyway, which the
    campaign flag cannot do: book-wide a campaign day is 1.1 points deeper
    than a quiet one, because the quiet days are under the standing rules
    at the same depth.

    Nothing is inferred about which of several amounts applied - `$150
    Trade-in Bonus OR $150 Site` is one or the other and the words say so.
    They are all returned and the caller decides; a tool that silently
    picked one would be making up the discount it is supposed to be
    reading.
    """
    out: dict = {}
    if not detail:
        return out
    marks = [(m.start(), m.group(1).strip()) for m in OFFER_TAG.finditer(detail)]
    spans = []
    if marks:
        for i, (at, tag) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(detail)
            spans.append((tag, detail[at:end]))
    else:
        spans = [('(untagged)', detail)]
    for tag, text in spans:
        got = out.setdefault(tag, [])
        for m in OFFER_PCT.finditer(text):
            got.append(('pct', float(m.group(1))))
        for m in OFFER_AUD.finditer(text):
            got.append(('aud', float(m.group(1).replace(',', ''))))
    return {k: v for k, v in out.items() if v}


def offer_worth(lines, rrp: float):
    """What the offers on these plan lines are worth, in money off one unit.

    Two rules, and the second one is the whole of what the first book-wide
    reading got wrong.

    **Within a channel offers stack.** A site credit and a PayPal rebate in
    the same fortnight are both money off the same purchase, so they add.

    **Across channels they do not.** A customer buys on S.COM *or* through
    EPP, never both, so adding `[S.COM] Save $300` to `[EPP] Save $200`
    charges one buyer for two offers they could not both take. Summed that
    way the book read a median gap of 47 points and a p90 of **167** -
    impossible as a discount, and the giveaway that the instrument and not
    the idea was at fault. The deepest channel is taken instead: an upper
    bound on what any one customer was offered, which is what a discount
    off list has to be measured against.

    Where one offer names two amounts as alternatives - `$150 Trade-in
    Bonus OR $150 Site` - the larger is taken, since which a customer took
    is not in the file. Returns `(worth, named, alternatives?)`.
    """
    byc: dict = {}
    alt = False
    for r in lines:
        for tag, got in offer_values(r.get('detail') or '').items():
            auds = [v for k, v in got if k == 'aud']
            pcts = [v for k, v in got if k == 'pct']
            here = 0.0
            if auds:
                here = max(auds)
                alt = alt or len(auds) > 1
            if pcts and rrp:
                here = max(here, max(pcts) / 100.0 * rrp)
                alt = alt or (len(pcts) > 1 or bool(auds))
            if here:
                byc[tag] = byc.get(tag, 0.0) + here
    if not byc:
        return 0.0, [], alt
    best = max(byc, key=lambda t: byc[t])
    return byc[best], [f'{t} {v:,.0f}' for t, v in
                       sorted(byc.items(), key=lambda kv: -kv[1])], alt


def live_lines(lines, a, b):
    """The plan lines whose window touches the days `a` to `b`."""
    return [r for r in lines
            if (not r.get('start') or r['start'] <= b)
            and (not r.get('end') or r['end'] >= a)]


def offer_months(plan, code, rrp, sold, months, say=print) -> None:
    """Do the offers in words account for the discount that was realised?

    This is the check that has to pass before the words can be used to
    price anything. For each month of the window: the money-off offers the
    plan had live for this product, added up and read against its list
    price, beside **what the product actually came off list that month**.

    If the two track, the offer text is a measurement and a launch\u2019s
    share of a discount can be added back to recover an ordinary price. If
    they do not, the text is a description and the add-back would be an
    invention.

    Added up, because offers stack: a site credit and a PayPal rebate in
    the same fortnight are both money off. A trade-in **bonus** is money
    off too - it is Samsung\u2019s, not the customer\u2019s - which is not the
    same thing as the traded phone\u2019s own value, and only the latter is
    outside a price.

    Where one offer names two amounts as alternatives - `$150 Trade-in
    Bonus OR $150 Site` - the larger is taken and the row says `or`, since
    which of them a customer took is not in the file.
    """
    want = {PM.code_norm(code)}
    lines = [r for r in plan.rows
             if PM.code_norm(r.get('code') or '') in want]
    if not lines:
        say('  the plan has no line for it')
        return
    say(f"\n    {'month':>7}{'offers':>8}{'in words':>11}{'realised':>10}"
        f"{'gap':>8}   the offers live that month")
    for m in months:
        a, b = month_days(m)[0], month_days(m)[-1]
        live = live_lines(lines, a, b)
        worth, names, alt = offer_worth(live, rrp)
        q, amt = sold.get(m, (0.0, 0.0))
        real = (1 - amt / (q * rrp)) * 100 if q > 0 and rrp else None
        words = (worth / rrp * 100) if rrp else None
        gap = (real - words) if (real is not None and words is not None) else None
        say(f'    {m:>7}{len(live):>8}'
            + (f'{words:>10.1f}%' if words is not None else f"{'-':>11}")
            + (f'{real:>9.1f}%' if real is not None else f"{'-':>10}")
            + (f'{gap:>7.1f}%' if gap is not None else f"{'-':>8}")
            + ('  ' if not alt else ' ~')
            + ', '.join(names[:4])[:48])
    say('    ~ an offer named two amounts as alternatives; the larger is '
        'taken')
    say('\n    gap = what the words do not account for: the channel\u2019s '
        'standing pricing,\n    which the plan does not write down. '
        '**Steady across the months and the\n    offer text is a '
        'measurement** - the launch\u2019s own share can be added back and '
        'an\n    ordinary price recovered. Erratic and it is a '
        'description, and the add-back\n    would be an invention.')


def gap_spread(plan, rows, months, say=print) -> None:
    """Is the gap a property of the product, or is it noise?

    `offer_months` shows, for one product, that what the plan writes down
    accounts for most of its discount and the rest - the gap - is steady.
    One product proves nothing. This runs the same subtraction over every
    product that sold, and asks how much each one\u2019s gap moves from month
    to month.

    If it barely moves, the gap is the product\u2019s own unwritten markdown
    and a month can be priced as **the offers it is actually running, plus
    that**. If it jumps about, the offer text explains one product and not
    the book, and the window average stays the better answer however
    polluted it is.
    """
    by: dict = {}
    for r in rows:
        if r['qty'] <= 0 or not r.get('rrp'):
            continue
        t = by.setdefault((PM.code_norm(r['code']), r.get('ym')),
                          [0.0, 0.0, 0.0])
        t[0] += r['qty']
        t[1] += r['amt']
        t[2] += r['qty'] * r['rrp']
    lines: dict = {}
    for r in plan.rows:
        lines.setdefault(PM.code_norm(r.get('code') or ''), []).append(r)

    moves, held, levels_, over = [], 0, [], 0
    span = 0
    for code in {c for c, _ in by}:
        mine = lines.get(code) or []
        if not mine:
            continue
        gaps = []
        for m in months:
            t = by.get((code, m))
            if not t or t[0] < MIN_UNITS or t[2] <= 0:
                continue
            rrp = t[2] / t[0]
            d1, d2 = month_days(m)[0], month_days(m)[-1]
            worth, _, _ = offer_worth(live_lines(mine, d1, d2), rrp)
            words = worth / rrp * 100
            span += 1
            if words > 100:
                over += 1
            gaps.append((1 - t[1] / t[2]) * 100 - words)
        if len(gaps) < 2:
            continue
        held += 1
        levels_ += gaps
        gaps.sort()
        moves.append(gaps[-1] - gaps[0])
    if not moves:
        say('\n  no product sold in two months of the window with a plan '
            'line, so the gap cannot be followed')
        return
    moves.sort()
    levels_.sort()

    def at(v, f):
        return v[min(len(v) - 1, int(f * len(v)))]

    say(f'\n  the gap followed over {held:,} product(s) that sold in two '
        f'months or more, {span:,} product-month(s)')
    if over:
        say(f'  {over:,} of those month(s) read an offer worth more than '
            'the list price, which\n  cannot be a discount - read them as '
            'the instrument, not the book')
    say('\n  what the gap IS, in points of list (the part the words do not '
        'account for):')
    say(f"    {'p25':>8}{'median':>9}{'p75':>8}{'p90':>8}")
    say(f'    {at(levels_, 0.25):>7.1f}%{at(levels_, 0.50):>8.1f}%'
        f'{at(levels_, 0.75):>7.1f}%{at(levels_, 0.90):>7.1f}%')
    say('\n  how far each product\u2019s gap MOVES between its best and '
        'worst month:')
    say(f"    {'p25':>8}{'median':>9}{'p75':>8}{'p90':>8}")
    say(f'    {at(moves, 0.25):>7.1f}%{at(moves, 0.50):>8.1f}%'
        f'{at(moves, 0.75):>7.1f}%{at(moves, 0.90):>7.1f}%')
    for n in (5, 10, 15):
        sh = sum(1 for v in moves if v <= n) / len(moves) * 100
        say(f'    {sh:>5.0f}% move {n:>2} points or less')
    say('\n  It is the MOVE that decides it, not the level: a gap that '
        'sits at 24 points\n  and stays there is a price, and one that '
        'swings 50 is noise. Tight, and a\n  month can be priced as the '
        'offers it is actually running plus the product\u2019s\n  own gap; '
        'loose, and the window average stays the better answer however\n'
        '  polluted it is')


def chan_key(row) -> str:
    """One comparable string for the channel a sales line went out on.

    `Portal Group` and `Distribution` run together with everything but
    letters and digits taken out, so `S.COM` on one side and `S.com /
    B2C` on the other meet as `SCOM` and `SCOMB2C`.
    """
    return re.sub(r'[^A-Z0-9]', '',
                  f"{row.get('portal') or ''} {row.get('dist') or ''}".upper())


def tag_key(tag: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', (tag or '').upper())


def is_gift(r) -> bool:
    """Does this plan line give the product away?

    Read off `Offer_Type` and `Offer_Detail` together: November's CE plan
    writes `Gift with Purchase` in the first and `GWP music studio` in
    the second, and neither carries an amount for `offer_values` to find.
    """
    return bool(GIFT.search(f"{r.get('type') or ''} "
                            f"{r.get('detail') or ''}"))


GIFT_MODEL = re.compile(r'\(([^)]*)\)')


def gift_models(detail: str) -> list:
    """The models a GWP line gives away, named inside its own text.

    `GWP-Music Studio(LS51H)` is a line on the **buying** product - an
    MRA soundbar, say - and LS51H is what the customer is given. The
    plan has no row for the gift; the only place it is named is in
    these brackets.

    So the days this line discounts are not the days of the product it
    sits on. The buyer's price does not move at all; the gift's does,
    all the way to nil. Attributing the line to its own row marks the
    wrong product.

    Only bracketed tokens that look like a model are taken - letters and
    digits together, four characters or more - so `(AUD)` and `(2 pack)`
    are left alone.
    """
    out = []
    for inside in GIFT_MODEL.findall(detail or ''):
        for bit in re.split(r'[,;/+&]| or ', inside):
            t = re.sub(r'[^A-Za-z0-9]', '', bit).upper()
            if len(t) >= 4 and any(c.isdigit() for c in t) \
                    and any(c.isalpha() for c in t):
                out.append(t)
    return out


GIFT_WORDS = re.compile(r'\bgwp\b|gift\s*with\s*purchase|free\s*gift'
                        r'|bonus\s*gift|\bwith\b|\bfor\b|\bon\b'
                        r'|\bpurchase\b|\bbuy\b|\bfree\b', re.I)


def gift_phrase(detail: str) -> str:
    """What the gift is called, once the GWP wording is taken off.

    **The full model is not always written down.** `GWP-Music
    Studio(LS51H)` names one; `GWP Music Studio` names none, and then
    the only handle on the gift is what it is called. So the words are
    kept as a second way in, matched against the plan's own product
    descriptions.

    Everything inside brackets is removed first - that is the code's
    route, tried before this one - and so are the words every GWP line
    shares, which carry no information about which product is meant.
    """
    txt = GIFT_MODEL.sub(' ', detail or '')
    txt = GIFT_WORDS.sub(' ', txt)
    return re.sub(r'[^A-Za-z0-9]', '', txt).upper()


def offer_live(lines, chans=(), codes=(), say=None, named=None):
    """`code -> (days for every channel, {channel: days})`.

    Only lines whose `Offer_Detail` carries an amount count. A line that
    names a campaign and no money is not an offer for this purpose: it
    says a name was in force, and a name is what four attempts at this
    have already shown cannot size a discount.

    **The channel the offer is tagged for decides whose day it spoils.**
    `[EPP] Save $750` is money to an EPP buyer and nothing at all to
    somebody on the consumer store, so counting it against the store's
    day throws away a day that really was ordinary. With the tags read,
    an EPP offer marks EPP's days and leaves the rest clean.

    `chans` is every channel string the sales actually carry. A tag that
    matches none of them is one this reader does not understand - a
    mis-spelling, a channel named differently on the two sides, an
    untagged line - and it marks the day for **everyone**, which is what
    the first version of this did for every tag. Not understanding a tag
    must never quietly turn a promoted day into a clean one.
    """
    chans = {c for c in chans if c}
    sold = {PM.code_norm(c) for c in codes if c}

    def known(tag):
        k = tag_key(tag)
        return k if k and any(k in c for c in chans) else None

    def span(r):
        a, b = r.get('start'), r.get('end')
        if not a or not b or b < a:
            return None
        days, d = set(), a
        while d <= b:
            days.add(d)
            d += timedelta(days=1)
        return days

    out: dict = {}

    def mark(code, days, tag=None):
        every, by = out.setdefault(code, (set(), {}))
        k = known(tag) if tag is not None else None
        if k is None:
            every |= days
        else:
            by.setdefault(k, set()).update(days)

    gifts = [0, 0, 0]
    for code, mine in lines.items():
        out.setdefault(code, (set(), {}))
        for r in mine:
            days = span(r)
            if days is None:
                continue
            got = offer_values(r.get('detail') or '')
            for tag in got:
                mark(code, days, tag)
            if not is_gift(r):
                continue
            # The gift goes to the models named in the brackets, not to
            # the row the line sits on. A gift is not tied to how the
            # buyer paid, so it marks every channel.
            want = gift_models(r.get('detail') or '')
            hit = [c for c in sold
                   if any(c.startswith(t) or t in c for t in want)]
            gifts[0] += 1
            if hit:
                gifts[1] += 1
            elif named:
                # No model in the brackets, or one nothing sold under.
                # Fall back to what the gift is called, against the
                # plan's own product descriptions.
                ph = gift_phrase(r.get('detail') or '')
                if len(ph) >= 6:
                    hit = [c for d, cs in named.items() if ph in d
                           for c in cs if c in sold]
                    if hit:
                        gifts[2] += 1
            for c in hit:
                mark(c, days)
    if say and gifts[0]:
        lost = gifts[0] - gifts[1] - gifts[2]
        say(f'  {gifts[0]:,} gift-with-purchase line(s) in the plan: '
            f'{gifts[1]:,} resolved by the model in the brackets, '
            f'{gifts[2]:,} by what the gift is called')
        if lost:
            say(f'  {lost:,} resolved to nothing that sold. Their free '
                'units are still read off the export - a nil-revenue\n'
                '  line is never a quiet day - so only the priced '
                'month\u2019s forecast misses them')
    return out


def offer_on(live, code, day, chan: str) -> bool:
    """Was an offer this line's buyer could have taken live that day?"""
    got = live.get(code)
    if not got:
        return False
    every, by = got
    if day in every:
        return True
    for k, days in by.items():
        if k in chan and day in days:
            return True
    return False


def plan_names(plan) -> dict:
    """`normalised product description -> {codes}` out of the plan.

    The second route to a gift, for the lines that name no model. The
    plan describes every row it prices, so `Music Studio` can be found
    there even where the brackets are empty.
    """
    out: dict = {}
    for r in getattr(plan, 'rows', ()) or ():
        d = re.sub(r'[^A-Za-z0-9]', '', str(r.get('desc') or '')).upper()
        c = PM.code_norm(r.get('code') or '')
        if len(d) >= 6 and c:
            out.setdefault(d, set()).add(c)
    return out


def offer_tags(plan, chans, say=print, top: int = 12) -> None:
    """Which `[TAG]`s the plan writes, and which of them a sales line answers to.

    A tag that resolves marks only its own channel's days. One that does
    not marks everybody's, so it is worth seeing: a tag high on this list
    and unresolved is a channel named differently on the two sides, and
    naming it here is cheaper than finding it in a price six weeks later.
    """
    seen: dict = {}
    for r in plan.rows:
        for tag in offer_values(r.get('detail') or ''):
            seen[tag] = seen.get(tag, 0) + 1
    if not seen:
        say('  the plan writes no tagged offer')
        return
    say(f"\n  {'offer tag':<16}{'lines':>8}  matched against the sales")
    for tag, n in sorted(seen.items(), key=lambda kv: -kv[1])[:top]:
        k = tag_key(tag)
        hit = sorted(c for c in chans if k and k in c)
        say(f'  {tag[:15]:<16}{n:>8}  '
            + (', '.join(hit)[:46] if hit
               else 'no channel answers to it - marks every channel'))
    if len(seen) > top:
        say(f'  ... and {len(seen) - top} more')


def clean_days(plan, rows, months, say=print) -> None:
    """Is there a day left over, once the days carrying an offer are taken out?

    The add-back failed because the plan says what was **offered** and not
    what was **taken**, and the take-up rate is in no file here. The way
    round it needs no take-up at all: instead of adding an offer back to a
    polluted average, drop the days the offer was live and average what is
    left. Those days are the ordinary price, observed rather than
    reconstructed, and nothing has to be sized for them.

    It only works if those days exist. The promotion file is cumulative
    from 2025 and the standing EPP rules sit under everything, so a product
    can easily carry a live offer on every day of the window - and then
    there is nothing left to average and this road is shut too. That is
    what this measures, before anything is built on it.

    Three numbers matter. **How many products** keep enough units on clean
    days to be read at all; **how much of the book** those units are; and
    **how far apart** the clean price and the window price are, because a
    filter that changes nothing is not worth having however good its
    coverage.
    """
    lines: dict = {}
    for r in plan.rows:
        lines.setdefault(PM.code_norm(r.get('code') or ''), []).append(r)
    chans = {chan_key(r) for r in rows if r['qty'] > 0}
    offer_tags(plan, chans, say=say)
    live = offer_live(lines, chans, {r['code'] for r in rows}, say=say,
                      named=plan_names(plan))

    span = set()
    for m in months:
        span.update(month_days(m))
    tot: dict = {}
    undated = 0
    for r in rows:
        if r['qty'] <= 0:
            continue
        if not r.get('day'):
            undated += r['qty']
            continue
        k = PM.code_norm(r['code'])
        t = tot.setdefault(k, [0.0, 0.0, 0.0, 0.0, 0.0])
        t[0] += r['qty']
        t[1] += r['amt']
        if r['amt'] <= 0 or offer_on(live, k, r['day'], chan_key(r)):
            t[4] += r['qty']        # sold under an offer, or given away
        else:
            t[2] += r['qty']
            t[3] += r['amt']

    if not tot:
        say('\n  no dated sales in the window, so clean days cannot be '
            'counted')
        return
    units = sum(t[0] for t in tot.values())
    free = sum(t[2] for t in tot.values())

    # Three groups, because they want three different things and averaging
    # them together is what made the first reading say nothing. A product
    # the window never put an offer on has a clean price identical to its
    # window price by construction - it is a nought that is right, and a
    # few hundred of them sitting in the middle of the distribution drag
    # any median to nought whatever the filter is doing elsewhere.
    noop = [k for k, t in tot.items() if t[4] <= 0]
    work = [k for k, t in tot.items() if t[4] > 0 and t[2] >= MIN_UNITS]
    short = [k for k, t in tot.items() if t[4] > 0 and t[2] < MIN_UNITS]

    say(f'\n  {len(tot):,} product(s), {units:,.0f} dated unit(s) over '
        f'{len(span):,} day(s) of window')
    if undated:
        say(f'  {undated:,.0f} unit(s) carry no date and are left out')
    say(f'  {free / units * 100:.1f}% of those units fell on a day with no '
        'offer live')

    def share(ks):
        return sum(tot[k][0] for k in ks) / units * 100

    say('')
    say(f"    {'':<34}{'products':>10}{'% of book':>11}")
    say(f"    {'A  never had an offer':<34}{len(noop):>10,}"
        f'{share(noop):>10.1f}%')
    say(f"    {'B  had one, and clean days left':<34}{len(work):>10,}"
        f'{share(work):>10.1f}%')
    say(f"    {'C  had one, too few clean days':<34}{len(short):>10,}"
        f'{share(short):>10.1f}%')
    say('\n  A needs no filter - its window price is already clean. C '
        'falls through to')
    say('  the plain ASP whatever happens. **B is the only group this is '
        'for.**')

    if not work:
        say('\n  B is empty: every product with an offer in the window '
            'kept too few\n  clean units to read one. The filter has '
            'nothing to work on')
        return

    moves, deep = [], []
    for k in work:
        t = tot[k]
        whole, bare = t[1] / t[0], t[3] / t[2]
        if whole > 0:
            moves.append((bare / whole - 1) * 100)
            deep.append(t[4] / t[0] * 100)
    moves.sort()
    deep.sort()

    def at(v, f):
        return v[min(len(v) - 1, int(f * len(v)))]

    say(f'\n  B: {len(work):,} product(s). How much of each one\u2019s '
        'month sold under an offer:')
    say(f"    {'p25':>8}{'median':>9}{'p75':>8}{'p90':>8}")
    say(f'    {at(deep, 0.25):>7.0f}%{at(deep, 0.50):>8.0f}%'
        f'{at(deep, 0.75):>7.0f}%{at(deep, 0.90):>7.0f}%')
    say('\n  B: the clean-day price against the whole-window price, in '
        'percent:')
    say(f"    {'p25':>8}{'median':>9}{'p75':>8}{'p90':>8}")
    say(f'    {at(moves, 0.25):>+7.1f}%{at(moves, 0.50):>+8.1f}%'
        f'{at(moves, 0.75):>+7.1f}%{at(moves, 0.90):>+7.1f}%')
    up = sum(1 for v in moves if v > 0.05) / len(moves) * 100
    flat = sum(1 for v in moves if abs(v) <= 0.05) / len(moves) * 100
    say(f'  {up:.0f}% dearer on clean days, {flat:.0f}% unchanged, '
        f'{100 - up - flat:.0f}% cheaper')
    say('\n  Dearer is the direction the filter is for: the window '
        'average is dragged')
    say('  down by the offers in it, and taking those days out should '
        'put it back.')
    say('  Cheaper means the offer days were not the cheap ones, and on '
        'those products')
    say('  the filter would make the answer worse, not better')


def offer_report(plan, codes=(), say=print, top: int = 40) -> None:
    """What the plan’s `Offer_Detail` column says, and what it is worth.

    The plan carries the offer in words beside the campaign that ran it,
    and the re-price has never read it: the model asks the plan only *which
    campaign* covered a day, then measures the depth from the sales. That
    works while a campaign’s name is the whole of what it did, and fails on
    a launch, where what the product sold at is the launch and there is no
    ordinary price behind it to find.

    The offer in words is the one place the two are written apart - a
    pre-order bonus named as such, beside the tier discount that would have
    applied anyway. This lists the vocabulary so that what can be read out
    of it is a reading and not a hope.

    The quoted depth beside each is the plan’s own: its store price against
    its list price, on the lines that carry both.
    """
    rows = plan.rows or []
    if codes:
        want, mine = set(), []
        for c in codes:
            got, _ = plan.candidates(PM.code_norm(c))
            for r in got:
                if id(r) not in want:
                    want.add(id(r))
                    mine.append(r)
        rows = mine
        say(f'\nthe plan\u2019s offers for '
            + ', '.join(str(c) for c in codes) + f': {len(rows):,} line(s)')
    else:
        say(f'\nthe plan\u2019s Offer_Detail column, over '
            f'{len(rows):,} line(s)')
    if not rows:
        say('  no plan line to read')
        return

    def depth(r):
        px = r.get('prices') or {}
        rrp, com = px.get('RRP'), px.get('S.COM_Price')
        return (1 - com / rrp) if rrp and com and rrp > 0 else None

    if codes:
        say(f"    {'from':>10}{'to':>12}  {'quoted':>7}  "
            f"{'campaign':<22}{'what the words say':<26}offer")
        for r in sorted(rows, key=lambda r: (r['start'] or date.min)):
            d = depth(r)
            camp = ' / '.join(x for x in (r.get('camp') or []) if x) or '-'
            vals = offer_values(r.get('detail') or '')
            worth = '; '.join(
                f'{t}: ' + ' or '.join(f'{v:,.0f}%' if k == 'pct'
                                       else f'${v:,.0f}' for k, v in got)
                for t, got in vals.items()) or '-'
            say(f"    {str(r['start'] or '-'):>10}{str(r['end'] or '-'):>12}"
                + (f'{d * 100:>8.1f}%' if d is not None else f"{'-':>9}")
                + f"  {camp[:21]:<22}{worth[:25]:<26}"
                + (r.get('detail') or '-')[:44])
        return

    by: dict = {}
    for r in rows:
        t = by.setdefault((r.get('detail') or '(blank)').strip()[:46],
                          [0, set(), [], set()])
        t[0] += 1
        t[1].add(r.get('code') or '')
        d = depth(r)
        if d is not None:
            t[2].append(d)
        for x in (r.get('camp') or []):
            if x:
                t[3].add(x)
    say(f"  {'offer':<48}{'lines':>7}{'SKUs':>7}{'quoted':>9}   a campaign "
        'it runs under')
    for name, t in sorted(by.items(), key=lambda kv: -kv[1][0])[:top]:
        d = (sum(t[2]) / len(t[2]) * 100) if t[2] else None
        camp = sorted(t[3])
        say(f'  {name:<48}{t[0]:>7,}{len(t[1]):>7,}'
            + (f'{d:>8.1f}%' if d is not None else f"{'-':>9}")
            + f'   {(camp[0] if camp else "-")[:28]}'
            + (f' +{len(camp) - 1}' if len(camp) > 1 else ''))
    if len(by) > top:
        say(f'  ... and {len(by) - top:,} more')


def rung_report(out, levels, say=print, top: int = 14) -> None:
    """Which rung of the ladder actually carried the month.

    The rrp model walks a day at a time and the rungs are tried in order,
    so a change to a low rung can be perfectly correct and move nothing,
    because a rung above it answers first on nearly every day. That is not
    visible in the prices and it is not visible in the spread - a model
    that is 0.2 points different from another looks like a model that was
    barely changed, when it may be one whose change never ran.

    Days are counted twice: once flat, and once weighted by the units the
    product sold, because a rung carrying 3% of the days of a product that
    shifts half the division is not a 3% rung.
    """
    units = {PM.code_norm(c): max(v.get('qty') or 0.0, 0.0)
             for c, v in out.items()}
    flat: dict = collections.defaultdict(float)
    heavy: dict = collections.defaultdict(float)
    days = wsum = 0.0
    for p in BREAKDOWN:
        u = units.get(p['code'], 0.0)
        for c, f, n, *_ in p.get('rows', ()):
            flat[f] += n
            heavy[f] += n * u
            days += n
            wsum += n * u
    if not days:
        say('\n  no day-by-day record to break down')
        return
    say(f'\n  which rung priced the day, over {days:,.0f} product-day(s):')
    say(f"    {'rung':<42}{'days':>9}{'by units':>10}")
    for f, n in sorted(flat.items(), key=lambda kv: -kv[1])[:top]:
        say(f'    {f[:41]:<42}{n / days * 100:>8.1f}%'
            + (f'{heavy[f] / wsum * 100:>9.1f}%' if wsum else f"{'-':>10}"))
    if len(flat) > top:
        say(f'    ... and {len(flat) - top} more')
    say('    a rung with few days is one the rungs above it answer for '
        'first, and')
    say('    changing it moves nothing however right the change is')


def report(out, levels, hist, explain, campaigns, why, say,
           clearance: bool = True) -> None:
    """The three asked-for readings, whichever model was run.

    They used to hang off the `simple` branch, so `--why`, `--explain` and
    `--campaigns` quietly did nothing on the model that is now the default -
    the one question they exist to answer was the one they would not take.
    """
    if explain:
        rung_report(out, levels, say)
        explain_terms(out, levels, say)
    if campaigns:
        campaign_report(hist, levels, say, level=campaigns)
    if why:
        why_one(why, hist, out, levels, say, clearance=clearance)


def write_csv(path, out) -> None:
    """The per-material rows: the forecast, and what the month did."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        # The three `Actual` columns are the month **to date** - the order
        # export stops where it stops - so a material that is still selling
        # is a part month read against a whole month's forecast. The amount
        # is the export's own money and the price is that over the units,
        # so a pivot can weight by either without re-deriving one from the
        # other and rounding twice.
        #
        # `Actual - Re-priced` is the miss, and `Impact` is that miss times
        # the units it was made on - the figure a pivot actually sums,
        # because a 60 miss on four hundred units and on four is not the
        # same money.
        #
        # All of them are blank rather than nought where nothing sold: a
        # material the month never sold has no price to miss by, and nought
        # in that column is the single thing that wrecks a deviation.
        w.writerow(['Material', 'Biz', 'Div 1', 'Div 2', 'Div 3',
                    'Planned qty', 'GSCM price', 'Re-priced', 'Change %',
                    'RRP', 'Promo days', 'From', 'Nearest SKU',
                    'Actual qty', 'Actual amount', 'Actual price',
                    'Actual - Re-priced', 'Diff %', 'Actual - GSCM',
                    'Impact', 'Why'])
        for code, v in sorted(out.items(),
                              key=lambda kv: -abs((kv[1]['price']
                                                   - kv[1]['gscm'])
                                                  * kv[1]['qty'])):
            ch = (v['price'] / v['gscm'] - 1) * 100 if v['gscm'] else None
            asp = v.get('asp')
            dr = (asp - v['price']) if asp else None
            drp = (asp / v['price'] - 1) * 100 if asp and v['price'] else None
            dg = (asp - v['gscm']) if asp and v['gscm'] else None
            w.writerow([code, *(v['chain'] + [''] * 4)[:4], v['qty'],
                        f"{v['gscm']:.2f}", f"{v['price']:.2f}",
                        '' if ch is None else f'{ch:+.1f}',
                        '' if v['rrp'] is None else f"{v['rrp']:.2f}",
                        f"{v['promo_days'] * 100:.0f}%", v['how'],
                        v.get('near', ''),
                        '' if not v.get('sold') else f"{v['sold']:.0f}",
                        '' if v.get('amt') is None else f"{v['amt']:.0f}",
                        '' if asp is None else f'{asp:.2f}',
                        '' if dr is None else f'{dr:+.2f}',
                        '' if drp is None else f'{drp:+.1f}',
                        '' if dg is None else f'{dg:+.2f}',
                        '' if dr is None else f"{dr * v['sold']:+.0f}",
                        v['why']])


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
    ap.add_argument('--model', default='rrp',
                    choices=('rrp', 'quote', 'campaign', 'simple'),
                    help='rrp (default): the list price the promotion table '
                         'quotes, less what the same promotion has been '
                         'running at - this product\u2019s own record of it '
                         'first, then its group\u2019s. quote: the same, but '
                         'a day whose campaign nobody has a record of takes '
                         'the plan\u2019s own quote for it ahead of the '
                         'product\u2019s ordinary-month ASP - which is the '
                         'Black Friday case. simple: each product\u2019s own '
                         'six-month ASP, nudged by three group ratios. '
                         'campaign is the old name for rrp')
    ap.add_argument('--scope', default='div1', choices=SCOPES,
                    help='how far a promotion\u2019s discount may be '
                         'borrowed from when the product has never run it '
                         '(default div1: its model family, then Div 3, then '
                         'Div 1, never the whole book; all lets the book '
                         'answer, range holds it to the family). This flag '
                         'said div1 and did range - it does what it says '
                         'now')
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
    ap.add_argument('--min-months', type=int, default=MIN_MONTHS,
                    metavar='N',
                    help='how many months of its own a product needs before '
                         'its ASP is read one month one vote rather than '
                         'pooled over units (default 3)')
    ap.add_argument('--min-units', type=int, default=MIN_UNITS,
                    metavar='N',
                    help=f'units a product needs before its own discount is '
                         f'read rather than its range\u2019s (default '
                         f'{MIN_UNITS})')
    ap.add_argument('--floor', type=float, default=None, metavar='PCT',
                    help='leave out every line more than PCT%% below what '
                         'the product fetches on its voucher-free lines, '
                         'whichever voucher did it or none. One number, '
                         'no list to keep, and a product with nothing odd '
                         'in it loses nothing')
    ap.add_argument('--learn', type=float, nargs='?', const=50.0,
                    default=None, metavar='PCT',
                    help='take the voucher stems the floor caught and '
                         'drop ALL of their lines, not only the deep '
                         'ones - a stem is condemned when PCT%% of its '
                         'lines (default 50) fall below the floor. The '
                         'effective depth then differs by mechanic '
                         'without anybody setting one per mechanic')
    ap.add_argument('--trim-in', dest='trim_in', nargs='+', default=(),
                    metavar='NAME',
                    help='apply --floor and --ceil to these groups only, '
                         'e.g. --trim-in MX. Matched at any level the '
                         'product has a name at. The trim is not equally '
                         'good everywhere: MX gained on both months '
                         'measured, DA and VD each gained on one and lost '
                         'on the other')
    ap.add_argument('--ceil', type=float, default=None, metavar='PCT',
                    help='the other end of --floor: leave out every line '
                         'more than PCT%% ABOVE what the product fetches '
                         'voucher-free. A floor only ever makes the '
                         'forecast dearer; a ceiling pushes back')
    ap.add_argument('--vouchers', action='store_true',
                    help='which voucher codes move a price and by how '
                         'much, against the list price and against what '
                         'the same products fetched voucher-free. Group '
                         'aggregates only, so it is safe to paste')
    ap.add_argument('--drop-voucher', dest='no_vouch', nargs='+',
                    default=(), metavar='NAME',
                    help='leave lines carrying these voucher codes out of '
                         'every ASP and discount. Matched as a '
                         'case-insensitive substring, so a family can be '
                         'named by its stem. Read --vouchers first')
    ap.add_argument('--drop-deals', dest='no_deals', action='store_true',
                    help='leave every line the export flags as a voucher '
                         'or a trade-in out of every ASP and every '
                         'discount. The narrow instrument where --band is '
                         'the blunt one: it names the mechanic instead of '
                         'guessing it from the price')
    ap.add_argument('--band', nargs=2, type=float, default=None,
                    metavar=('LO', 'HI'),
                    help='leave a line out of every ASP and every discount '
                         'unless its realised price is between LO%% and '
                         'HI%% of the list price, e.g. --band 30 70. '
                         'Vouchers, staff orders and bundle allocations '
                         'sit far below the band and drag an ASP with them')
    ap.add_argument('--grace', type=int, default=None, metavar='N',
                    help='leave the launch out by date, with its written '
                         'end pushed out N days - the plan stops writing '
                         'the offer before the price moves. Off by '
                         'default; N is fitted, so measure several')
    ap.add_argument('--clean-quiet', dest='clean_quiet',
                    action='store_true',
                    help='a quiet day is one with no live offer in the '
                         'promotion plan, not one the plan wrote no '
                         'campaign name on. See --clean for the '
                         'measurement behind it')
    ap.add_argument('--clean', action='store_true',
                    help='count the window days that carry no live '
                         'offer, and what the price on them is worth '
                         'against the whole-window price. Group '
                         'aggregates only, so it is safe to paste')
    ap.add_argument('--offers', nargs='*', default=None, metavar='CODE',
                    help='what the plan\u2019s Offer_Detail column says, with '
                         'the depth the plan quotes beside it. With no code, '
                         'the vocabulary over the whole plan; with codes, '
                         'those products\u2019 own lines in date order. Reads '
                         'the plan only - no history, no pricing')
    ap.add_argument('--drop-launch-months', dest='drop_launch',
                    action='store_true',
                    help='where a month in the window carried a launch or a '
                         'pre-order for a product, drop that whole month of '
                         'it - the quiet days as well, because a launch '
                         'price applies on the days the plan does not name '
                         'it. Off by default: measure it with price_spread '
                         'before turning it on')
    ap.add_argument('--keep', nargs='+', default=(), metavar='NAME',
                    help='leave these groups at the GSCM price, by any of '
                         'Biz, Div 1, Div 2, Div 3 or Range - e.g. --keep MX. '
                         'For a group the sheet already prices better than '
                         'anything here can: measure with price_spread '
                         '--compare before naming one')
    ap.add_argument('--new-from', default='sheet',
                    choices=('sheet', 'asp', 'rate'),
                    help='what prices a product with no record of its own '
                         'and no quote in the plan. sheet (default): the '
                         'GSCM price it already has, left alone - measured '
                         'best on October by some way. asp: the nearest '
                         'product\u2019s ASP. rate: that ASP at its own rate '
                         'off the sheet. The last two were 293 and 543 '
                         'against the sheet\u2019s 244')
    ap.add_argument('--no-actual', action='store_true',
                    help='leave the realised price out of the CSV. It is '
                         'another read of the order export, which is the '
                         'slow part of a run that only wants the forecast')
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
    ap.add_argument('--asp-first', dest='promo_first',
                    action='store_false',
                    help='take the product\u2019s blended ASP and nudge it '
                         'towards the month, instead of answering the '
                         'promoted and the quiet days each out of the part '
                         'of its past that matches')
    ap.add_argument('--quiet-list', action='store_true',
                    help='price the unpromoted part of a month off the '
                         'month\u2019s list price at its group\u2019s '
                         'ordinary markdown, rather than off what the '
                         'product itself fetched on quiet days')
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
    set_min_months(args.min_months)
    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        raise SystemExit(f'no such folder: {folder.resolve()}')

    import plan_price as PP
    gf, ym = PP.pick_month(folder, 'gscm', args.month)
    if ym is None:
        raise SystemExit(f'no gscm_* file in {folder.resolve()}')
    if gf is None:
        raise SystemExit(f'no gscm_* sheet in {folder.resolve()} prices that '
                         'month')
    full = (2000 + ym // 100) * 100 + ym % 100

    if args.vouchers:
        say = print
        months = months_back(full, args.back)
        say('reading what sold, and under which voucher:')
        voucher_report(DTC.read(folder, set(months), say=say), say=say)
        return 0

    if args.clean:
        say = print
        say('reading the promotion plan:')
        plan, _ = PM.load_plans(folder, args.plan, say=say)
        if not getattr(plan, 'rows', None):
            raise SystemExit('no promotion plan to read')
        months = months_back(full, args.back)
        say('\nreading what sold, and when:')
        clean_days(plan, DTC.read(folder, set(months), say=say),
                   months, say=say)
        return 0

    if args.offers is not None:
        say = print
        say('reading the promotion plan:')
        plan, _ = PM.load_plans(folder, args.plan, say=say)
        if not getattr(plan, 'rows', None):
            raise SystemExit('no promotion plan to read')
        offer_report(plan, args.offers, say=say)
        if not args.offers:
            months = months_back(full, args.back)
            say('\nreading what those products sold at:')
            gap_spread(plan, DTC.read(folder, set(months), say=say),
                       months, say=say)
        # With a code, the check that decides whether the words can price
        # anything: the offers added up against what the product actually
        # came off list, month by month.
        if args.offers:
            months = months_back(full, args.back)
            rows = DTC.read(folder, set(months), say=lambda *a: None)
            for code in args.offers:
                k = PM.code_norm(code)
                sold = {}
                for r in rows:
                    if PM.code_norm(r['code']) != k or r['qty'] <= 0:
                        continue
                    t = sold.setdefault(r.get('ym'), [0.0, 0.0])
                    t[0] += r['qty']
                    t[1] += r['amt']
                rrp = rrp_of(plan, code)
                say(f'\n  {code}: list {rrp:,.0f}' if rrp
                    else f'\n  {code}: no list price in the plan')
                offer_months(plan, code, rrp, sold, months, say=say)
        return 0

    out = reprice(folder, full, args.back, args.plan, explain=args.explain,
                  pooled=args.pooled, campaigns=args.campaigns,
                  clearance=args.clearance, why=args.why,
                  quiet_list=args.quiet_list,
                  promo_first=args.promo_first,
                  scope=args.scope, decay=args.decay, source=args.source,
                  new_cap=args.new_cap / 100.0, no_mix=args.no_mix,
                  flat_days=args.flat_days, by_units=args.by_units,
                  model=args.model, actual=not args.no_actual,
                  new_from=args.new_from, keep=args.keep,
                  drop_launch=args.drop_launch,
                  clean_quiet=args.clean_quiet, grace=args.grace,
                  band=band_of(args.band), no_deals=args.no_deals,
                  no_vouch=args.no_vouch,
                  floor=(args.floor / 100.0 if args.floor else None),
                  ceil=(args.ceil / 100.0 if args.ceil else None),
                  trim_in=args.trim_in,
                  learn=(args.learn / 100.0 if args.learn else None))

    path = Path(args.out) if args.out else ROOT / 'docs' / f'reprice_{ym}.csv'
    write_csv(path, out)
    print(f'\n-> {path}  ({len(out):,} material(s))')
    return 0


if __name__ == '__main__':
    sys.exit(main())

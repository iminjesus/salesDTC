#!/usr/bin/env python3
"""The month a unit's revenue fell in, read off SAP rather than argued for.

`tools/orders.py` reads the store's own export and has to decide, from a status,
which month a unit belongs to. SAP's sales-order export does not need deciding:
`Created On` is when the order arrived and `Goods Issue Date` is when it left,
and the month it left in is the month it earned in.

So the same three buckets the profit page runs on come out measured:

    booked       left in this month, ordered in this month
    carried in   left in this month, ordered before it
    carried out  ordered in this month, leaves after it

and the key is better as well. The store export knows a portal group, which is
why `orders.py` has to spread an order across every customer it might have been.
SAP knows the **payer** - the same `Sold-to Party` the profit file is keyed on -
so a line lands on one customer at full depth with nothing spread anywhere.

Only the lines carrying a store-stamped reference count. `AU260930-46262020` is
the store's own order number; Amazon, Myer, MyDeal and eBay carry something else,
and the shape of the reference is what separates them with nothing to configure.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from rawdata import (find, key_norm, parse_number,             # noqa: E402
                     pick_amount, read_any)

S_REF = ('Customer Reference (Header)', 'Customer Reference', 'Purchase Order')
S_PAYER = ('Sold-to Party', 'Sold-To Party', 'Sold to Party', 'Payer',
           'Customer')
S_SKU = ('Material', 'Material Number', 'Product Code', 'SKU')
S_QTY = ('Confirmed Quantity (Item)', 'Order Quantity (Item)', 'Quantity')
S_AMT = ('Net Value (Item)', 'AUD Revenue excl. GST', 'USD Revenue excl. GST',
         'Net Value')
S_GI = ('Goods Issue Date', 'Actual GI Date', 'Despatch Date')
S_MADE = ('Created On', 'Creation Date', 'Entered On')
S_DSTAT = ('Overall Delivery Status Item Description',
           'Overall Delivery Status (All Items)')
S_REJECT = ('Reason for Rejection', 'Rejection Reason')

STAMPED = re.compile(r'^([A-Z]{2})(\d{6})-(\d+)$')
DELIVERED = ('COMPLETED', 'DELIVERED', 'FULLY DELIVERED')

BOOKED, CARRIED_IN, CARRIED_OUT = 0, 1, 2       # which pair of slots


def to_date(v):
    for f in ('%d/%m/%Y', '%Y-%m-%d', '%d-%b-%Y', '%m/%d/%Y', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(str(v or '').strip(), f).date()
        except ValueError:
            pass
    return None


def month_of_date(d):
    return d.year * 100 + d.month if d else None


class Months:
    """Per key: booked, carried in and carried out, as units and amount."""

    def __init__(self):
        self.by_key: dict[tuple, list] = {}
        self.lines = self.counted = self.outside = self.rejected = 0
        self.no_customer = self.no_product = 0
        self.scheduled = 0.0        # units counted off a date that has not come
        self.measured = 0.0
        self.files: list[str] = []
        self.amount_col = None
        # Units per promotion band, on the same key. Filled only when the
        # caller passes a `band_of`, and only for what this month earned -
        # carried out is next month's and has earned nothing here to split.
        self.by_band: dict[tuple, list[float]] = {}
        # token -> column. The tokens are (band, campaign) pairs and which ones
        # exist is not known until the file has been read, so the vector grows
        # as they turn up rather than being sized from a list written here.
        self.band_at: dict = {}

    def add(self, key, which, qty, amt):
        v = self.by_key.get(key)
        if v is None:
            v = self.by_key[key] = [0.0] * 6
        v[which * 2] += qty
        v[which * 2 + 1] += amt

    def add_band(self, key, band, qty):
        i = self.band_at.get(band)
        if i is None:
            i = self.band_at[band] = len(self.band_at)
        v = self.by_band.setdefault(key, [])
        if len(v) <= i:
            v.extend([0.0] * (i + 1 - len(v)))
        v[i] += qty

    def band_rows(self):
        """(tokens, {key: vector}) with every vector the same width."""
        tokens = sorted(self.band_at, key=self.band_at.get)
        n = len(tokens)
        for v in self.by_band.values():
            if len(v) < n:
                v.extend([0.0] * (n - len(v)))
        return tokens, self.by_band


    def totals(self):
        out = [0.0] * 6
        for v in self.by_key.values():
            for i in range(6):
                out[i] += v[i]
        return out


def load(paths, *, month: int, cust_levels, prod_levels, customers: dict,
         products: dict, skip_sku: tuple = (), currency: str | None = None,
         band_of=None, say=print) -> Months | None:
    """Read every SAP export and total the month onto the profit file's key.

    `month` is the month being drawn, as YYYYMM. A line counts when it left in
    that month, or when it was ordered in that month and leaves after it.
    """
    out = Months()
    for path in paths:
        rows, info = read_any(path)
        if not rows:
            continue
        head = [h.strip() for h in rows[0]]
        body = rows[1:]
        amt_i, amt_all = pick_amount(head, S_AMT, currency)
        col = {k: find(head, *v) for k, v in
               {'ref': S_REF, 'payer': S_PAYER, 'sku': S_SKU, 'qty': S_QTY,
                'gi': S_GI, 'made': S_MADE, 'dstat': S_DSTAT,
                'reject': S_REJECT}.items()}
        col['amt'] = amt_i
        say(f'  {path.name}: {info["format"]}, {len(body):,} rows')
        missing = [k for k in ('ref', 'payer', 'sku', 'qty', 'gi', 'made')
                   if col[k] is None]
        if missing:
            say(f'    no {", ".join(missing)} - skipped')
            continue
        for what in ('ref', 'payer', 'sku', 'qty', 'gi', 'made', 'amt'):
            i = col[what]
            say(f'    {what:<6} ' + (repr(head[i]) if i is not None
                                     else '-- not found --'))
        if amt_i is not None and len(amt_all) > 1:
            say('    (also here: '
                + ', '.join(a for a in amt_all if a != head[amt_i])
                + '; --currency picks)')
        out.files.append(path.name)
        out.amount_col = head[amt_i] if amt_i is not None else out.amount_col

        def cell(r, i):
            return (r[i].strip() if i is not None and i < len(r) else '')

        # The day the export was taken, so a despatch date past it can be
        # reported as a schedule rather than passed off as a measurement.
        made_all = [to_date(cell(r, col['made'])) for r in body]
        asof = max((d for d in made_all if d), default=None)

        for r in body:
            out.lines += 1
            if not STAMPED.match(cell(r, col['ref']).upper()):
                continue                       # a marketplace, not the store
            if cell(r, col['reject']):
                out.rejected += 1
                continue
            gi = to_date(cell(r, col['gi']))
            made = to_date(cell(r, col['made']))
            gi_m, made_m = month_of_date(gi), month_of_date(made)
            if gi_m == month:
                which = BOOKED if made_m == month else CARRIED_IN
            elif made_m == month and gi_m and gi_m > month:
                which = CARRIED_OUT
            else:
                out.outside += 1
                continue
            sku = cell(r, col['sku'])
            if skip_sku and sku.upper().startswith(skip_sku):
                continue
            qty = parse_number(cell(r, col['qty'])) or 0.0
            amt = parse_number(cell(r, col['amt'])) or 0.0
            if gi and asof and gi > asof:
                out.scheduled += qty
            else:
                out.measured += qty

            # The payer is the profit file's own key, so the customer levels
            # come out at full depth with nothing inferred and nothing spread.
            c = customers.get(key_norm(cell(r, col['payer']))) or {}
            if not c:
                out.no_customer += 1
            key = [CUST.channel_of(c.get('account'), bool(c))]
            for _, slot, _ in cust_levels[1:]:
                key.append(c.get(slot) or CUST.BLANK)
            p = products.get(key_norm(sku)) or {}
            if not p:
                out.no_product += 1
            for _, slot, _ in prod_levels:
                key.append(sku or CUST.BLANK if slot == 'sku'
                           else p.get(slot) or CUST.BLANK)
            out.counted += 1
            out.add(tuple(key), which, qty, amt)
            # What brought it in, banded on the day it was ordered rather than
            # the day it shipped: the promotion was live when the customer
            # bought, not when the warehouse got to it. Carried out is left
            # alone - it is next month's revenue and has earned nothing here.
            if band_of is not None and which != CARRIED_OUT:
                out.add_band(tuple(key), band_of(sku, made), qty)
    return out if out.files else None


def report(m: Months, month: int, say=print) -> None:
    bq, ba, iq, ia, xq, xa = m.totals()
    say(f'\nthe month off SAP, {", ".join(m.files)}')
    say(f'  {m.counted:,} of {m.lines:,} line(s) belong to {month} - the rest '
        'are another month, a marketplace,\n  or an order that was rejected')
    say(f'  {"booked - left in the month, ordered in it":<44} {bq:>10,.0f} units '
        f'{ba:>14,.0f}')
    say(f'  {"carried in - left in it, ordered before":<44} {iq:>10,.0f} units '
        f'{ia:>14,.0f}')
    say(f'  {"carried out - ordered in it, leaves later":<44} {xq:>10,.0f} units '
        f'{xa:>14,.0f}')
    if m.scheduled:
        total = m.scheduled + m.measured
        say(f'  {m.scheduled:,.0f} of {total:,.0f} unit(s) '
            f'({m.scheduled / total * 100:.0f}%) sit on a despatch date that has '
            'not come yet -\n  a schedule rather than a measurement, almost all '
            'of it the carry-out')
    if m.rejected:
        say(f'  {m.rejected:,} line(s) were rejected and belong to no month')
    if m.no_customer:
        say(f'  {m.no_customer:,} line(s) matched no customer, so they carry the '
            'channel and nothing below it')
    if m.no_product:
        say(f'  {m.no_product:,} line(s) matched no product, so they carry a SKU '
            'and nothing above it')

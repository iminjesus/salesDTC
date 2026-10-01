#!/usr/bin/env python3
"""August orders, keyed the way the profit file is keyed.

The profit export is a month of sales with no order behind it: one row per
customer and product, and nothing that says which order it came from. The order
export is the other half - every August order, with a status saying whether it
has shipped yet.

Neither file can answer "what did August's orders earn" on its own, and no join
can either, because the link between them was never exported. What can be done
is to count units on both sides of the same key and say how they overlap:

    sold             units in the profit file        - August revenue
    ordered, shipped units on an August order that shipped
    ordered, open    units on an August order that has not

    from August orders = min(sold, ordered-shipped)
    carried in         = sold - that            ordered before August
    still to come      = ordered-open           will be a later month's revenue

`from August orders` is a share of a key, not a set of rows, so anything built
on it is an allocation and the page says so. It holds exactly as far as the
units of one key being worth the same as each other - the same assumption the
per-unit view of that page already runs on.

This module only produces the counts. What is done with them is the caller's.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
from cohort import is_dead                                     # noqa: E402
from promo_match import NAMES as O_NAMES                       # noqa: E402
from promo_match import code_norm, portal_levels, to_date      # noqa: E402
from rawdata import find, key_norm, parse_number, read_any     # noqa: E402
from reconcile import O_AMT, O_QTY, O_SKU, O_STATUS, classify  # noqa: E402

# What the order export calls the customer. Its vocabulary is the master's
# Type and Type2 rather than its Portal Group, which is why the lookup is an
# index of every spelling rather than a column-to-column join.
O_GROUP = ('Portal Group', 'portal_group', 'Portal_Group')
O_PORTAL = ('Portal', 'Portal Name', 'Store Portal')

DONE, OPEN = 0, 1             # which half of a value vector a count lands in


class Orders:
    """Per key: [done units, done amount, open units, open amount].

    What counts as done depends on how the file is being read. On the booking
    rule it is the status that books the money - COMPLETED - and open is
    everything still in flight; `tools/cohort.py` is where that rule was tested
    against the month it claims to explain.
    """

    def __init__(self, path):
        self.path = path
        self.by_key: dict[tuple, list[float]] = {}
        self.lines = self.kept = self.open = self.skipped = 0
        self.group_seen: dict[str, int] = {}
        self.group_hit: dict[str, int] = {}
        self.unknown: dict[str, float] = {}
        self.no_product = 0
        self.dates: list = []

    def month(self):
        """The month this export covers, as YYYYMM, or None if it spans more.

        The page models one month with the orders of that month and the one
        before it. An export quietly holding the wrong month would be modelled
        anyway, so the month is read off the rows rather than off the name.
        """
        if not self.dates:
            return None
        months = {d.year * 100 + d.month for d in self.dates}
        return months.pop() if len(months) == 1 else None

    def span(self):
        return (min(self.dates), max(self.dates)) if self.dates else (None, None)

    def add(self, key: tuple, qty: float, amt: float, which: int) -> None:
        v = self.by_key.get(key)
        if v is None:
            v = self.by_key[key] = [0.0, 0.0, 0.0, 0.0]
        v[which * 2] += qty
        v[which * 2 + 1] += amt

    def totals(self) -> list[float]:
        out = [0.0, 0.0, 0.0, 0.0]
        for v in self.by_key.values():
            for i in range(4):
                out[i] += v[i]
        return out


def load(path: Path, *, cust_levels, prod_levels, customer_master: Path | None,
         products: dict, shipped: set | None = None, booked: set | None = None,
         agree: float = 80.0, say=print) -> Orders | None:
    """Read the order export and total it onto the profit file's key.

    `cust_levels` and `prod_levels` are the level lists in the order the key is
    built in; `products` is the product master keyed by SKU. Returns None when
    the file cannot be read as orders, having said why.
    """
    rows, info = read_any(path)
    if not rows:
        say(f'  {path.name}: empty')
        return None
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    say(f'  {path.name}: {info["format"]}, {len(body):,} rows')

    col = {'sku': find(head, *O_SKU), 'qty': find(head, *O_QTY),
           'amt': find(head, *O_AMT), 'status': find(head, *O_STATUS),
           'group': find(head, *O_GROUP), 'portal': find(head, *O_PORTAL),
           'date': find(head, *O_NAMES['date'])}
    say('  order columns:')
    for what in ('sku', 'qty', 'amt', 'status', 'group'):
        i = col[what]
        say(f'    {what:<7} ' + (repr(head[i]) if i is not None
                                 else '-- not found --'))
    if col['sku'] is None or col['qty'] is None:
        say('  without a product code and a quantity there is nothing to count '
            'against the profit file')
        return None

    portals = portal_levels(customer_master, agree, say=lambda *_: None) \
        if customer_master else {}
    if portals:
        say(f'  customer master indexed under {len(portals):,} spelling(s) for '
            'the order side')

    out = Orders(path)

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    for r in body:
        out.lines += 1
        if col['date'] is not None:
            d = to_date(cell(r, col['date']))
            if d:
                out.dates.append(d)
        status = cell(r, col['status']) or '(blank)'
        if booked is not None:
            # The booking rule: one set of statuses books the money, everything
            # still in flight is carried to a later month, and an order that was
            # called off or came back is carried nowhere.
            verdict = ('shipped' if status.upper() in booked
                       else 'returned' if is_dead(status) else 'not shipped')
        elif shipped is not None:
            verdict = 'shipped' if status.upper() in shipped else 'not shipped'
        else:
            verdict = classify(status)
        if verdict == 'returned':
            # The order shipped and came back. The profit file counts quantity
            # net of returns, so it nets to nothing there too; counting it as a
            # shipment on this side would invent a gap.
            out.skipped += 1
            continue
        if verdict == 'unknown':
            # Only the shipped reading leaves a status unread; the booking rule
            # has somewhere for every one of them.
            out.skipped += 1
            out.unknown[status] = out.unknown.get(status, 0.0) + 1
            continue

        qty = parse_number(cell(r, col['qty'])) or 0.0
        amt = parse_number(cell(r, col['amt'])) or 0.0

        # The customer half. Every online order is on the online channel by
        # definition - that much needs no join - and the levels under it come
        # from whatever the order calls its group.
        group = cell(r, col['group'])
        found = {}
        for token in (group, cell(r, col['portal'])):
            if not token:
                continue
            found = portals.get(token.upper()) or portals.get(code_norm(token)) or {}
            if found:
                break
        if group:
            out.group_seen[group] = out.group_seen.get(group, 0) + 1
            if found:
                out.group_hit[group] = out.group_hit.get(group, 0) + 1

        key = [CUST.ONLINE]
        for _, slot, _ in cust_levels[1:]:
            key.append(found.get(slot) or CUST.BLANK)

        sku = cell(r, col['sku'])
        p = products.get(key_norm(sku)) or {}
        if not p:
            out.no_product += 1
        for _, slot, _ in prod_levels:
            key.append(sku or CUST.BLANK if slot == 'sku'
                       else p.get(slot) or CUST.BLANK)

        which = DONE if verdict == 'shipped' else OPEN
        out.kept += verdict == 'shipped'
        out.open += verdict != 'shipped'
        out.add(tuple(key), qty, amt, which)

    return out


def report(o: Orders, say=print) -> None:
    """What the read made of the file, in the shape the other tools print."""
    sq, sa, oq, oa = o.totals()
    lo, hi = o.span()
    say(f'\n{o.path.name}: {o.lines:,} line(s) - {o.kept:,} booked ({sq:,.0f} '
        f'units, {sa:,.0f}), {o.open:,} carried ({oq:,.0f} units, {oa:,.0f})')
    if lo:
        say(f'  order dates {lo} .. {hi}'
            + ('' if o.month() else '   <- more than one month in this file'))
    else:
        say('  no order date could be read, so the month cannot be checked')
    if o.skipped:
        say(f'  {o.skipped:,} line(s) left out: returns, and statuses that say '
            'neither one thing nor the other')
    if o.unknown:
        worst = sorted(o.unknown.items(), key=lambda kv: -kv[1])[:6]
        say('  statuses read as neither: '
            + ', '.join(f'{s} ({int(n):,})' for s, n in worst))
        say('  name the ones that mean shipped with --shipped "A,B,C"')
    seen = sum(o.group_seen.values())
    hit = sum(o.group_hit.values())
    if seen:
        say(f'  portal groups: {hit:,} of {seen:,} line(s) found their group in '
            f'the customer master ({hit / seen * 100:.0f}%)')
        missed = sorted(((g, n) for g, n in o.group_seen.items()
                         if not o.group_hit.get(g)), key=lambda t: -t[1])[:6]
        if missed:
            say('    not in the master: '
                + ', '.join(f'{g} ({n:,})' for g, n in missed)
                + ' - those lines keep the channel and nothing below it')
    if o.no_product:
        say(f'  {o.no_product:,} line(s) matched no product, so they carry a SKU '
            'and nothing above it')

#!/usr/bin/env python3
"""Work out which promotion each order came in on.

    py tools\\promo_match.py --profile     # describe every file, change nothing
    py tools\\promo_match.py               # attribute, and cross-check the two

The plan arrives as one file per division - MX_product, ce_product - in the same
shape with a few of the columns spelled differently. Both are read together, and
where they differ from each other is printed before anything is read out of
them, because a column one file spells differently is a column that reads as
blank in the other.

The order export already answers most of this itself: `promotion_rule` is what
the store applied, and `Voucher Code(s)` is what the customer typed. Neither is
a guess, so both are used before anything is inferred. Three sources, in order
of how much they can be trusted:

  rule      the engine's own promotion code, parsed into something readable
  voucher   the order's voucher found in the plan's Voucher_Code column
  plan      the SKU, in a promotion whose window covers the order date, at a
            price near the one paid - an inference, and labelled as one

Where a rule and the plan both answer, they are compared, because the two
disagreeing is worth more than either on its own.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                       # noqa: E402
from rawdata import (find, parse_number, pick_file,            # noqa: E402
                     pick_latest, read_any)

ROOT = Path(__file__).resolve().parent.parent

# Header names these exports have used. The first hit wins; --flags override.
NAMES = {
    'sku':     ('SKU', 'Product Code', 'Material', 'Material Code', 'Model',
                'Model Code', 'Product Number', 'Item Code', 'Item'),
    'promo':   ('Nationwide_Campaign', 'Promotion Name', 'Promotion',
                'Campaign', 'Program'),
    # The plan carries three campaign columns, not two. 'promo' took the
    # nationwide one and 'promo2' the second DTC one, which left DTC_Campaign1
    # - 49% filled on CE, and the column that holds Samsung Week, Boost Week
    # and the launches - read by nothing at all.
    'promo3':  ('DTC_Campaign1',),
    'promo2':  ('DTC_Campaign2', 'Offer_Detail', 'Offer Detail'),
    'type':    ('Offer_Type', 'Offer Type', 'Mechanic'),
    'start':   ('Start_Date', 'Start Date', 'Start', 'Valid From', 'From Date'),
    'end':     ('End_Date', 'End Date', 'End', 'Valid To', 'To Date'),
    'status':  ('Status', 'PUMI', 'Approval'),
    'site':    ('Site', 'Channel'),
    'voucher': ('Voucher_Code', 'Voucher Code', 'Voucher Code(s)', 'Vouchers',
                'Coupon', 'Coupon Code'),
    'rule':    ('promotion_rule', 'Promotion Rule', 'Promo Rule', 'Rule'),
    'date':    ('Date', 'Order Date', 'Order Creation Date', 'Created Date',
                'Invoice Date'),
    'order':   ('Order Code', 'Order No', 'Order Number', 'Order ID',
                'Sales Order', 'Document'),
    'qty':     ('Quantity', 'Qty', 'Order Qty', 'Units'),
    'amount':  ('AUD Revenue excl. GST', 'Net Amount', 'Amount', 'Net Sales',
                'Line Total', 'Revenue'),
    'group':   ('Portal Group', 'Site', 'Channel', 'Store'),
    'cancel':  ('Cancelled', 'Order Cancelled'),
    'cat':     ('Product Category', 'Category', 'Product Division', 'Product'),
    'division': ('Product Division', 'Division'),
    # Finer than the portal group and carried by the order itself, so it needs
    # no inference at all: commbank_yello_au, samsung_benefits_au, au.
    'portal': ('Portal', 'Portal Name', 'Store Portal'),
    # The plan names the product as well as the offer, which is the only
    # description a material that has not sold yet has anywhere.
    'category': ('Category', 'Product Category'),
    'prange': ('Range', 'product_range'),
    'pname': ('Product_Name', 'Product Name', 'Description'),
}
# A rule spells its mechanic in short; the plan spells it out. Same thing.
MECHANIC = {'DISC': 'Discount', 'DISCOUNT': 'Discount', 'PWP': 'PWP',
            'GWP': 'GWP', 'BUNDLE': 'Bundle', 'BDL': 'Bundle',
            'CASHBACK': 'Cashback', 'CB': 'Cashback', 'TRADEUP': 'Trade-Up',
            'TRADEIN': 'Trade-In', 'VOUCHER': 'Voucher', 'PROMO': 'Discount',
            # How the plan writes the same six - in words, with separators,
            # where the store writes one token.
            'PURCHASEWITHPURCHASE': 'PWP', 'GIFTWITHPURCHASE': 'GWP',
            'FREEGIFT': 'GWP', 'TRADEUPTRADEIN': 'Trade-In',
            'REDEMPTION': 'Cashback', 'PRICEOFF': 'Discount',
            'INSTANTDISCOUNT': 'Discount',
            # CE's own four, read off CE_product's Offer_Type column, which is
            # 100% filled and spells its ten mechanics in words. Without them
            # 1,044 live plan lines - a ninth of the file - came back as
            # "mechanic not in the vocabulary" and disagreed with every rule
            # they were compared against.
            'DELIVERYINSTALL': 'Delivery/Install',
            'FREEDELIVERY': 'Delivery/Install',
            # And the ones the store writes on CE's own rule codes. BOGO is
            # 11,109 units of CE's promoted - the third largest thing in the
            # file - and was reading as "mechanic not in the code".
            'BOGO': 'BOGO', 'SHIPPING': 'Delivery/Install',
            'FREESHIPPING': 'Delivery/Install', 'FOC': 'GWP',
            'SAMSUNGCARE': 'Samsung Care+', 'SAMSUNGCAREPLUS': 'Samsung Care+',
            'REWARDSEARN': 'Rewards Earn', 'REWARDSBURN': 'Rewards Burn'}


# Words that sit beside the mechanic and say nothing about which it was.
#
# MESSAGE and AUME are prefixes the store glues on - MESSAGE on 60% of CE's
# promoted units, AUME on 50% - and a long run of digits is the promotion's own
# id. Neither says anything about the offer, and both are why CE's offer level
# came back with 3,949 distinct values that the eight biggest covered a third
# of: the same offer, re-numbered every time it ran. Short numbers stay, because
# 5PCT and 50 are the offer.
# CE adds a typo of its own - MESSSAGE, three Ss, on 406 units - and three
# words that name the channel or the division rather than the offer: B2C, DTC,
# CE. 'AU' was already here for the same reason.
NOISE = {'PROMOTEXT', 'RULE', 'EXECUTE', 'ALL', 'AU', 'THE', 'AND', 'OF',
         'MESSAGE', 'MESSSAGE', 'AUME', 'B2C', 'DTC', 'CE'}
ID_CODE = re.compile(r'^\d{4,}$')


# The plan and the store are not two vocabularies for one thing. The plan names
# what the offer **is** - a Bundle, a Voucher - and the rule names what the
# engine **did** to deliver it. A bundle is sold as purchase-with-purchase at a
# discount, so the plan's `Bundle` and the rule's `PWP + Discount` are the same
# promotion described one level apart, and comparing them as if they were
# synonyms measures nothing: on August that one pair alone was 74% of every
# disagreement the cross-check found.
#
# So a plan type is compared against the mechanics it is *executed* as. Only
# where the execution is genuinely implied - a voucher is a discount applied by
# code, a trade-in is a discount for the trade. `Discount` stays strict: a plan
# that says Discount and a rule that says PWP is a difference worth keeping.
EXECUTED_AS = {
    'Bundle':   {'Bundle', 'PWP', 'Discount'},
    'Voucher':  {'Voucher', 'Discount'},
    'Trade-In': {'Trade-In', 'Trade-Up', 'Discount'},
    'Trade-Up': {'Trade-Up', 'Trade-In', 'Discount'},
    # The commonest unreconciled pair in September: the plan says Gift with
    # Purchase and the rule ran a discount, or a discount and a voucher - 116
    # lines of the 233 that fitted neither reading. A gift is given by taking
    # its price off, so that is the same promotion described at two levels.
    'GWP':      {'GWP', 'PWP', 'Discount', 'Voucher'},
    # CE's four. Free delivery is a discount on the delivery line; Samsung
    # Care+ is sold at a dollar with the product, which is a PWP; burning
    # points is a voucher the customer did not pay cash for. Earning points
    # changes no price at all, so it is delivered as itself and a rule that
    # discounts alongside it is a different promotion, not the same one.
    'Delivery/Install': {'Delivery/Install', 'Discount', 'GWP'},
    'Samsung Care+':    {'Samsung Care+', 'PWP', 'Discount', 'Bundle'},
    'Rewards Burn':     {'Rewards Burn', 'Voucher', 'Discount'},
    'Rewards Earn':     {'Rewards Earn'},
    'BOGO':             {'BOGO', 'GWP', 'PWP', 'Discount'},
}


def real(v) -> bool:
    """Does this cell say anything?

    A plan writes "not applicable" as a dash, and `Yes` turns up in CE's
    campaign columns where a Hot_Deals flag was pasted one column over. Both
    read as a campaign name called '-' or 'Yes' in any chart that groups by it.
    """
    t = str(v or '').strip()
    return bool(t) and t != '-' and t.lower() not in ('yes', 'no', 'n/a')


def mechanics_in(text: str) -> tuple[list, list]:
    """The mechanics named anywhere in a code, and what is left of it.

    Split on every non-alphanumeric, not on whitespace. A code carrying no
    dates comes back from parse_rule as one unbroken underscore string, so
    splitting on spaces looked at `welcome-voucher_-_percentage-discount` and
    saw a single word that is in no vocabulary - which left a fifth of the
    promoted units with no mechanic, and made every one of them disagree with
    the plan in the cross-check below.

    Adjacent words are tried joined as well. The store writes `TRADEUP` as one
    token; the plan writes `Trade-Up`, and splitting that gives TRADE and UP,
    neither of which is a mechanic. The two sides spell the same thing with and
    without a separator, so both spellings have to be looked for or the plan
    side never matches at all.
    """
    words = [w for w in re.split(r'[^A-Za-z0-9]+', text) if w]
    kinds, rest, used = [], [], set()
    for i, w in enumerate(words):
        if i in used:
            continue
        for n in (3, 2):                    # the longest join wins
            if i + n <= len(words):
                j = ''.join(words[i:i + n]).upper()
                if j in MECHANIC:
                    kinds.append(MECHANIC[j])
                    used.update(range(i, i + n))
                    break
        else:
            u = w.upper()
            if u in MECHANIC:
                kinds.append(MECHANIC[u])
            elif u not in NOISE and not ID_CODE.match(u):
                rest.append(w)
    return kinds, rest


def mechanic_of(rules: list[dict]) -> tuple[str, str]:
    """The offer type and detail a set of rules describes.

    The plan names an Offer_Type and an Offer_Detail; a rule carries the same
    two things run together in its code. Reading the mechanic out of the rule
    lets both sides sit on one pair of levels instead of two vocabularies that
    cannot be charted together.

    The set is sorted, so a rule naming PWP and a discount lands in one bucket
    however the two were ordered in the cell.
    """
    kinds, rest = [], []
    for d in rules:
        k, r = mechanics_in(d['what'])
        kinds += k
        if ' '.join(r):            # and no falling back to the raw code
            rest.append(' '.join(r))
    return (' + '.join(sorted(set(kinds))) or '(not named in the rule)',
            ' + '.join(dict.fromkeys(rest)) or '(no detail)')


def portal_levels(path: Path, agree: float = 80.0, say=print) -> dict:
    """The customer hierarchy, keyed by whatever the order calls its group.

    The order export carries a portal group, not a payer - and its vocabulary
    is not the customer master's `Portal Group` column. `S.COM` and `EPP` are
    spelled in the master's Type, `EDU` and `Partnership` in its Type2, and the
    master's own Portal Group holds different words again (`EPP External`,
    `3PD`). Matching one named column against another therefore misses almost
    everything.

    So every value of every level is indexed as a possible spelling, and a
    lookup returns only what the accounts behind it agree on. Asking for `EPP`
    settles the Type, because every account spelled that way carries it; it
    leaves Type2 blank, because those accounts carry several. Blank here means
    "the master does not say", which is worth more than a plausible guess.
    """
    rows, _ = read_any(path)
    head = [h.strip() for h in rows[0]]
    cols = {slot: find(head, *names) for _, slot, names in CUST.LEVELS if names}
    cols['account'] = find(head, *CUST.ACCOUNT_NAMES)
    cols = {k: i for k, i in cols.items() if i is not None}
    if not cols:
        say('  customer_2608 carries none of the levels, so it cannot be joined')
        return {}

    tally: dict[str, dict[str, dict[str, int]]] = {}
    where: dict[str, set] = {}
    for r in rows[1:]:
        vals = {slot: (r[i].strip() if i < len(r) else '') for slot, i in cols.items()}
        live = {s: v for s, v in vals.items() if v and v != '-'}
        for slot, v in live.items():
            for key in {v.upper(), code_norm(v)}:
                if not key:
                    continue
                where.setdefault(key, set()).add(head[cols[slot]])
                t = tally.setdefault(key, {})
                for s2, v2 in live.items():
                    t.setdefault(s2, {})
                    t[s2][v2] = t[s2].get(v2, 0) + 1

    out = {}
    for key, t in tally.items():
        row = {}
        for slot, counts in t.items():
            total = sum(counts.values())
            best = max(counts, key=counts.get)
            # Only assert what the accounts behind this spelling agree on.
            if counts[best] >= total * agree / 100:
                row[slot] = best
        row['channel'] = (CUST.channel_of(row['account']) if row.get('account')
                          else '')
        row['_from'] = ', '.join(sorted(where[key]))
        row['_spread'] = t          # kept so an unset level can be explained
        out[key] = row
    say(f'  customer master indexed under {len(out):,} spelling(s) across '
        + ', '.join(sorted({head[i] for i in cols.values()})))
    return out


# Every column in the plan that can hold a price, tried nearest-first against
# what the order actually paid. Which one wins is reported, because "matched
# T2_Price" says which tier the customer was on.
PRICE_COLS = ('S.COM_Price', 'T1_Price', 'T2_Price', 'T3_Price', 'EDU_Price',
              'RRP', 'Promo Price', 'Promotion Price', 'Price')
# A plan row in one of these states was never live, so nothing sold under it.
DEAD = {'cancelled', 'tentative', 'draft', 'rejected'}

DATE_PATTERNS = ('%d/%m/%Y', '%Y-%m-%d', '%d-%b-%y', '%d-%b-%Y', '%d %b %Y',
                 '%Y/%m/%d', '%m/%d/%Y', '%d-%m-%Y', '%Y%m%d', '%d/%m/%y',
                 '%d.%m.%Y', '%b %d %Y')
EXCEL_EPOCH = date(1899, 12, 30)
RULE_DATE = re.compile(r'^(\d{1,2})([A-Z]{3})(\d{2})$')
MONTHS = {m: i + 1 for i, m in enumerate(
    ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
     'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'))}


def to_date(v) -> date | None:
    """The date a cell holds, or None. Day-first where it is ambiguous."""
    t = str(v or '').strip()
    if not t or t == '-':
        return None
    if ' ' in t or 'T' in t:
        t = re.split(r'[ T]', t)[0]              # drop a time part
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    n = parse_number(t)
    if n is not None and 20000 < n < 60000:      # an Excel serial
        return EXCEL_EPOCH + timedelta(days=int(n))
    return None


def code_norm(v) -> str:
    return re.sub(r'[^0-9A-Z]', '', str(v or '').upper())


def parse_rule(token: str) -> dict:
    """Pull a promotion rule apart into something a person can read.

    They come out of the store as one underscore-joined code, for example
    AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT: a country, a site,
    a channel, two dates, then the mechanic and what it was. The dates are the
    landmark - whatever sits before them describes where it ran, whatever sits
    after describes the offer - so the shape is read off them rather than off
    fixed positions, which vary.
    """
    raw = token.strip()
    parts = [p for p in raw.split('_') if p]
    at = [i for i, p in enumerate(parts) if RULE_DATE.match(p.upper())]

    def as_date(p):
        m = RULE_DATE.match(p.upper())
        d, mon, y = m.group(1), MONTHS.get(m.group(2)), int(m.group(3))
        return date(2000 + y, mon, int(d)) if mon else None

    if not at:
        return {'raw': raw, 'where': ' '.join(parts[:2]), 'what': raw,
                'start': None, 'end': None}
    head, tail = parts[:at[0]], parts[at[-1] + 1:]
    return {
        'raw': raw,
        'where': ' '.join(head),
        'what': ' '.join(tail) or ' '.join(head),
        'start': as_date(parts[at[0]]),
        'end': as_date(parts[at[-1]]) if len(at) > 1 else None,
    }


def split_rules(v: str) -> list[str]:
    """One cell can hold several rules, joined by commas or semicolons."""
    return [p.strip() for p in re.split(r'[,;|]', str(v or '')) if p.strip()
            and p.strip() != '-']


# ── the plan ────────────────────────────────────────────────────────────────
PROBE_STEM = 8          # the stem length the "what would looser buy" report uses


class Plan:
    """The promotion plan, indexed by product code and by voucher."""

    def __init__(self, rows, stem=0):
        self.rows = rows
        self.stem = stem
        self.by_code = {}
        self.by_voucher = {}
        for r in rows:
            self.by_code.setdefault(r['code'], []).append(r)
            for v in r['vouchers']:
                self.by_voucher.setdefault(v, []).append(r)
        self.by_length = sorted(self.by_code, key=len, reverse=True)
        self.by_stem = {}
        self.probe = {}
        for c, rs in self.by_code.items():
            if stem and len(c) >= stem:
                self.by_stem.setdefault(c[:stem], []).extend(rs)
            if len(c) >= PROBE_STEM:
                self.probe.setdefault(c[:PROBE_STEM], []).extend(rs)

    def candidates(self, code):
        """The plan lines that could be this product, and how that was decided.

        Four rules, loosest last, each named on the row it produces. Beyond an
        exact code they are inferences, and an inference that is not labelled
        is indistinguishable from a fact.
        """
        if not code:
            return [], 'the order has no product code'
        if code in self.by_code:
            return self.by_code[code], 'code'
        for planned in self.by_length:
            if len(planned) >= 6 and code.startswith(planned):
                return self.by_code[planned], 'code starts with ' + planned
        for planned in self.by_length:
            if len(code) >= 6 and planned.startswith(code):
                return self.by_code[planned], 'code is the start of ' + planned
        # The same model in another colour or capacity - SM-L320NDAAXSA and
        # SM-L320NZSAXSA are one product, planned and priced alike.
        if self.stem and len(code) >= self.stem:
            hit = self.by_stem.get(code[:self.stem])
            if hit:
                return hit, 'same first %d characters' % self.stem
        return [], 'the plan has no line for this product'


def plan_columns(head: list[str]) -> dict:
    """Where the plan keeps the pieces a promotion is made of."""
    P = {k: find(head, *NAMES[k]) for k in
         ('sku', 'promo', 'promo3', 'promo2', 'type', 'start', 'end', 'status',
          'site', 'voucher', 'division', 'category', 'prange', 'pname')}
    P['promo2b'] = find(head, 'Offer_Detail', 'Offer Detail')
    return P


def plan_price_columns(head: list[str]) -> list:
    """The price columns the plan actually has, in PRICE_COLS order."""
    return [(c, i) for c in PRICE_COLS if (i := find(head, c)) is not None]


def plan_fields(head: list[str], body: list, args, name: str = '') -> dict:
    """The plan's columns, with any --promo-* override applied.

    An override that names a column this file does not have is a warning and
    not the end of the run: with a plan per division the flag that fixes MX's
    spelling need not exist in CE's, and aborting on that would make the flag
    unusable for the pair.
    """
    P = plan_columns(head)
    for slot, flag in (('sku', 'promo_sku'), ('promo', 'promo_name'),
                       ('start', 'promo_start'), ('end', 'promo_end'),
                       ('voucher', 'promo_voucher')):
        want = getattr(args, flag, None)
        if not want:
            continue
        i = find(head, want)
        if i is None:
            print(f'  {name}: no column named {want!r}, keeping '
                  + (repr(head[P[slot]]) if P.get(slot) is not None else 'none'))
            continue
        P[slot] = i
    return P


def plan_lines(body, P, price_cols, keep_cancelled: bool = False,
               source: str = '') -> tuple:
    """The plan as rows `Plan` can index, and how many were never live.

    Each row remembers which file it came from. With one plan that is noise;
    with a plan per division it is the difference between "the plan has no line
    for this product" and "the plan for the other division has it", which are
    not the same fault and do not have the same fix.
    """
    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    rows, dropped = [], 0
    for r in body:
        code = code_norm(cell(r, P['sku']))
        if not code:
            continue
        if not keep_cancelled and cell(r, P['status']).lower() in DEAD:
            dropped += 1
            continue
        label = ' / '.join(x for x in (cell(r, P['promo']), cell(r, P['promo3']),
                                       cell(r, P['promo2']), cell(r, P['type']))
                           if real(x)) or '(unnamed plan line)'
        rows.append({
            'code': code, 'promo': label, 'source': source,
            # The code as the plan spells it, and what the plan says the product
            # is: for a material that has never sold, this is the only place
            # either comes from.
            'sku': cell(r, P['sku']),
            'desc': cell(r, P['pname']),
            'division': cell(r, P['division']),
            'category': cell(r, P['category']),
            'range': cell(r, P['prange']),
            'type': cell(r, P['type']),
            'detail': cell(r, P['promo2b']) or cell(r, P['promo2']),
            'start': to_date(cell(r, P['start'])),
            'end': to_date(cell(r, P['end'])),
            'site': cell(r, P['site']),
            'vouchers': [code_norm(v) for v in split_rules(cell(r, P['voucher']))],
            'prices': {c: p for c, i in price_cols
                       if (p := parse_number(cell(r, i))) is not None},
        })
    return rows, dropped


def load_plan(path: Path, *, keep_cancelled: bool = False, stem: int = 0,
              say=print) -> tuple:
    """The plan file, read and indexed.

    Pulled out of the cross-check so another report can ask the plan what a
    product's list price and offer were in a given month without repeating the
    dozen small decisions - which status was never live, which columns hold a
    price, how a window is read, how a product code is normalised - that are
    exactly what makes two answers to that question disagree.
    """
    rows, info = read_any(path)
    if not rows:
        raise ValueError(f'{path.name} is empty')
    head = [h.strip() for h in rows[0]]
    P = plan_columns(head)
    if P['sku'] is None:
        raise ValueError(f'{path.name} has no product code column')
    price_cols = plan_price_columns(head)
    lines, dropped = plan_lines(rows[1:], P, price_cols, keep_cancelled,
                                path.name)
    dated = sum(1 for r in lines if r['start'] or r['end'])
    say(f'  {path.name}: {info["format"]}, {len(lines):,} live line(s), '
        f'{dated:,} with a window'
        + (f', {dropped:,} cancelled or unapproved left out' if dropped else ''))
    say('    prices: ' + (', '.join(c for c, _ in price_cols) or 'none'))
    return Plan(lines, stem), {'prices': [c for c, _ in price_cols],
                               'dropped': dropped, 'lines': len(lines)}


def load_plans(folder: Path, stems, *, keep_cancelled: bool = False,
               stem: int = 0, say=print) -> tuple:
    """Several plan files as one plan - a plan per division, read together.

    MX and CE keep their own file, in the same shape with the same columns
    spelled a little differently, and an order does not know which of them it
    belongs to. Reading them together means a CE order is matched against CE's
    plan without being told to look there, and a stem that is in neither comes
    back as genuinely unplanned rather than as "the file I happened to load
    does not have it".

    A stem that names no file is said and skipped, not fatal: one division's
    plan arriving a week late should cost that division's rows, not the run.
    """
    lines, meta = [], []
    for want in stems:
        path = pick_file(folder, want)
        if path is None:
            say(f'  no file matching {want!r} - skipped')
            continue
        try:
            rows, info = read_any(path)
            if not rows:
                raise ValueError('it is empty')
            head = [h.strip() for h in rows[0]]
            P = plan_columns(head)
            if P['sku'] is None:
                raise ValueError('no product code column')
            price_cols = plan_price_columns(head)
            got, dropped = plan_lines(rows[1:], P, price_cols, keep_cancelled,
                                      path.name)
        except (ValueError, OSError, IndexError, KeyError) as e:
            say(f'  {path.name}: {e} - skipped')
            continue
        lines += got
        meta.append({'path': path, 'head': head, 'P': P, 'lines': len(got),
                     'dropped': dropped,
                     'prices': [c for c, _ in price_cols],
                     'dated': sum(1 for r in got if r['start'] or r['end'])})
        say(f'  {path.name}: {info["format"]}, {len(got):,} live line(s), '
            f'{meta[-1]["dated"]:,} with a window'
            + (f', {dropped:,} cancelled or unapproved left out'
               if dropped else ''))
        say('    prices: ' + (', '.join(c for c, _ in price_cols) or 'none'))
    return Plan(lines, stem), meta


def plan_structure(meta: list, say=print) -> None:
    """Where two plan files disagree about their own shape.

    Said out loud because the alternative is finding out from a column that
    quietly read as blank for half the rows. A header one file has and the
    other does not is the whole of "similar, with a few differences", and it is
    cheaper to read it here than to explain a missing RRP later.
    """
    if len(meta) < 2:
        return
    names = [m['path'].name for m in meta]
    sets = [{h for h in m['head'] if h} for m in meta]
    shared = set.intersection(*sets)
    say(f'\nthe plan files, side by side: {len(shared)} column(s) in all of '
        + ', '.join(names))
    for m, own in zip(meta, sets):
        only = sorted(own - shared)
        if only:
            say(f'  only in {m["path"].name}: ' + ', '.join(only[:12])
                + (f' ... and {len(only) - 12} more' if len(only) > 12 else ''))
    # The columns this tool actually reads matter more than the rest of them.
    want = ('sku', 'promo', 'promo3', 'promo2', 'type', 'start', 'end',
            'status', 'site', 'voucher')
    say('  what each file answers with:')
    width = max(len(n) for n in names)
    for m in meta:
        head, P = m['head'], m['P']
        got = [f'{k}={head[P[k]]!r}' for k in want if P.get(k) is not None]
        gap = [k for k in want if P.get(k) is None]
        say(f'    {m["path"].name:<{width}}  ' + ', '.join(got))
        if gap:
            say(f'    {"":<{width}}  nothing for: ' + ', '.join(gap)
                + ' - read as blank')
        if 'RRP' not in m['prices']:
            say(f'    {"":<{width}}  no RRP column, so no list price from this '
                f'file')


def from_plan(order: dict, plan: Plan, tol: float, slack: int = 0) -> dict:
    """The plan line this order best fits, and what had to be assumed."""
    cands, how = plan.candidates(order['code'])
    if not cands:
        return {'promo': '', 'how': how, 'gap': '', 'alts': 0, 'priced': '',
                'type': '', 'detail': '', 'off_by': '', 'miss': 'code'}

    off_by = ''
    if order['date'] is not None:
        dated = [c for c in cands if c['start'] or c['end']]
        undated = [c for c in cands if c not in dated]

        def distance(c):
            """Days the order sits outside this window; 0 while inside it."""
            if c['start'] and order['date'] < c['start']:
                return (c['start'] - order['date']).days
            if c['end'] and order['date'] > c['end']:
                return (order['date'] - c['end']).days
            return 0

        if dated:
            near = sorted(dated, key=distance)
            best = distance(near[0])
            live = [c for c in near if distance(c) <= slack]
            if not live and not undated:
                return {'promo': '', 'gap': '', 'alts': len(dated), 'priced': '',
                        'type': '', 'detail': '', 'off_by': best, 'miss': 'window',
                        'how': how + f', but the nearest window it fits misses '
                               f'the order date by {best:,} day(s)'}
            if live and best:
                off_by = best
                how += f', in window give or take {best:,} day(s)'
            elif live:
                how += ', in window'
            cands = live + undated

    gap, priced_as = '', ''
    if order['price'] is not None:
        priced = [(c, col, p) for c in cands for col, p in c['prices'].items()]
        if priced:
            priced.sort(key=lambda t: abs(t[2] - order['price']))
            best, col, p = priced[0]
            gap = round(order['price'] - p, 2)
            off_pct = abs(gap) / abs(p) * 100 if p else 999.0
            if off_pct <= tol or abs(gap) <= 0.01:
                priced_as = col
                cands = [best] + [c for c in cands if c is not best]
                how += f', paid the {col}'
            else:
                nothing = [c for c in cands if not c['prices']]
                if not nothing:
                    return {'promo': '', 'gap': gap, 'alts': len(cands),
                            'priced': '', 'type': '', 'detail': '',
                            'off_by': off_by, 'miss': 'price',
                            'off_pct': round(off_pct, 1),
                            'how': how + f', but the price paid is {gap:+,.2f} '
                                   f'({off_pct:,.0f}%) from the nearest '
                                   f'({best["promo"]}, {col})'}
                cands, gap = nothing, ''
                how += ', price fits none of the priced lines'

    return {'promo': cands[0]['promo'], 'how': how, 'gap': gap,
            'type': cands[0]['type'], 'detail': cands[0]['detail'],
            'priced': priced_as, 'alts': len(cands) - 1, 'off_by': off_by,
            'miss': ''}


# ── describing a file ───────────────────────────────────────────────────────
def profile(name: str, head: list[str], rows: list[list[str]]) -> None:
    print(f'\n{name}: {len(rows):,} rows, {len(head)} columns')
    live = [(i, h) for i, h in enumerate(head)
            if any(i < len(r) and r[i].strip() for r in rows)]
    if len(live) < len(head):
        print(f'  ({len(head) - len(live)} column(s) are empty and skipped)')
    width = min(28, max((len(h) for _, h in live), default=8))
    for i, h in live:
        vals = [(r[i].strip() if i < len(r) else '') for r in rows]
        filled = [v for v in vals if v]
        seen = min(200, len(filled))
        dates = sum(1 for v in filled[:200] if to_date(v))
        nums = sum(1 for v in filled[:200] if parse_number(v) is not None)
        kind = ('date' if dates > seen * 0.8 else
                'number' if nums > seen * 0.8 else 'text')
        samples = ', '.join(sorted(set(filled), key=filled.index)[:3])
        print(f'  {h:<{width}}  {kind:<6} {len(filled) * 100 // len(vals):>3}% '
              f'filled, {len(set(filled)):>6,} distinct   e.g. {samples[:60]}')


def choose(head: list[str], rows: list[list[str]], what: str,
           override: str | None) -> int | None:
    if override:
        i = find(head, override)
        if i is None:
            print(f'  no column named {override!r}; columns are: '
                  + ', '.join(h for h in head if h), file=sys.stderr)
            raise SystemExit(2)
        return i
    return find(head, *NAMES[what])


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--plan', nargs='+', default=['MX_product', 'ce_product'],
                    metavar='STEM',
                    help='the promotion plan(s), one per division, read '
                         'together (default: MX_product ce_product; a '
                         'stem that names no file is skipped)')
    ap.add_argument('--orders', default='26 DTC Aug')
    ap.add_argument('--profile', action='store_true',
                    help='describe both files and stop')
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--html', nargs='?', const='', metavar='PATH',
                    help='also write a page to look at it in '
                         '(default dashboard/promo_2608.html)')
    ap.add_argument('--cdn', action='store_true',
                    help='link Chart.js in the page instead of embedding it')
    ap.add_argument('--price-tolerance', type=float, default=3.0, metavar='PCT',
                    help='how far the price paid may sit from a plan price and '
                         'still count, as a percent of it (default 3)')
    ap.add_argument('--stem', type=int, default=0, metavar='N',
                    help='match a product code on its first N characters when '
                         'nothing else fits - the same model in another colour '
                         'is planned alike (0 = off; try 8)')
    ap.add_argument('--window-slack', type=int, default=0, metavar='DAYS',
                    help='allow an order this many days outside a promotion '
                         'window (0 = strict). The row records how far out it '
                         'was, so a slack match is never mistaken for a clean one')
    ap.add_argument('--agree', type=float, default=80.0, metavar='PCT',
                    help='how much of the accounts behind a portal group must '
                         'carry the same value before that level is taken as '
                         'settled (default 80)')
    ap.add_argument('--gst', type=float, default=10.0, metavar='PCT',
                    help='added to the order amount before comparing, because '
                         'the plan quotes retail prices and the export does not '
                         '(default 10; 0 if they already agree)')
    ap.add_argument('--amount-is', choices=('line', 'unit'), default='line',
                    help='whether the order amount is the whole line or one '
                         'unit (default line, so it is divided by quantity)')
    ap.add_argument('--keep-cancelled', action='store_true',
                    help='keep cancelled orders and unapproved plan lines')
    for flag, what in (('promo-sku', 'product code in the plan'),
                       ('promo-name', 'campaign name'),
                       ('promo-start', 'first day it runs'),
                       ('promo-end', 'last day it runs'),
                       ('promo-voucher', 'voucher code in the plan'),
                       ('order-sku', 'product code on the order'),
                       ('order-date', 'order date'),
                       ('order-amount', 'what was paid'),
                       ('order-no', 'order number'),
                       ('order-qty', 'units'),
                       ('order-rule', "the store's own promotion code"),
                       ('order-voucher', 'voucher the customer used')):
        ap.add_argument(f'--{flag}', metavar='COLUMN', help=what)
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    op = pick_file(folder, args.orders)
    if op is None:
        print(f'no orders file matching {args.orders!r} in {folder.resolve()}',
              file=sys.stderr)
        return 2
    print('reading:')
    plans = []
    for want in args.plan:
        path = pick_file(folder, want)
        if path is None:
            print(f'  no plan file matching {want!r} - skipped')
            continue
        rows, info = read_any(path)
        if not rows:
            print(f'  {path.name} is empty - skipped')
            continue
        head, body = [h.strip() for h in rows[0]], rows[1:]
        print(f'  {path.name}: {info["format"]}, {info["encoding"]}, '
              f'{len(body):,} rows')
        plans.append({'path': path, 'head': head, 'body': body})
    if not plans:
        print(f'none of {", ".join(repr(w) for w in args.plan)} is in '
              f'{folder.resolve()}', file=sys.stderr)
        return 2

    o_rows, o_info = read_any(op)
    o_head, o_body = [h.strip() for h in o_rows[0]], o_rows[1:]
    print(f'  {op.name}: {o_info["format"]}, {o_info["encoding"]}, {len(o_body):,} rows')

    if args.profile:
        for f in plans:
            profile(f['path'].name, f['head'], f['body'])
        profile(op.name, o_head, o_body)

    for f in plans:
        f['P'] = plan_fields(f['head'], f['body'], args, f['path'].name)
        f['price_cols'] = plan_price_columns(f['head'])
    O = {
        'sku': choose(o_head, o_body, 'sku', args.order_sku),
        'date': choose(o_head, o_body, 'date', args.order_date),
        'amount': choose(o_head, o_body, 'amount', args.order_amount),
        'order': choose(o_head, o_body, 'order', args.order_no),
        'qty': choose(o_head, o_body, 'qty', args.order_qty),
        'rule': choose(o_head, o_body, 'rule', args.order_rule),
        'voucher': choose(o_head, o_body, 'voucher', args.order_voucher),
        'group': choose(o_head, o_body, 'group', None),
        'cat': choose(o_head, o_body, 'cat', None),
        'division': choose(o_head, o_body, 'division', None),
        'portal': choose(o_head, o_body, 'portal', None),
        'cancel': choose(o_head, o_body, 'cancel', None),
    }

    print('\ncolumns chosen  (--flags override any of these):')
    rows_out = []
    for f in plans:
        n, P, head = f['path'].name, f['P'], f['head']
        rows_out += [(n, 'product code', P['sku'], head, '--promo-sku'),
                     (n, 'campaign', P['promo'], head, '--promo-name'),
                     (n, 'also labelled by', P['promo2'], head, ''),
                     (n, 'offer type', P['type'], head, ''),
                     (n, 'starts', P['start'], head, '--promo-start'),
                     (n, 'ends', P['end'], head, '--promo-end'),
                     (n, 'status', P['status'], head, ''),
                     (n, 'voucher', P['voucher'], head, '--promo-voucher')]
    rows_out += [(op.name, 'product code', O['sku'], o_head, '--order-sku'),
                 (op.name, 'order date', O['date'], o_head, '--order-date'),
                 (op.name, 'order number', O['order'], o_head, '--order-no'),
                 (op.name, 'units', O['qty'], o_head, '--order-qty'),
                 (op.name, 'paid', O['amount'], o_head, '--order-amount'),
                 (op.name, 'promotion rule', O['rule'], o_head, '--order-rule'),
                 (op.name, 'voucher', O['voucher'], o_head, '--order-voucher'),
                 (op.name, 'portal group', O['group'], o_head, ''),
                 (op.name, 'portal', O['portal'], o_head, '')]
    width = max(len(n[:18]) for n, *_ in rows_out)
    for side, what, i, head, flag in rows_out:
        print(f'  {side[:18]:<{width}} {what:<16} '
              + (repr(head[i]) if i is not None
                 else '-- none --' + (f'  ({flag})' if flag else '')))
    for f in plans:
        print(f'  {f["path"].name[:18]:<{width}} {"prices":<16} '
              + (', '.join(c for c, _ in f['price_cols']) or '-- none --'))

    # Where several plans were read, how they differ from each other is the
    # first thing worth knowing about them.
    plan_structure([{'path': f['path'], 'head': f['head'], 'P': f['P'],
                     'prices': [c for c, _ in f['price_cols']]}
                    for f in plans])

    if args.profile:
        return 0
    live = [f for f in plans if f['P']['sku'] is not None]
    for f in plans:
        if f['P']['sku'] is None:
            print(f'\n{f["path"].name} has no product code column, so nothing '
                  f'in it can be matched - left out', file=sys.stderr)
    if not live or O['sku'] is None:
        print('\nWithout a product code on both sides nothing can be matched.',
              file=sys.stderr)
        return 1
    return run(args, live, op, o_head, o_body, O)


def run(args, plans, op, o_head, o_body, O) -> int:
    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── the plan ────────────────────────────────────────────────────────────
    # Every plan file given, read into one plan. An order does not know which
    # division's file it belongs to, so it is matched against all of them and
    # the line it matched says which one answered.
    plan_rows, dropped = [], 0
    for f in plans:
        got, lost = plan_lines(f['body'], f['P'], f['price_cols'],
                               args.keep_cancelled, f['path'].name)
        plan_rows += got
        dropped += lost
    plan = Plan(plan_rows, args.stem)
    portals = {}
    cp = pick_latest(Path(args.dir), 'customer')
    if cp:
        portals = portal_levels(cp, args.agree)
    dated = sum(1 for r in plan_rows if r['start'] or r['end'])
    print(f'\nplan: {len(plan_rows):,} line(s) over {len(plan.by_code):,} product '
          f'code(s); {dated:,} carry a window, {len(plan.by_voucher):,} voucher '
          f'code(s)' + (f'; {dropped:,} cancelled or unapproved line(s) left out'
                        if dropped else ''))
    if len(plans) > 1:
        per = collections.Counter(r['source'] for r in plan_rows)
        codes = {f['path'].name: {r['code'] for r in plan_rows
                                  if r['source'] == f['path'].name}
                 for f in plans}
        for f in plans:
            n = f['path'].name
            print(f'  {n}: {per[n]:,} line(s) over {len(codes[n]):,} code(s)')
        shared = set.intersection(*codes.values()) if codes else set()
        if shared:
            print(f'  {len(shared):,} product code(s) are in more than one plan '
                  f'file, where the nearest price decides which line wins')

    # ── the orders ──────────────────────────────────────────────────────────
    out, gaps, page = [], [], []
    portal_seen: dict[str, int] = {}
    portal_hit: dict[str, int] = {}
    near_window: list[int] = []
    near_price: list[float] = []
    near_code = 0
    slack_used = 0
    source = {'rule': 0, 'voucher': 0, 'plan': 0, 'none': 0}
    # A voucher attribution of zero is either "no order used one" or "the join is
    # broken", and those need telling apart. Counted on the way past.
    vouch = {'carried': 0, 'known': 0}
    agree = {'same': 0, 'differ': 0, 'outside': 0, 'as_run': 0, 'apart': 0}
    clash = collections.Counter()
    by_promo: dict[tuple, list[float]] = {}
    cancelled = 0
    for r in o_body:
        if not args.keep_cancelled and cell(r, O['cancel']).lower() in ('yes', 'y',
                                                                       'true'):
            cancelled += 1
            continue
        qty = parse_number(cell(r, O['qty'])) or 0.0
        amount = parse_number(cell(r, O['amount']))
        paid = None
        if amount is not None:
            per = amount / qty if args.amount_is == 'line' and qty else amount
            paid = per * (1 + args.gst / 100) if per is not None else None
        order = {'code': code_norm(cell(r, O['sku'])),
                 'date': to_date(cell(r, O['date'])), 'price': paid}

        rules = [parse_rule(t) for t in split_rules(cell(r, O['rule']))]
        vouchers = [code_norm(v) for v in split_rules(cell(r, O['voucher']))]
        v_hits = [p for v in vouchers for p in plan.by_voucher.get(v, [])]
        if vouchers:
            vouch['carried'] += 1
            vouch['known'] += bool(v_hits)
        guess = from_plan(order, plan, args.price_tolerance, args.window_slack)
        if guess['gap'] != '':
            gaps.append(guess['gap'])
        # What each miss missed by, so the cost of loosening can be counted
        # rather than guessed at.
        if not guess['promo'] and not rules and not v_hits:
            if guess['miss'] == 'window':
                near_window.append(guess['off_by'])
            elif guess['miss'] == 'price':
                near_price.append(guess['off_pct'])
            elif guess['miss'] == 'code' and order['code']:
                if len(order['code']) >= PROBE_STEM and \
                        order['code'][:PROBE_STEM] in plan.probe:
                    near_code += 1

        if rules:
            # Sorted and deduplicated. One promotion arrives as two rules - the
            # discount and the message that announces it - and the store writes
            # them in either order, so the same offer came out as two rows of
            # the summary: QBH8-50-PCT-RRP-FF8F was 1,997 lines under one
            # ordering and 1,862 under the other, when it is one promotion of
            # 3,859 and the largest in the month.
            how = 'rule'
            promo = ' + '.join(sorted({d['what'] for d in rules}))
            # The two name promotions in different vocabularies - a rule says
            # PWP, the plan says "Black Friday / PWP" - so comparing the names
            # would measure nothing. The mechanic is the part both spell, and
            # the rule's own window is a check that needs no plan at all.
            if guess['type']:
                # Both sides through the same vocabulary. Comparing the first
                # three characters of whatever the code happened to start with
                # against the plan's own words was not a comparison at all: on
                # a dateless rule it tested 'AU_' and always said they differ.
                kinds = set()
                for d in rules:
                    kinds.update(mechanics_in(d['what'])[0])
                want = set(mechanics_in(guess['type'])[0]) or {guess['type']}
                # Widened to how the plan's offer is actually delivered.
                wide = set(want)
                for w in want:
                    wide |= EXECUTED_AS.get(w, set())
                if kinds:
                    strict = bool(kinds & want)
                    ok = bool(kinds & wide)
                    agree['same' if strict else 'differ'] += 1
                    agree['as_run' if ok else 'apart'] += 1
                    if not ok:
                        clash[(' + '.join(sorted(kinds)), guess['type'])] += 1
            if order['date'] is not None:
                for d in rules:
                    if (d['start'] and order['date'] < d['start']) or \
                            (d['end'] and order['date'] > d['end']):
                        agree['outside'] += 1
                        break
        elif v_hits:
            how, promo = 'voucher', v_hits[0]['promo']
        elif guess['promo']:
            how, promo = 'plan', guess['promo']
        else:
            how, promo = 'none', ''
        source[how] += 1

        key = (how, promo or '(no promotion found)')
        agg = by_promo.setdefault(key, [0.0, 0.0, 0.0])
        agg[0] += 1
        agg[1] += qty
        agg[2] += amount or 0.0
        # The offer, on one pair of levels whichever source answered.
        if how == 'rule':
            o_type, o_detail = mechanic_of(rules)
        elif how == 'voucher':
            o_type = v_hits[0]['type'] or '(not named in the plan)'
            o_detail = v_hits[0]['detail'] or v_hits[0]['promo']
        elif how == 'plan':
            o_type = guess['type'] or '(not named in the plan)'
            o_detail = guess['detail'] or guess['promo']
        else:
            o_type = o_detail = '(nothing fits)'
        group = cell(r, O['group']) or '(blank)'
        c = portals.get(group.upper()) or portals.get(code_norm(group)) or {}
        portal_seen[group] = portal_seen.get(group, 0) + 1
        if c:
            portal_hit[group] = portal_hit.get(group, 0) + 1
        # Where the group matched but the master would not commit to a level,
        # say that rather than print a blank - the two mean different things.
        unset = '(master does not say)' if c else CUST.NO_MATCH
        if how == 'plan' and guess['off_by']:
            slack_used += 1
        # A plan match that needed a loosened rule is not the same answer as
        # one that did not, and the page should not colour them alike.
        if how == 'plan' and (guess['off_by'] or 'starts with' in guess['how']
                              or 'is the start of' in guess['how']
                              or 'same first' in guess['how']):
            how_page = 'loose'
        else:
            how_page = how
        page.append((how_page,
                     c.get('channel') or unset,
                     c.get('type') or unset, c.get('type2') or unset,
                     group, cell(r, O['portal']) or '(blank)', o_type, o_detail,
                     cell(r, O['cat']) or '(blank)',
                     order['date'].isoformat() if order['date'] else '',
                     qty, amount or 0.0))
        out.append([
            cell(r, O['order']), cell(r, O['sku']), cell(r, O['group']),
            order['date'].isoformat() if order['date'] else '',
            qty, amount if amount is not None else '',
            round(paid, 2) if paid is not None else '',
            how, promo,
            '; '.join(d['raw'] for d in rules),
            '; '.join(vouchers),
            guess['promo'], guess['how'], guess['priced'], guess['gap'],
            guess['off_by'], guess['alts'] or '',
        ])

    if portal_seen:
        hits = sum(portal_hit.values())
        total = sum(portal_seen.values())
        print(f'\nportal groups: {hits:,} of {total:,} line(s) found their group '
              'in the customer master')
        misses = sorted(((g, n) for g, n in portal_seen.items()
                         if not portal_hit.get(g)), key=lambda t: -t[1])
        for g, n in misses[:8]:
            print(f'  {g[:26]:<26} {n:>8,} line(s)  - no account is spelled that way')
        if misses:
            print('  the master spells its groups e.g. '
                  + ', '.join(sorted(portals)[:6]))
        for g, n in sorted(portal_hit.items(), key=lambda t: -t[1])[:8]:
            c = portals.get(g.upper()) or portals.get(code_norm(g)) or {}
            says = ' / '.join(f'{k}={v}' for k, v in c.items()
                              if not k.startswith('_') and k != 'account' and v)
            print(f'  {g[:26]:<26} {n:>8,} line(s)  <- found in '
                  f'{c.get("_from", "?")}; settles {says or "nothing"}')
            # A level left unset is more useful with the reason attached.
            for slot, counts in (c.get('_spread') or {}).items():
                if c.get(slot) or slot == 'account':
                    continue
                total = sum(counts.values()) or 1
                top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
                print(f'      {slot} unsettled: '
                      + ', '.join(f'{v} {n2 * 100 // total}%' for v, n2 in top)
                      + (' ...' if len(counts) > 3 else ''))

    if O['division'] is not None:
        divs: dict[str, int] = {}
        for r in o_body:
            d = cell(r, O['division']) or '(blank)'
            divs[d] = divs.get(d, 0) + 1
        total = sum(divs.values()) or 1
        print('\nthe order export by division - the plan only covers what it '
              'lists, so the rest cannot be attributed at all:')
        for d, c in sorted(divs.items(), key=lambda kv: -kv[1])[:6]:
            print(f'  {d[:20]:<20} {c:>8,} line(s)  {c * 100 / total:>5.1f}%')

    n = len(out) or 1
    print(f'\nattributed {len(out):,} order line(s)'
          + (f' ({cancelled:,} cancelled left out)' if cancelled else '') + ':')
    for k, label in (('rule', "the store's own promotion rule"),
                     ('voucher', 'a voucher the plan lists'),
                     ('plan', 'inferred from the plan - code, window, price'),
                     ('none', 'nothing fits')):
        print(f'  {source[k]:>8,}  {source[k] * 100 / n:>5.1f}%  {label}')
        if k == 'voucher' and not source['voucher']:
            # Said rather than left to be wondered about: a voucher is only
            # looked up where the order carries no rule, so nothing here usually
            # means the rule answered first, not that the join failed.
            print(f'           {vouch["carried"]:,} line(s) carry a voucher '
                  f'code, {vouch["known"]:,} of them one the plan lists; a '
                  f'voucher is\n           only read where the line has no '
                  f'rule, and {source["rule"]:,} line(s) had one')
    both = agree['same'] + agree['differ']
    if both:
        print(f'  of {both:,} line(s) the rule and the plan both answered for:')
        print(f"    the same mechanic         {agree['same']:>8,}  "
              f"{agree['same'] * 100 / both:>5.0f}%")
        print(f"    the plan's offer as run   {agree['as_run']:>8,}  "
              f"{agree['as_run'] * 100 / both:>5.0f}%   "
              '<- a Bundle delivered as PWP + Discount counts here')
        print(f"    neither                   {agree['apart']:>8,}  "
              f"{agree['apart'] * 100 / both:>5.0f}%")
    # A disagreement count on its own says nothing about whether the two really
    # disagree or whether one of them was read wrong. The pairs say which.
    if clash:
        print('\n  where they differ, the commonest pairs:')
        print(f'    {"the rule says":<28}{"the plan says":<28}{"lines":>8}')
        for (a, b), n in clash.most_common(12):
            print(f'    {a[:27]:<28}{b[:27]:<28}{n:>8,}')
        if len(clash) > 12:
            print(f'    and {len(clash) - 12:,} more pair(s)')
        print('    a pair that is plainly the same thing in two vocabularies is '
              'a word missing\n    from MECHANIC, not a promotion that ran off '
              'plan.')
    if agree['outside']:
        print(f"  {agree['outside']:,} line(s) carry a rule whose own dates do "
              'not cover the order date - the rule names its window, so this '
              'needs no plan to spot')
    if gaps:
        gaps.sort()
        mid = gaps[len(gaps) // 2]
        print(f'  price paid vs plan price, {len(gaps):,} comparison(s): '
              f'median {mid:+,.2f}, from {gaps[0]:+,.2f} to {gaps[-1]:+,.2f}')
        if abs(mid) > 1:
            print('  a median far from zero means the two quote prices on '
                  'different bases - try --gst or --amount-is')

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = outdir / 'promo_orders.csv'
    with lines.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Order', 'Product', 'Portal group', 'Date', 'Qty', 'Paid',
                    'Unit price compared', 'Source', 'Promotion', 'Rule raw',
                    'Voucher', 'Plan says', 'Plan matched by', 'Plan price used',
                    'Price gap', 'Days outside window', 'Other plan lines fit'])
        w.writerows(out)
    summary = outdir / 'promo_summary.csv'
    table = sorted(by_promo.items(), key=lambda kv: -kv[1][2])
    with summary.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Source', 'Promotion', 'Order lines', 'Qty', 'Amount'])
        w.writerows([how, name, int(v[0]), v[1], round(v[2], 2)]
                    for (how, name), v in table)
    print(f'\n-> {lines}\n-> {summary}')

    wide = min(52, max((len(nm) for (_, nm), _ in table[:15]), default=10))
    print(f'\n  {"":<9}{"":<{wide}} {"Lines":>8} {"Qty":>9} {"Amount":>15}')
    for (how, name), v in table[:15]:
        print(f'  {how:<9}{name[:52]:<{wide}} {v[0]:>8,.0f} {v[1]:>9,.0f} '
              f'{v[2]:>15,.0f}')
    if len(table) > 15:
        print(f'  ... and {len(table) - 15:,} more in {summary.name}')

    reasons: dict[str, int] = {}
    for row in out:
        if row[7] == 'none':
            why = row[12] or 'no plan line'
            # One reason per kind, not one per day count: the numbers vary
            # line by line and the tally is about the kinds.
            why = re.sub(r'\(.*?\)', '(...)', why)
            why = re.sub(r'[-+]?\d[\d,.]*', 'N', why)
            reasons[why] = reasons.get(why, 0) + 1
    if slack_used:
        print(f'  {slack_used:,} of the plan matches only fit because of '
              f'--window-slack {args.window_slack}; their row says by how many days')

    # The data is being matched before it is cleaned, so what matters is what
    # each loosening is worth and what it costs. Count both rather than guess.
    if near_code or near_window or near_price:
        print('\nwhat looser matching would buy, on the lines nothing fits now:')
        if near_code and not args.stem:
            print(f'  --stem {PROBE_STEM:<18} {near_code:>8,} more line(s) - the same '
                  f'model in another colour or capacity')
        for days in (1, 3, 7, 14):
            n2 = sum(1 for d in near_window if d <= days)
            if n2 and days > args.window_slack:
                print(f'  --window-slack {days:<11} {n2:>8,} more line(s) - '
                      f'ordered that close to a window')
        for tol in (5, 10, 20, 50):
            n2 = sum(1 for g in near_price if g <= tol)
            if n2 and tol > args.price_tolerance:
                print(f'  --price-tolerance {tol:<8} {n2:>8,} more line(s) - '
                      f'paid within {tol}% of a plan price')
        print('  each one is a looser rule, not a better one: the row says which '
              'rule matched it, so a loosening can be undone by reading back.')

    ranked = sorted(reasons.items(), key=lambda kv: -kv[1])
    if ranked:
        print('\nwhy nothing fit:')
        for why, count in ranked[:8]:
            print(f'  {count:>8,}  {why}')

    if args.html is not None:
        path = Path(args.html) if args.html else ROOT / 'dashboard' / 'promo_2608.html'
        write_page(path, args, ' + '.join(f['path'].name for f in plans),
                   op, page, ranked, cancelled)
    return 0


def write_page(path: Path, args, plan_name: str, op, page: list, reasons: list,
               cancelled: int) -> None:
    """One self-contained page, with the profit chart's controls.

    The rows are rolled up to one per source, per level value and per day -
    always fewer than the order lines and usually far fewer - so the filters
    and the drill work off sums rather than off forty thousand rows carried
    into the browser.
    """
    import json

    # The drill, top first. The customer half comes from the portal group
    # folded against the customer master; the offer half is the promotion.
    # Portal sits under Portal Group and comes off the order itself, so it
    # breaks the customer down further without inferring anything.
    LEVELS = ['Channel', 'Type', 'Type2', 'Portal Group', 'Portal',
              'Offer Type', 'Offer Detail', 'Product Category']
    sources: dict[str, int] = {}
    values: list[dict[str, int]] = [{} for _ in LEVELS]
    days = set()
    buckets: dict[tuple, list[float]] = {}

    def idx(d, v):
        return d.setdefault(v, len(d))

    for row in page:
        how, levels, day, qty, amt = row[0], row[1:9], row[9], row[10], row[11]
        days.add(day)
        key = (idx(sources, how),) + tuple(idx(values[i], v)
                                           for i, v in enumerate(levels)) + (day,)
        b = buckets.setdefault(key, [0.0, 0.0, 0.0])
        b[0] += 1
        b[1] += qty
        b[2] += amt

    payload = {
        'title': 'August 2026 Promotions',
        'plan': plan_name, 'orders': op.name,
        'lines': len(page), 'cancelled': cancelled,
        'sources': list(sources),
        'days': sorted(days),
        # Offer Type is where the page opens: it is the question this file
        # answers, and Offer Detail sits one click inside it.
        'startDim': LEVELS.index('Offer Type'),
        'custDepth': 5,
        'levels': [{'name': n, 'values': list(v)}
                   for n, v in zip(LEVELS, values)],
        'rows': [{'s': k[0], 'k': list(k[1:1 + len(LEVELS)]), 'd': k[-1],
                  'n': int(v[0]), 'q': round(v[1], 2), 'a': round(v[2], 2)}
                 for k, v in buckets.items()],
        'reasons': [[w, n] for w, n in reasons[:12]],
    }
    here = Path(__file__).resolve().parent.parent / 'dashboard'
    html = (here / 'promo_template.html').read_text(encoding='utf-8')
    html = html.replace('/*__DATA__*/null',
                        json.dumps(payload, ensure_ascii=False,
                                   separators=(',', ':')))
    if not args.cdn:
        lib = here / 'vendor' / 'chart.umd.js'
        if lib.is_file():
            code = lib.read_text(encoding='utf-8').replace('</script>', '<\\/script>')
            html = html.replace(
                '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>',
                f'<script>/* chart.umd.js */\n{code}\n</script>')
        else:
            print('vendor/chart.umd.js missing - the page will need a connection')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding='utf-8')
    print(f'-> {path.resolve()}  ({len(html.encode("utf-8")) / 1024:,.0f} KB, '
          f'{len(payload["rows"]):,} rolled-up row(s))')


if __name__ == '__main__':
    sys.exit(main())

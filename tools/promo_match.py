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
    # The order export states its own list price and its own discount. Where it
    # does, the discount needs no plan at all - which is the only way to see one
    # on a product the plan has no line for, and accessories are most of those.
    'rrp':     ('AUD RRP', 'RRP', 'List Price', 'Original Price',
                'Retail Price', 'Gross Price', 'Standard Price'),
    # Net before Customer, deliberately. The two differ by exactly the trade-in
    # and the points redeemed - 0.76 against 0.50 on a Fold8 traded up - and a
    # trade-in is not a price discount: the customer handed over a phone for it.
    # Net is what the promotion took off the price.
    'disc':    ('Average Net Discount', 'Average Customer Discount',
                'Discount Rate', 'Discount %', 'discount_rate', 'Discount',
                'Promotion Discount'),
    # Kept beside it so the gap can be named rather than silently included.
    'disc_all': ('Average Customer Discount', 'Customer Discount'),
    'trade':   ('AUD Trade-in Product Value excl. GST', 'Trade-in Value',
                'Trade-In Value', 'Trade-in Product Value'),
    'points':  ('Points Redeemed AUD Price', 'Points Redeemed'),
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



# What an offer *does*, which is the level a person can hold in their head.
#
# Read off the codes themselves rather than invented: `--tokens` counts the
# pieces the offer strings are built from, and these are the ones that came
# back on a large share of MX's units. The same offer is written several ways -
# 50PCT, 50PCTOFF, 50OFF, 50 PCT - and a wave code (26F, B4F, FF8F, 26R) is
# glued on each time it runs, which is what turned one offer into ten thousand.
#
# First match wins, so the order is the precedence: an accessories offer at 30%
# is filed under Accessories rather than under percent-off. Edit the table, not
# the code - that is the point of it being a table.
#
# These came off **MX's** codes. Another division writes its offers differently -
# CE's run to cashback, redemption, a bonus gift, delivery and installation - so
# on CE this table is a hypothesis, and the run says how much of it the table
# fails to name along with the tokens those unnamed units are built from. Write
# the new families from that list rather than from what sounds likely.
FAMILIES = [
    # ── what the offer was ──────────────────────────────────────────────────
    # A specific offer, named. These answer "what did the customer get", and
    # they come first because every row below describes something rather than
    # naming it.
    ('Trade-in / Trade-up',  r'TRADE'),
    ('Accessories offer',    r'\bACC(ESSORIES)?\b'),
    ('First 72 hours',       r'\d*HR\b|FIRST\d+'),
    ('Price match',          r'PRICE\s?MATCH'),
    ('Stunt promotion',      r'STUNT'),
    ('EPP surplus',          r'SURPLUS'),
    ('Aged clearance / EOL', r'CLEARANCE|AGED|\bEOL\b'),
    ('Cart abandon',         r'ABANDON'),
    ('Spend and save',       r'\bSPEND\b|\bBMSM\b'),
    ('Secret sale',          r'SECRET'),
    ('Live commerce',        r'LIVE\s?COMMERCE'),
    ('Flash sale',           r'\bFLASH'),        # FLASHTV9 too
    ('Staff / EDU offer',    r'\bSTAFF\b|\bEDU\b'),
    ('Samsung Care+',        r'SAMSUNG\s?CARE|\bSC\b'),
    ('Rewards points',       r'REWARD|\bPTS\b|POINTS'),
    ('Buy one get one',      r'\bBOGO\b'),
    ('Delivery / install',   r'DELIVERY|INSTALL|TABLETOP|SHIPPING'),
    ('Bonus gift',           r'\bBONUS\b|\bGIFT\b|\bFREE\b|\bFOC\b|\bGWP\b'),
    ('Bundle / PWP',         r'BUNDLE|PWP|PACKAGE'),
    # ── why it ran ──────────────────────────────────────────────────────────
    # A campaign, which beats a generic price word: the offer type level already
    # answers "what mechanic", so this level is where "why" belongs. A
    # "[Boost Week] EPP $100 Voucher" is filed under Boost Week, not under
    # voucher.
    ('Samsung / Boost Week', r'\bBOOST\b|SAMSUNG\s?WEEK|TECH\s?FEST'),
    # ── the standing offer ──────────────────────────────────────────────────
    # 5% off a first purchase, always on, and not a reason anything sold this
    # month. First in this table it collected 21,935 of CE's promoted units and
    # **none** were its alone - every one also ran under a real campaign, which
    # is what "only this one 0%" in the overlap report means. Here, those units
    # go to the campaign that drove them and the voucher keeps what it won by
    # itself, while a rule that is only the welcome voucher is still named as
    # one rather than as "% off".
    ('EPP welcome voucher',  r'WELCOME'),
    # ── how the price was written ───────────────────────────────────────────
    # Descriptions, not offers: anything still here was not named above, and
    # all these rows say is the shape of the discount.
    ('% off RRP',            r'RRP'),
    ('$ off',                r'\b\d{2,4}OFF\b'),
    ('% off',                r'\d+\s?PCT|PCTOFF|\d+OFF|\d+\s?PERCENT'),
    # The two rows above match 50PCT and 100OFF - the store writes a promotion
    # as one token. CE's plan writes the same thing in prose, "20% off" and
    # "$100 Discount", and punctuation is stripped before matching, so it
    # arrives as "20 OFF" and matches neither.
    ('Price off',            r'\d+\s?OFF\b|\d+\s?DISCOUNT\b|\bDEEPER\b'),
    ('$ voucher',            r'VOUCHER|\bCREDIT\b'),
    # ── last resorts ────────────────────────────────────────────────────────
    # `\bEPP\b` is on a third of the lines and says only which tier could buy,
    # so it names what nothing else could. Below it, the plan's Offer_Detail
    # cell used as a comment field, named so those lines can be counted and set
    # aside - last, because the words are ordinary English and a store rule that
    # happens to use one is still a real offer. CVM and CRP are deliberately not
    # in it: they read as a plan note in `[CVM/CRP]` and as a live rule in
    # `B2C CRP CE 231103`, which is 9,843 of CE's promoted units.
    # No comma in either name: --precedence is a comma-separated list, and a
    # family nobody can name on the command line is one nobody can reorder.
    ('EPP offer',            r'\bEPP\b'),
    ('Plan note (not an offer)',
     r'\bOVERRIDE\b|SHARPEN|\bEXTENDED\b|OFFER CHANGE|DATE CHANGE'
     r'|RETAIL PROMO'),
]


OTHER = '(not one of the named families)'


def families_in(offer: str) -> list:
    """Every family an offer matches, in the table's order."""
    up = re.sub(r'[^A-Z0-9]+', ' ', offer.upper())
    return [name for name, pat in FAMILIES if re.search(pat, up)]


def family_label(kind: str, offer: str, order=None) -> str:
    """The family of a rule, read from its offer **and** its mechanic.

    Pulling the mechanic out of the code is what makes the offer level readable,
    and it is also what can empty it: `BOGO HW LS60D XY AUME 18596` leaves
    `HW LS60D XY`, a bare model code that no family names, and `FREE SHIPPING`
    leaves nothing at all. The mechanic is part of what the offer was, so it is
    put back for this one question.
    """
    if kind and kind.startswith('('):          # '(mechanic not in the code)'
        kind = ''
    return family_of(f'{offer} {kind}'.strip(), order)


def family_of(offer: str, order=None) -> str:
    """The one family a unit is filed under - the first match in `order`.

    This is a **choice**, not a reading. Most of MX's promoted units ran under
    more than one rule, so most match more than one family, and something has
    to decide which the unit counts as. First match wins, and the order is
    therefore the whole of the decision - which is why it is a table at the top
    of this file and a --precedence flag on the command line, rather than
    something buried in the code.
    """
    hits = families_in(offer)
    if not hits:
        return OTHER
    for name in (order or []):
        if name in hits:
            return name
    return hits[0]


def family_label(kind: str, offer: str, order=None) -> str:
    """The family of a rule, read from its offer **and** its mechanic.

    Pulling the mechanic out of the code is what makes the offer level readable,
    and it is also what can empty it: `BOGO HW LS60D XY AUME 18596` leaves
    `HW LS60D XY`, a bare model code that no family names, and `FREE SHIPPING`
    leaves nothing at all. The mechanic is part of what the offer was, so it is
    put back for this one question.
    """
    if kind and kind.startswith('('):          # '(mechanic not in the code)'
        kind = ''
    return family_of(f'{offer} {kind}'.strip(), order)

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
            # Kept apart, not joined into the label: the nationwide campaign is
            # the one level a chart can stack by, and that only works if it can
            # be read on its own.
            'camp': [cell(r, P[k]) if real(cell(r, P[k])) else ''
                     for k in ('promo', 'promo3', 'promo2')],
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
                'type': '', 'detail': '', 'off_by': '', 'miss': 'code',
                'added_back': False,
                'camp': ['', '', ''], 'camp_alts': 0, 'camp_lost': False, 'cands': []}

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
                        'type': '', 'detail': '', 'off_by': best,
                        'miss': 'window', 'added_back': False,
                        'camp': ['', '', ''], 'camp_alts': 0, 'camp_lost': False, 'cands': [],
                        'how': how + f', but the nearest window it fits misses '
                               f'the order date by {best:,} day(s)'}
            if live and best:
                off_by = best
                how += f', in window give or take {best:,} day(s)'
            elif live:
                how += ', in window'
            cands = live + undated

    gap, priced_as, added_back = '', '', ''
    # Two readings of what the line paid: the amount as the export states it,
    # and the amount before the customer handed over a phone or spent points.
    # The plan prices the promotion; a trade-in is a separate transaction that
    # lands in the same amount column, so a Fold8 traded up reads about $1,350
    # against a plan that says $2,579 and the price test throws out a line the
    # plan does cover - inside its window, on the right SKU, at the right price
    # until the trade-in was taken off it.
    tries = [('', order['price'])]
    if order.get('gross') is not None and order['price'] is not None \
            and abs(order['gross'] - order['price']) > 0.01:
        tries.append((' once the trade-in and the points are added back',
                      order['gross']))
    if order['price'] is not None:
        priced = [(c, col, p) for c in cands for col, p in c['prices'].items()]
        if priced:
            # Nearest over both readings at once, so adding the trade-in back
            # can only rescue a line the amount as written would have lost - it
            # never moves a line that already fits onto a different plan row.
            scored = sorted(((abs(p - v), i, c, col, p, note)
                             for i, (c, col, p) in enumerate(priced)
                             for note, v in tries if v is not None),
                            key=lambda t: (t[0], t[1]))
            _, _, best, col, p, note = scored[0]
            gap = round((order['gross'] if note else order['price']) - p, 2)
            off_pct = abs(gap) / abs(p) * 100 if p else 999.0
            if off_pct <= tol or abs(gap) <= 0.01:
                priced_as, added_back = col, bool(note)
                cands = [best] + [c for c in cands if c is not best]
                how += f', paid the {col}{note}'
            else:
                nothing = [c for c in cands if not c['prices']]
                if not nothing:
                    return {'promo': '', 'gap': gap, 'alts': len(cands),
                            'priced': '', 'type': '', 'detail': '',
                            'off_by': off_by, 'miss': 'price',
                            'camp': ['', '', ''], 'camp_alts': 0, 'camp_lost': False, 'cands': [],
                            'off_pct': round(off_pct, 1), 'added_back': False,
                            'how': how + f', but the price paid is {gap:+,.2f} '
                                   f'({off_pct:,.0f}%) from the nearest '
                                   f'({best["promo"]}, {col})'}
                cands, gap = nothing, ''
                how += ', price fits none of the priced lines'

    return {'promo': cands[0]['promo'], 'how': how, 'gap': gap,
            'added_back': added_back,
            'type': cands[0]['type'], 'detail': cands[0]['detail'],
            'priced': priced_as, 'alts': len(cands) - 1, 'off_by': off_by,
            'miss': '', 'camp': cands[0].get('camp', ['', '', '']),
            # How many different answers the lines that fit this order give for
            # the nationwide campaign, counting "none" as one of them: one line
            # saying Black Friday and another saying nothing is as much of a
            # choice as two naming different campaigns. One answer is a fact;
            # more than one is a precedence, and a stack built on a precedence
            # has to say so.
            'camp_alts': len({(c.get('camp') or [''])[0] for c in cands}),
            # And whether the line that won names no campaign while another that
            # fits does: those units are in the residual by the price rule, not
            # because no campaign covered them.
            'camp_lost': not (cands[0].get('camp') or [''])[0]
            and any((c.get('camp') or [''])[0] for c in cands),
            'cands': cands}


# ── describing a file ───────────────────────────────────────────────────────


# Which price column a channel is supposed to pay. The plan quotes a price per
# tier and the order says which portal it came through, so the two can be put
# against each other - and that is a different question from "is the price in
# the plan at all", which is all the nearest-price match answers.
EXPECT = {
    ('S.COM', ''):     {'S.COM_Price'},
    ('EPP', 'EDU'):    {'EDU_Price'},
    ('EPP', ''):       {'T1_Price', 'T2_Price', 'T3_Price'},
}
NO_DISCOUNT = 'RRP'


def expected_tiers(typ: str, typ2: str) -> set:
    """The price columns this channel should be paying, or an empty set.

    Empty means the customer master would not settle the channel, which is not
    the same as a mismatch and is counted apart from one.
    """
    t, t2 = (typ or '').upper(), (typ2 or '').upper()
    if t.startswith('S.COM') or t.startswith('SCOM'):
        return EXPECT[('S.COM', '')]
    if t == 'EPP':
        return EXPECT[('EPP', 'EDU')] if t2 == 'EDU' else EXPECT[('EPP', '')]
    return set()


def rule_price_report(rows: list, tol: float, say=print) -> None:
    """Does the price paid belong to the promotion the rule names?

    The nearest-price match answers a weaker question than it looks like it
    answers: it finds whichever plan line the price fits best, and the rule
    plays no part in choosing it. So a line can "match the plan" at a price that
    belongs to a different offer entirely - the rule says Secret Sale and the
    customer paid the Stunt Promotion price - and the cross-check above would
    still call it a match, because both sides are discounts.

    Both sides now land on one family, so the stronger question can be asked:
    of the plan lines live for this product, is there one of the family the
    *rule* names, and is what was paid that line's price? Three answers, and the
    middle one is the interesting one.
    """
    got = [r for r in rows if r['rule_fam'] and r['cands']]
    if not got:
        return
    same = other = none = 0
    pairs = collections.Counter()
    for r in got:
        mine = [c for c in r['cands']
                if family_label(c.get('type', ''), c.get('detail', ''))
                == r['rule_fam']]
        if not mine:
            none += 1
            pairs[(r['rule_fam'], r['plan_fam'] or '(the plan prices none)')] += 1
            continue
        # Against the price before the trade-in, for the same reason the match
        # uses it: the plan quotes what the promotion sells the phone for, and a
        # traded-up line pays part of that in a phone.
        paid = r.get('paid_plan') or r['paid']
        if paid is None:
            continue
        near = min((abs(paid - v) / v * 100 if v else 999.0
                    for c in mine for v in c['prices'].values()), default=999.0)
        if near <= tol:
            same += 1
        else:
            other += 1
    n = same + other + none
    if not n:
        return
    say(f'\ndoes the price belong to the promotion the rule names? '
        f'{n:,} line(s) with both')
    say(f'  {same:>8,}  {same * 100 / n:>5.1f}%  the plan has a line of that '
        f'family and the price is its price')
    say(f'  {other:>8,}  {other * 100 / n:>5.1f}%  it has one, but what was '
        f'paid is not within {tol:g}% of any of its prices')
    say(f'  {none:>8,}  {none * 100 / n:>5.1f}%  it has no line of that family '
        f'live for this product at all')
    if pairs:
        say('  where the plan prices a different family than the rule ran, '
            'the commonest pairs:')
        say(f'    {"the rule ran":<30}{"the plan prices":<30}{"lines":>8}')
        for (a, b), k in pairs.most_common(8):
            say(f'    {a[:30]:<30}{b[:30]:<30}{k:>8,}')
    say('  the middle row is the one to read: the promotion was planned and the '
        'customer did not\n  pay its price, which the nearest-price match '
        'cannot see because it is looking for\n  any price rather than the '
        'right one')


def tier_report(rows: list, say=print) -> None:
    """Did the customer pay the price their own channel is quoted?

    The plan prices a promotion five times over - S.COM, T1, T2, T3, EDU - and
    the order knows which portal it came through. Matching an order to the
    *nearest* of those five says only that the price is somewhere in the plan;
    it does not say the customer paid the price they were entitled to. An EPP
    order settling on S.COM_Price is either a tier that was not applied or a
    portal group this build has mapped wrongly, and both are worth seeing.

    So this is the one table that puts the two sides together: the channel the
    order came through, against the price column it actually landed on.
    """
    got = [r for r in rows if r['priced']]
    if not got:
        say('\nno line matched a named price column, so the tier cannot be '
            'checked')
        return
    cols = sorted({r['priced'] for r in got},
                  key=lambda c: (c != 'S.COM_Price', c))
    chans = collections.Counter(r['chan'] for r in got)
    say(f'\nthe price paid against the channel it came through - '
        f'{len(got):,} line(s) that landed on a named price')
    head = ''.join(f'{c.replace("_Price", ""):>9}' for c in cols)
    say(f'  {"channel":<22}{"lines":>8}{head}{"as quoted":>12}')
    ok_all = n_all = 0
    for chan, _ in chans.most_common(10):
        mine = [r for r in got if r['chan'] == chan]
        by = collections.Counter(r['priced'] for r in mine)
        want = mine[0]['want']
        ok = sum(n for c, n in by.items() if c in want) if want else 0
        if want:
            ok_all += ok
            n_all += len(mine)
        say(f'  {chan[:22]:<22}{len(mine):>8,}'
            + ''.join(f'{by.get(c, 0):>9,}' for c in cols)
            + (f'{ok * 100 / len(mine):>11.0f}%' if want else f'{"-":>12}'))
    if n_all:
        say(f'  {ok_all * 100 / n_all:.0f}% of the {n_all:,} line(s) whose '
            f'channel the master settles paid a price quoted to\n  that '
            f'channel. A dash means the master would not settle it, which is '
            f'not a mismatch.')
    rrp = sum(1 for r in got if r['priced'] == NO_DISCOUNT)
    if rrp:
        say(f'  {rrp:,} line(s) landed on the RRP - a promotion was live and '
            f'the list price was paid')


# ── one campaign, out of three columns ──────────────────────────────────────
# The plan writes a campaign in three places - Nationwide_Campaign,
# DTC_Campaign1, DTC_Campaign2 - and keeping them as three levels makes two
# thirds of CE's plan lines look campaign-less when most of them are not: they
# are in Samsung Week or Clearance, which the nationwide column never holds.
# So the three are read as one. Nationwide first because it is the widest, then
# the DTC columns; the rest are kept so a line that names two can be seen to.
NO_CAMPAIGN = '(outside every campaign)'
NO_PLAN = '(no plan line fits this order)'


def plan_state(plan, code: str, day):
    """What the plan says about one product on one date.

    Returns (live lines, a nationwide campaign is named, a DTC campaign is
    named). It is the one reading of the plan every band in this repository is
    built on - the P&L page's stack, the profit split, and the ASP sheet - so
    that the three agree about one order instead of each walking the plan its
    own way.

    Read from the product code and the date, never from the price: a trade-in
    or a stacked voucher moves what was collected away from what the plan
    quotes, and a band decided on the price rejects lines the plan does cover.
    """
    cands, _ = plan.candidates(code)
    live = [c for c in cands
            if day is not None
            and (not c['start'] or day >= c['start'])
            and (not c['end'] or day <= c['end'])]
    nat = any((c.get('camp') or [''])[0] for c in live)
    dtc = any(any((c.get('camp') or ['', '', ''])[1:]) for c in live)
    return live, nat, dtc


def campaign_names(live, canon=None, at=1) -> str:
    """The campaigns named in column `at` of the live lines, spelled one way.

    A product in two campaigns at once on the same date keeps both: picking one
    would be inventing a precedence the plan does not state.
    """
    canon = canon or {}
    return ' + '.join(sorted({canon.get(n, n) for c in live
                              if (n := (c.get('camp') or ['', '', ''])[at])}))


def canon_campaigns(rows: list, say=print) -> dict:
    """Fold campaign spellings that differ only by case or punctuation.

    `Father's Day` and `Father's day` are one campaign and came out as two
    bands of a chart. The canonical spelling is the one the plan uses most, read
    off the plan itself rather than from a table here - which also means a
    spelling that becomes the commoner one later is followed without an edit.
    Letter typos are a different thing and are left alone: `Samsung Weel` is not
    `Samsung Week` by any rule that would not also merge two real campaigns.
    """
    seen: dict[str, collections.Counter] = {}
    for r in rows:
        for v in r.get('camp') or []:
            if v:
                seen.setdefault(re.sub(r'[^A-Z0-9]', '', v.upper()),
                                collections.Counter())[v] += 1
    out, folded = {}, []
    for k, c in seen.items():
        best = c.most_common(1)[0][0]
        for v in c:
            out[v] = best
        if len(c) > 1:
            folded.append((best, sorted(x for x in c if x != best)))
    if folded:
        say(f'  {len(folded):,} campaign name(s) are spelled more than one way '
            f'and are read as one:')
        for best, rest in sorted(folded)[:8]:
            say(f'    {best} <- ' + ', '.join(rest))
    return out


def one_campaign(camp, canon: dict) -> str:
    """The campaign a plan line ran in: the first of its three columns to say."""
    for v in camp or []:
        if v:
            return canon.get(v, v)
    return ''


def all_campaigns(camp, canon: dict) -> list:
    """Every campaign it names, in the order the columns are read."""
    out = []
    for v in camp or []:
        if v and canon.get(v, v) not in out:
            out.append(canon.get(v, v))
    return out


PRICE_ORDER = ('S.COM_Price', 'T2_Price', 'T3_Price', 'EDU_Price', 'T1_Price')


def plan_discount(line) -> float | None:
    """What the plan meant to take off the RRP on this line."""
    rrp = (line.get('prices') or {}).get('RRP')
    if not rrp:
        return None
    for col in PRICE_ORDER:
        v = line['prices'].get(col)
        if v:
            return 1 - v / rrp
    return None


def planned_vs_arrived(plan_rows, orders, lo, hi, canon, say=print,
                       what: str = '') -> None:
    """Did the orders come in on what the plan said would run?

    Two sides of one table. The plan side is what was live in the month and on
    how many product codes; the order side is what actually arrived. A campaign
    with plan lines and no orders was planned and did not happen - which no
    chart of the orders alone can show, because a thing that did not happen
    leaves no row to chart. A campaign with orders and no plan lines is the
    other way round and is just as worth seeing.
    """
    live = collections.defaultdict(set)
    lines = collections.Counter()
    where = collections.defaultdict(set)      # which column named it
    span: dict[str, list] = {}                # the window it was planned for
    dcs = collections.defaultdict(list)       # what it meant to take off
    for r in plan_rows:
        if (r['start'] and r['start'] > hi) or (r['end'] and r['end'] < lo):
            continue
        names = all_campaigns(r.get('camp'), canon)
        for i, v in enumerate(r.get('camp') or []):
            if v:
                where[canon.get(v, v)].add(('nationwide', 'DTC1', 'DTC2')[i])
        for name in names or [NO_CAMPAIGN]:
            live[name].add(r['code'])
            lines[name] += 1
            if r['start'] or r['end']:
                a, b = r['start'] or lo, r['end'] or hi
                cur = span.setdefault(name, [a, b])
                cur[0], cur[1] = min(cur[0], a), max(cur[1], b)
            d = plan_discount(r)
            if d is not None:
                dcs[name].append(d)
    got = collections.Counter()
    units = collections.Counter()
    amt = collections.Counter()
    inside = collections.Counter()
    paid_n = collections.Counter()
    paid_d = collections.Counter()
    for o in orders:
        # The order side keeps its campaign as a one-element list, because the
        # chart rows want it that way; here it is one name.
        name = o['camp'][0] or (NO_CAMPAIGN if o['fitted'] else NO_PLAN)
        got[name] += 1
        units[name] += o['qty']
        amt[name] += o['amt']
        if o.get('rule_out'):
            inside[name] += o['qty']
        # Before the trade-in, like everything else that compares a price to
        # the plan: a campaign does not get credit for the phone the customer
        # handed over, and a "paid DC" that counts it reads 23% where the
        # promotion gave 4%.
        was_paid = o.get('paid_plan') or o.get('paid')
        if was_paid and o.get('rrp'):
            paid_n[name] += o['qty'] * (1 - was_paid / o['rrp'])
            paid_d[name] += o['qty']

    names = set(live) | set(got)
    names -= {NO_CAMPAIGN, NO_PLAN}      # these two are the rows below, not campaigns
    rows = sorted(names, key=lambda n: (-amt.get(n, 0), -lines.get(n, 0), n))
    def mid(xs):
        xs = sorted(xs)
        n2 = len(xs)
        return None if not n2 else (xs[n2 // 2] if n2 % 2
                                    else (xs[n2 // 2 - 1] + xs[n2 // 2]) / 2)

    say(f'\nwhat the plan said would run in this month, and how it was applied'
        + (f' - {what} only' if what else ''))
    def row(name, named, skus, pl, u, rev, late, pd_, rd):
        say(f'  {name[:28]:<28}{named[:11]:<12}{skus:>6}{pl:>7}'
            f'{u:>9,.0f}{rev:>13,.0f}'
            + (f'{late:>8.0f}%' if late is not None else f'{"-":>9}')
            + (f'{pd_ * 100:>8.0f}%' if pd_ is not None else f'{"-":>9}')
            + (f'{rd * 100:>8.0f}%' if rd is not None else f'{"-":>9}'))

    say(f'  {"campaign":<28}{"named by":<12}{"SKUs":>6}{"lines":>7}'
        f'{"units":>9}{"revenue":>13}{"late":>9}{"plan DC":>9}{"paid DC":>9}')
    for n in rows:
        u = units.get(n, 0)
        rd = paid_n[n] / paid_d[n] if paid_d.get(n) else None
        row(n, '+'.join(sorted(where.get(n, ()))), f'{len(live.get(n, ())):,}',
            f'{lines.get(n, 0):,}', u, amt.get(n, 0),
            (inside[n] / u * 100) if u else None, mid(dcs.get(n, [])), rd)
    for n, label in ((NO_CAMPAIGN, 'outside every campaign'),
                     (NO_PLAN, 'no plan line fits the order')):
        if got.get(n):
            rd = paid_n[n] / paid_d[n] if paid_d.get(n) else None
            row(label, '-', '-', '-', units[n], amt[n],
                (inside[n] / units[n] * 100) if units[n] else None, None, rd)
    say('  "late" is the share of that campaign\'s units whose own rule names '
        'a window the order\n  date sits outside - the engine still applying a '
        'promotion that had ended, or applying\n  one early. It needs no plan '
        'to spot: the rule carries its own dates.')
    say('  "plan DC" is what the plan meant to take off the RRP, "paid DC" what '
        'came off. Both\n  are consumer prices, so the two are comparable as '
        'written; a paid DC far under the\n  plan DC is a campaign whose '
        'discount mostly did not reach the customer.')
    dark = [n for n in rows if lines.get(n) and not got.get(n)]
    new = [n for n in rows if got.get(n) and not lines.get(n)]
    if dark:
        say(f'  {len(dark):,} campaign(s) were planned and nothing arrived on '
            f'them: ' + ', '.join(dark[:6])
            + (f' and {len(dark) - 6:,} more' if len(dark) > 6 else ''))
    if new:
        say(f'  {len(new):,} campaign(s) took orders with no plan line live '
            f'this month: ' + ', '.join(new[:6]))
    say('  a campaign with plan lines and no orders cannot appear in any chart '
        'of the orders\n  alone - it left no row to chart - which is the whole '
        'reason for the left two columns')


# What a rule claims it takes off, read out of its own text. `50PCT` and
# `50-PERCENT` are a rate; `120OFF` and `$120-OFF` are an amount.
CLAIM_PCT = re.compile(r'(\d{1,2})\s*-?\s*(?:PCT|PERCENT)\b')
CLAIM_OFF = re.compile(r'(\d{2,4})\s*-?\s*OFF\b')


def claims_of(text: str) -> list:
    """Every discount a rule's text claims, as ('pct', 0.3) or ('off', 120)."""
    up = re.sub(r'[^A-Z0-9]+', ' ', str(text).upper())
    return ([('pct', int(m) / 100) for m in CLAIM_PCT.findall(up)]
            + [('off', float(m)) for m in CLAIM_OFF.findall(up)])


def rules_on_line(rules: list, rrp, paid, own_dc, tol: float = 0.01) -> tuple:
    """Which of a cell's rules actually ran on **this** line.

    One cell carries every rule the order qualified for, and an order is more
    than one line. A Fold8 bought with a case comes back on both lines with the
    same pair - the accessories PWP and the eco voucher - but the phone got the
    voucher and the case got the thirty percent, and reading the two together
    files the phone under "Accessories offer", which is simply not what happened
    to it.

    The line's own numbers settle it: a rule claiming 30% fits a line that lost
    30%, a rule claiming $120 fits a line that lost $120, and a rule claiming
    neither cannot be told apart and is kept. Only where the claims disagree
    with each other is anything dropped - with one rule, or with no numbers to
    test against, nothing changes.
    """
    if len(rules) < 2 or own_dc is None:
        return rules, False
    off = (rrp - paid) if (rrp and paid is not None) else None
    keep, judged = [], False
    for d in rules:
        cl = claims_of(d['what'])
        if not cl:
            keep.append(d)                 # claims nothing, so it cannot miss
            continue
        fits = False
        for kind, v in cl:
            if kind == 'pct' and abs(own_dc - v) <= tol:
                fits = True
            if kind == 'off' and off is not None and abs(off - v) <= 1.0:
                fits = True
        judged = True
        if fits:
            keep.append(d)
    # Only narrow where something was judged and something survived: a line
    # whose every rule misses is a line this test cannot explain, and dropping
    # them all would turn it into "no promotion", which is worse than the
    # over-wide reading it replaced.
    if judged and keep and len(keep) < len(rules):
        return keep, True
    return rules, False


def suggest_price_columns(head, body, amount_i, qty_i, say=print) -> None:
    """Which columns behave like a list price or a discount rate.

    The names vary and guessing more of them is a losing game, so where neither
    is recognised the file is asked instead: a column that is numeric and sits
    consistently above what was paid behaves like a list price, and one whose
    values all fall between zero and one behaves like a rate. Named here, they
    can be passed with --order-rrp and --order-disc, and the run is exact rather
    than approximately right.
    """
    rows = body[:4000]
    paid, rate, above = [], [], []
    for i, h in enumerate(head):
        if not h or i in (amount_i, qty_i):
            continue
        vals, over, n = [], 0, 0
        for r in rows:
            v = parse_number(r[i] if i < len(r) else '')
            if v is None:
                continue
            a = parse_number(r[amount_i] if amount_i is not None
                             and amount_i < len(r) else '')
            q = parse_number(r[qty_i] if qty_i is not None
                             and qty_i < len(r) else '') or 1.0
            vals.append(v)
            if a is not None and q:
                n += 1
                over += v >= a / q
        if len(vals) < 20:
            continue
        # Zeros are ordinary - a line given away has no price and a line at
        # list has no discount - so they are allowed on both tests. Requiring
        # every value to be positive was enough on its own to find nothing in
        # an export that plainly carries both columns.
        if n and over >= n * 0.95 and any(v > 0 for v in vals):
            above.append((h, len(vals)))
        if min(vals) >= 0 and max(vals) <= 1 and len(set(vals)) > 5:
            rate.append((h, len(vals)))
    if above:
        say('  columns that behave like a list price (always at or above what '
            'a unit was paid):\n    ' + ', '.join(h for h, _ in above[:8]))
    if rate:
        say('  columns that behave like a rate (every value between 0 and 1):'
            '\n    ' + ', '.join(h for h, _ in rate[:8]))
    if above or rate:
        say('  pass one with --order-rrp and --order-disc and the discount is '
            'read off the order\n  itself, which is the only discount a '
            'product the plan does not list can have')
    else:
        say('  nothing in this export behaves like a list price or a rate, so '
            'a discount can only\n  come from the plan - and not at all for a '
            'product the plan does not list')


def own_discount(disc, rrp, amount, qty, basis=1.0):
    """The discount the order line states about itself, or None.

    A rate column is a rate - 0.3 is thirty percent, 30 is thirty percent - and
    where there is none, the list price divided into what was paid says the
    same thing. Both come off the order export, so this is the one discount
    that exists for a product the plan has never heard of.
    """
    d = parse_number(disc)
    if d is not None and 0 < d < 1:
        return d
    if d is not None and 1 <= d <= 99:
        return d / 100
    r, a = parse_number(rrp), amount
    if r and a is not None and qty:
        # The basis is a property of the file, not of a row - the export quotes
        # the line ex GST and the list price with it, or both the same way - so
        # it is settled once, by gst_basis below, and passed in. Deciding it per
        # row picks whichever reading happens to look plausible and gets a
        # different answer on the next row.
        got = 1 - (a / qty * basis) / r
        if -0.05 <= got <= 0.95:
            return got
    return None


def gst_basis(rows, say=print) -> float:
    """Whether the export's list price and its amount are on one basis.

    Settled against the export's own discount rate where it has one: the basis
    that reproduces the stated rate is the right basis, and that is a fact about
    the file rather than a guess. With no rate column there is nothing to settle
    it against, so the two are taken as written and that is said out loud.
    """
    err = {1.0: [], 1.1: []}
    for d, r, a, q in rows:
        rate = parse_number(d)
        rate = rate / 100 if rate is not None and 1 <= rate <= 99 else rate
        rr, amt = parse_number(r), a
        if rate is None or not (0 < rate < 1) or not rr or amt is None or not q:
            continue
        for b in err:
            err[b].append(abs((1 - (amt / q * b) / rr) - rate))
    if not err[1.0]:
        say('  the export states no discount rate, so its list price and its '
            'amount are taken\n  as written - if one includes GST and the '
            'other does not, every discount below is\n  out by a ninth')
        return 1.0
    mids = {b: sorted(v)[len(v) // 2] for b, v in err.items()}
    best = min(mids, key=mids.get)
    say(f'  list price against amount: {len(err[1.0]):,} row(s) state a rate '
        f'as well, and the two agree\n  within {mids[best] * 100:.1f}pp when '
        f'the amount is multiplied by {best:g}'
        + (f' (and {mids[1.1 if best == 1.0 else 1.0] * 100:.0f}pp when it is '
           f'not), so that is the basis' if len(mids) > 1 else ''))
    return best


def own_discount_report(rows: list, say=print) -> None:
    """What came off, by promotion, without asking the plan anything.

    The plan cannot price what it does not list, and what it does not list is
    mostly accessories - which is where a launch's promotion often sits. A
    Fold8 bought at its list price with a case at 30% off is a promoted sale,
    and every discount in it is on the case's line: a different product code, a
    different category, and no plan row at all.
    """
    got = [r for r in rows if r.get('own_dc') is not None]
    if not got:
        return
    tot = sum(r['qty'] for r in rows) or 1.0
    mine = sum(r['qty'] for r in got)
    say(f'\nwhat came off, as the order export states it - no plan involved')
    say(f'  {mine:,.0f} of {tot:,.0f} unit(s) ({mine / tot * 100:.0f}%) carry '
        f'enough to work out their own discount')
    by_n = collections.Counter()
    by_d = collections.Counter()
    for r in got:
        by_n[r['fam']] += r['qty'] * r['own_dc']
        by_d[r['fam']] += r['qty']
    say(f'  {"promotion":<34}{"units":>10}{"discount":>10}')
    for fam, q in by_d.most_common(14):
        say(f'  {fam[:34]:<34}{q:>10,.0f}{by_n[fam] / q * 100:>9.0f}%')
    nil = sum(r['qty'] for r in got if r['own_dc'] < 0.005)
    say(f'  {nil:,.0f} unit(s) ({nil / mine * 100:.0f}%) came off at nothing - '
        f'the list price was paid.')

def unnamed_discount_report(rows: list, say=print) -> None:
    """Lines where money came off and nothing said what for.

    This is the only honest answer to "did it catch all of this": a discount
    the export states is a fact, and whether anything named it is a separate
    fact. Four outcomes, and they are not degrees of the same thing - a rule
    was read, a rule was there but unreadable, no rule was recorded at all,
    or the discount is a trade-in and was never a price cut.
    """
    got = [r for r in rows if (r.get('own_dc') or 0) >= 0.005]
    if not got:
        return
    say('\nlines where a discount came off - was anything able to name it')
    buckets = {'named': [], 'rule not read': [], 'no rule recorded': [],
               'trade-in, not a price cut': []}
    for r in got:
        if r.get('how') in ('rule', 'voucher', 'plan'):
            buckets['named'].append(r)
        elif (r.get('trade') or 0) > 0 and not (r.get('rule_raw') or '').strip():
            buckets['trade-in, not a price cut'].append(r)
        elif (r.get('rule_raw') or '').strip():
            buckets['rule not read'].append(r)
        else:
            buckets['no rule recorded'].append(r)
    tot = sum(r['qty'] for r in got) or 1.0
    say(f'  {"":<28}{"units":>9}{"revenue":>14}{"discount":>10}')
    for name, rs in buckets.items():
        if not rs:
            continue
        q = sum(r['qty'] for r in rs)
        amt = sum(r.get('amt_line') or 0.0 for r in rs)
        dc = sum(r['qty'] * r['own_dc'] for r in rs) / (q or 1)
        say(f'  {name:<28}{q:>9,.0f}{amt:>14,.0f}{dc * 100:>9.0f}%'
            f'   {q / tot * 100:>3.0f}% of discounted units')
    # The two residuals are where the work is, so each gets real rows rather
    # than a number: a code to look up, and what the cell did or did not hold.
    for name in ('no rule recorded', 'rule not read'):
        rs = sorted(buckets[name], key=lambda r: -(r.get('amt_line') or 0.0))
        for r in rs[:3]:
            say(f'    {name}: {r["sku"]} {r["day"]} {r["qty"]:,.0f} unit(s) '
                f'-{r["own_dc"] * 100:.0f}% order {r.get("order") or "?"}'
                + (f' rule {(r.get("rule_raw") or "")[:52]}' if name ==
                   'rule not read' else ''))
    both = [r for r in rows if r.get('cust_dc') is not None
            and r.get('own_dc') is not None]
    apart = [r for r in both if abs(r['cust_dc'] - r['own_dc']) >= 0.005]
    if apart:
        q = sum(r['qty'] for r in apart)
        say(f'  {q:,.0f} unit(s) state two different discounts - the customer '
            f'one averages\n  '
            f'{sum(r["qty"] * r["cust_dc"] for r in apart) / q * 100:.0f}% and '
            f'the net one '
            f'{sum(r["qty"] * r["own_dc"] for r in apart) / q * 100:.0f}%. '
            f'The gap is the trade-in and the points\n  redeemed, which the '
            f'customer gave something for. Net is read here.')


# Its own residual label: this mode asks only about the two DTC columns, so a
# line that lands nowhere is outside every DTC campaign - which is not the same
# statement as the long match's "outside every campaign".
NO_DTC = '(no DTC campaign covers it)'
# A plan line can name the first DTC campaign and leave the second blank. That
# is the plan saying there was no second one, not a line that failed to match,
# so it reads differently from the residual above.
NO_SECOND = '(no second DTC campaign)'


def dtc_only(plan, plan_rows, o_body, O, canon, args, cell, say=print):
    """Which DTC campaign an order came in on, from the code and the date alone.

    The long match asks four questions - code, window, price, mechanic - and the
    price is the one that rejects lines the plan does in fact cover: a trade-in,
    a stacked voucher or a bundle all move what was collected away from the
    price the plan quotes. This asks two. A DTC campaign named a set of products
    and a set of dates; an order for one of those products on one of those dates
    came in on it. Nothing about the money is read.

    The two DTC columns are kept apart rather than merged. They are a hierarchy
    in the plan - the first names the campaign, the second what ran inside it -
    so the page opens on the first and the second is what a bar opens into.
    Merging them made a row called `A + B`, which is neither campaign.
    """
    windows: dict[str, list] = {}
    for r in plan_rows:
        c1, c2 = [canon.get(v, v) for v in (r.get('camp') or ['', '', ''])[1:]]
        if not c1 and not c2:
            continue
        windows.setdefault(r['code'], []).append(
            (c1, c2, r['start'], r['end'],
             # What the plan called the offer. This is where FF8 Pre-Order is
             # written, and it is the label the page is read for - a campaign
             # total with no offer under it answers nothing.
             r['detail'] or '(the plan names no offer)',
             r['type'] or '(the plan names no mechanic)'))
    # Spans and SKU counts per level, so each table says what its own column
    # planned rather than borrowing the other's.
    span: dict[tuple, list] = {}
    skus: dict[tuple, set] = collections.defaultdict(set)
    for code, hits in windows.items():
        for c1, c2, lo, hi, _d, _t in hits:
            for lv, name in ((1, c1), (2, c2)):
                if not name:
                    continue
                skus[(lv, name)].add(code)
                was = span.setdefault((lv, name), [lo, hi])
                if lo and (was[0] is None or lo < was[0]):
                    was[0] = lo
                if hi and (was[1] is None or hi > was[1]):
                    was[1] = hi

    agg = {1: [collections.Counter(), collections.Counter(),
               collections.Counter()],
           2: [collections.Counter(), collections.Counter(),
               collections.Counter()]}
    two = []                      # inside more than one campaign 1 at once
    undated = 0                   # a DTC line with no window - covers nothing
    out, page = [], []
    miss = {'code': 0, 'date': 0, 'no dtc': 0}
    for r in o_body:
        if not args.keep_cancelled and cell(r, O['cancel']).lower() in (
                'yes', 'y', 'true'):
            continue
        code = code_norm(cell(r, O['sku']))
        if args.only and code_norm(args.only) not in code:
            continue
        qty = parse_number(cell(r, O['qty'])) or 0.0
        amount = parse_number(cell(r, O['amount'])) or 0.0
        day = to_date(cell(r, O['date']))
        cands, _how = plan.candidates(code)
        live = []
        if not cands:
            miss['code'] += 1
        else:
            mine = [w for c in cands for w in windows.get(c['code'], [])]
            if not mine:
                miss['no dtc'] += 1
            live = [w for w in mine
                    if day is not None
                    and (w[2] is None or day >= w[2])
                    and (w[3] is None or day <= w[3])]
            undated += sum(1 for w in mine if w[2] is None and w[3] is None)
            if mine and not live:
                miss['date'] += 1
        c1s = sorted({w[0] for w in live if w[0]})
        c2s = sorted({w[1] for w in live if w[1]})
        offers = sorted({w[4] for w in live})
        mechanics = sorted({w[5] for w in live})
        name1 = ' + '.join(c1s) if c1s else (NO_SECOND if live else NO_DTC)
        name2 = ' + '.join(c2s) if c2s else (NO_SECOND if live else NO_DTC)
        if len(c1s) > 1:
            two.append((cell(r, O['sku']), day, c1s))
        for lv, name in ((1, name1), (2, name2)):
            agg[lv][0][name] += qty
            agg[lv][1][name] += amount
            agg[lv][2][name] += 1
        out.append([cell(r, O['order']), cell(r, O['sku']),
                    day.isoformat() if day else '', qty, amount,
                    name1, name2, ' + '.join(offers)])
        page.append(('plan' if live else 'none',
                     cell(r, O['group']) or '(blank)',
                     cell(r, O['portal']) or '(blank)',
                     name1, name2,
                     ' + '.join(offers) or NO_DTC,
                     ' + '.join(mechanics) or NO_DTC,
                     cell(r, O['cat']) or '(blank)',
                     day.isoformat() if day else '', qty, amount))

    def table(lv, title):
        units, amt, lines = agg[lv]
        tot = sum(units.values()) or 1.0
        say(f'\n{title}')
        say(f'  {"campaign":<34}{"period":<25}{"SKUs":>6}{"lines":>9}'
            f'{"units":>10}{"revenue":>14}{"share":>8}')
        for n, q in units.most_common(15):
            lo, hi = span.get((lv, n), [None, None])
            when = (f'{lo.strftime("%d %b") if lo else "-"} to '
                    f'{hi.strftime("%d %b %Y") if hi else "-"}') \
                if (lv, n) in span else ''
            # A residual is not a campaign and has no plan lines of its own, so
            # it shows a dash rather than a zero that reads like "planned
            # nothing".
            own = (f'{len(skus[(lv, n)]):>6}' if (lv, n) in skus
                   else f'{"-":>6}')
            say(f'  {n[:34]:<34}{when[:25]:<25}{own}'
                f'{lines[n]:>9,}{q:>10,.0f}{amt[n]:>14,.0f}'
                f'{q / tot * 100:>7.1f}%')
        quiet = [n for (l, n) in skus
                 if l == lv and not units.get(n)
                 and not any(n in got for _, _, got in two)]
        if quiet:
            say(f'  {len(quiet):,} have plan lines and no orders: '
                + ', '.join(sorted(quiet)[:6]))

    say(f'\nwhich DTC campaign the order came in on - product code and date '
        f'only, no price')
    table(1, 'DTC campaign 1 - the top level, and where the page opens')
    table(2, 'DTC campaign 2 - what a campaign 1 bar opens into')
    if two:
        say(f'\n  {len(two):,} line(s) sit inside more than one campaign 1 at '
            f'once and are left under\n  the pair, not split between them - '
            f'the price was what used to tell them apart:')
        for sku, day, got in two[:5]:
            say(f'    {sku:<22}{day.isoformat() if day else "":<12}'
                + ' + '.join(got)[:50])
    if undated:
        say(f'  {undated:,} DTC plan line(s) carry no window at all, so no date '
            f'can fall inside them')
    say(f'  of what did not land: {miss["code"]:,} line(s) the plan has no '
        f'product code for, {miss["no dtc"]:,}\n  on a product the plan lists '
        f'under no DTC campaign, {miss["date"]:,} on a date outside every DTC\n'
        f'  window the product is in')
    # The offer, which is what the page is actually opened to read: a campaign
    # total with nothing under it does not answer "did FF8 Pre-Order happen".
    say(f'\n  {"offer the plan names":<40}{"lines":>9}{"units":>10}'
        f'{"revenue":>14}')
    by_offer = collections.Counter()
    off_amt = collections.Counter()
    off_lines = collections.Counter()
    for row in page:
        by_offer[row[5]] += row[9]
        off_amt[row[5]] += row[10]
        off_lines[row[5]] += 1
    for o, q in by_offer.most_common(12):
        say(f'  {o[:40]:<40}{off_lines[o]:>9,}{q:>10,.0f}{off_amt[o]:>14,.0f}')
    reasons = [('the plan has no line for this product', miss['code']),
               ('the plan lists it under no DTC campaign', miss['no dtc']),
               ('the date is outside every DTC window it is in', miss['date'])]
    return out, page, [(w, n) for w, n in reasons if n]


def campaign_fit(rows: list) -> dict:
    """The numbers that say whether a campaign stack is a measurement.

    The same three the console block prints, kept as data so the page can carry
    them: a stacked bar that divides revenue by something which does not divide
    it has to say so where it is being read, not only where it was built.
    """
    tot = sum(r['qty'] for r in rows) or 1.0
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        nat = (r['camp'][0] or (NO_CAMPAIGN if r['fitted'] else NO_PLAN))
        per[(r['group'], code_norm(r['sku']))][nat] += r['qty']
    pure = n = 0
    share = 0.0
    for c in per.values():
        t = sum(c.values())
        if t <= 0:
            continue
        n += 1
        share += max(c.values()) / t
        pure += 1 if len(c) == 1 else 0
    return {
        'units': round(tot),
        'split': round(sum(r['qty'] for r in rows if r['camp_alts'] > 1) * 100
                       / tot, 1),
        'lost': round(sum(r['qty'] for r in rows if r['camp_lost']) * 100
                      / tot, 1),
        'rows': n,
        'pure': round(pure * 100 / n) if n else 0,
        'biggest': round(share * 100 / n) if n else 0,
    }


def campaign_report(rows: list, say=print) -> None:
    """Can a chart stack by campaign, and what is the rest of it made of?

    The campaign and the mechanic are not two ways of saying one thing, and that
    is what makes this worth a block of its own. A promotion's **mechanic** comes
    off the store's rule - the engine applied it, and an order can have several
    at once, which is why a mechanic cannot divide revenue. A promotion's
    **campaign** comes off the plan, and the plan gives a product one nationwide
    campaign at a time. One axis is a partition and the other is not, and they
    answer different questions: "why did this sell" and "what was done to the
    price".

    So this reports three things, in the order they have to be decided:

      1. whether the nationwide campaign really is one per order - measured, by
         counting the orders whose fitting plan lines name more than one
      2. the stack it would make, with its two residuals kept apart: an order in
         no nationwide campaign is not the same as an order no plan line fits
      3. what the biggest residual is **made of** - its DTC campaigns, and then
         the mechanics underneath - because a band holding half the revenue and
         called "none" is not an answer, it is a place to look
    """
    tot_q = sum(r['qty'] for r in rows) or 1.0
    say(f'\ncampaign, from the plan - the one level that can divide revenue')
    split = sum(r['qty'] for r in rows if r['camp_alts'] > 1)
    say(f'  {split:,.0f} of {tot_q:,.0f} unit(s) ({split / tot_q * 100:.1f}%) sit '
        f'on an order whose fitting plan lines give more than one answer for '
        f'the\n  nationwide campaign - counting "none" as an answer - so that '
        f'much of the split below is\n  a precedence rather than a reading')
    lost = sum(r['qty'] for r in rows if r['camp_lost'])
    if lost:
        say(f'  {lost:,.0f} unit(s) ({lost / tot_q * 100:.1f}%) took their '
            f'campaign from a plan line other than the one\n  the price picked '
            f'- the nearest line that names one. Without that they would be in '
            f'the\n  residual, which is a tie-break and not a reading')
    # What is actually left, now that a tie-break cannot be the reason.
    out = [r for r in rows if not r['camp'][0] and r['fitted']]
    if out:
        oq = sum(r['qty'] for r in out)
        say(f'\n  {oq:,.0f} unit(s) ({oq / tot_q * 100:.0f}%) matched a plan '
            f'line and **no** line that fits them names a\n  campaign in any '
            f'of the three columns. That is the plan saying nothing, not the '
            f'match\n  failing. Where they sit:')
        by = collections.Counter()
        for r in out:
            by[r.get('div') or '(blank)'] += r['qty']
        n = sum(by.values()) or 1
        for k, v in by.most_common(8):
            say(f'    {k[:30]:<30}{v:>10,.0f}{v / n * 100:>7.1f}%')

    def table(key, title, pool, note=''):
        t = collections.Counter()
        amt = collections.Counter()
        for r in pool:
            t[key(r)] += r['qty']
            amt[key(r)] += r['amt']
        n = sum(t.values()) or 1.0
        say(f'\n  {title}')
        for k, v in t.most_common(14):
            say(f'    {k[:46]:<46}{v:>10,.0f}{v / n * 100:>6.1f}%'
                f'{amt[k]:>14,.0f}')
        if len(t) > 14:
            rest = n - sum(v for _, v in t.most_common(14))
            say(f'    {f"and {len(t) - 14:,} more":<46}{rest:>10,.0f}'
                f'{rest / n * 100:>6.1f}%')
        if note:
            say(f'  {note}')
        return t

    def nat(r):
        if r['camp'][0]:
            return r['camp'][0]
        return NO_CAMPAIGN if r['fitted'] else NO_PLAN

    table(nat, 'by nationwide campaign  (units, share, amount)', rows)

    # The residual, opened up. This is the "what is it a mixture of" question,
    # and it is asked of the band that holds the most, not of all of them.
    rest = [r for r in rows if not r['camp'][0] and r['fitted']]
    if rest:
        rq = sum(r['qty'] for r in rest)
        say(f'\n  inside {NO_CAMPAIGN} - {rq:,.0f} unit(s), '
            f'{rq / tot_q * 100:.0f}% of everything. These are plan lines that '
            f'name no campaign in\n  any of the three columns, so there is '
            f'nothing campaign-shaped left to open them by:')
        table(lambda r: r['type'], 'by what was done to the price', rest,
              note='this cannot be stacked - an order can be in several at '
                   'once - but it says what\n  the band is a mixture of, which '
                   'is what a legend entry called "none" owes the\n  reader')

    # And the same concentration test the levels get, for the campaign: a profit
    # row can only carry a campaign by being shared out over its orders'.
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        per[(r['group'], code_norm(r['sku']))][nat(r)] += r['qty']
    pure = n = 0
    share = 0.0
    for c in per.values():
        t = sum(c.values())
        if t <= 0:
            continue
        n += 1
        share += max(c.values()) / t
        pure += 1 if len(c) == 1 else 0
    if n:
        say(f'\n  whether a profit row can carry a campaign: {n:,} row(s), '
            f'{pure / n * 100:.0f}% sit on one,\n  the biggest holds '
            f'{share / n * 100:.0f}% on average. A row is one portal group and '
            f'one product code.')


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
                    help='also write a page to look at it in (default '
                         'dashboard/promo_<the month the orders fall in>.html)')
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
    ap.add_argument('--only', metavar='CODE',
                    help='one product only, by any part of its code - '
                         '--only SM-F9 for the Fold. Everything is then about '
                         'that product: its orders, the rules they came in on, '
                         'and every plan line the plan has for it')
    ap.add_argument('--precedence', metavar='LIST',
                    help='which family a line counts as where it matches '
                         'several, highest first, comma separated. The default '
                         'is the order of the FAMILIES table in this file')
    ap.add_argument('--dtc-only', action='store_true',
                    help='the simple read: which DTC campaign an order came in '
                         'on, from the product code and the order date alone. '
                         'No price, no mechanic, no nationwide campaign')
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
                       ('order-voucher', 'voucher the customer used'),
                       ('order-rrp', 'the list price the order states'),
                       ('order-disc', 'the discount rate the order states')):
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
        'rrp': choose(o_head, o_body, 'rrp', args.order_rrp),
        'disc': choose(o_head, o_body, 'disc', args.order_disc),
        # The gross discount and what makes it gross. Neither is used to price
        # anything; they are there so a discount that is really a trade-in can
        # be told apart from one the promotion gave.
        'disc_all': choose(o_head, o_body, 'disc_all', None),
        'trade': choose(o_head, o_body, 'trade', None),
        'points': choose(o_head, o_body, 'points', None),
    }
    # Both discount columns found and the same column chosen for each means the
    # export has only one of them; nothing to tell apart then.
    if O['disc_all'] == O['disc']:
        O['disc_all'] = None

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
                 (op.name, 'portal', O['portal'], o_head, ''),
                 (op.name, 'list price', O['rrp'], o_head, ''),
                 (op.name, 'discount', O['disc'], o_head, '--order-disc'),
                 (op.name, 'gross discount', O['disc_all'], o_head, ''),
                 (op.name, 'trade-in value', O['trade'], o_head, ''),
                 (op.name, 'points redeemed', O['points'], o_head, '')]
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
    canon = canon_campaigns(plan_rows)
    if args.dtc_only:
        rows, dtc_page, why = dtc_only(plan, plan_rows, o_body, O, canon,
                                       args, cell)
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        yymm, _ = months_in([r[2] for r in rows if r[2]])
        path = outdir / f'promo_dtc{("_" + yymm) if yymm else ""}.csv'
        with path.open('w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['order', 'sku', 'date', 'units', 'amount',
                        'dtc campaign 1', 'dtc campaign 2', 'offer'])
            w.writerows(rows)
        print(f'\n-> {path}')
        if args.html is not None:
            # The page is how this is read, so the simple mode builds one too -
            # a shorter drill, because it infers no channel and reads no price,
            # and a different file name, because it is a different answer about
            # the same month and must not overwrite the long match's page.
            hp = (Path(args.html) if args.html else ROOT / 'dashboard' /
                  f'promo_dtc_{yymm or "nodate"}.html')
            write_page(hp, args, ' + '.join(f['path'].name for f in plans),
                       op, dtc_page, why, 0,
                       # Campaign 1 first and campaign 2 directly under it:
                       # the page opens on campaign 1, and the template drills
                       # to the next level down, so clicking a bar opens it by
                       # campaign 2 with nothing in between.
                       levels=['Portal Group', 'Portal', 'DTC Campaign 1',
                               'DTC Campaign 2', 'Offer', 'Mechanic',
                               'Product Category'],
                       cust_depth=2, start='DTC Campaign 1',
                       campaign='DTC Campaign 1',
                       source_labels=[
                           ['plan', 'the plan: this product, on this date',
                            'On a DTC campaign'],
                           ['none', 'no DTC campaign covers it',
                            'On none']])
        return 0
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
    added_back_n = 0
    source = {'rule': 0, 'voucher': 0, 'plan': 0, 'none': 0}
    camp_rows, tier_rows = [], []
    only = code_norm(args.only) if args.only else ''
    # One pass over the export to settle how its own prices are quoted, before
    # a single discount is read off them.
    basis = 1.0
    if O['rrp'] is None:
        print('\nthe order export states no list price this build recognises:')
        suggest_price_columns(o_head, o_body, O['amount'], O['qty'])
    if O['rrp'] is not None:
        print('\nthe order export prices itself:')
        basis = gst_basis([(cell(r, O['disc']), cell(r, O['rrp']),
                            parse_number(cell(r, O['amount'])),
                            parse_number(cell(r, O['qty'])) or 0.0)
                           for r in o_body])
    only_orders: set = set()
    narrowed_n = 0
    order_of = [x.strip() for x in (args.precedence or '').split(',') if x.strip()]
    bad = [x for x in order_of if x not in {n for n, _ in FAMILIES}]
    if bad:
        print(f'--precedence names no such family: {", ".join(bad)}',
              file=sys.stderr)
        return 2
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

        def consumer(v):
            """An export amount as a price one unit was sold at."""
            if v is None:
                return None
            per = v / qty if args.amount_is == 'line' and qty else v
            return per * (1 + args.gst / 100)

        paid = consumer(amount)
        # What the line would have cost without the trade-in and the points -
        # both stated by the export, both on the same basis as the amount, and
        # both subtractions the customer gave something for rather than
        # discounts the promotion gave.
        extra = sum(v for v in (parse_number(cell(r, O['trade']))
                                if O['trade'] is not None else None,
                                parse_number(cell(r, O['points']))
                                if O['points'] is not None else None) if v)
        gross = consumer(amount + extra) if amount is not None and extra else None
        if only and only not in code_norm(cell(r, O['sku'])):
            continue
        if only:
            only_orders.add(cell(r, O['order']))
        order = {'code': code_norm(cell(r, O['sku'])),
                 'date': to_date(cell(r, O['date'])), 'price': paid,
                 'gross': gross}

        rules = [parse_rule(t) for t in split_rules(cell(r, O['rule']))]
        own_dc = own_discount(cell(r, O['disc']), cell(r, O['rrp']),
                              amount, qty, basis)
        rules, narrowed = rules_on_line(
            rules, parse_number(cell(r, O['rrp'])),
            (amount / qty * basis) if (amount is not None and qty) else None,
            own_dc)
        narrowed_n += bool(narrowed)
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
        # One promotion, named once. The rule and the plan were shown to be two
        # descriptions of the same offer - 92% of the lines both answered for -
        # so keying the summary on which of them answered printed that offer
        # twice, once under its rule code and once under its plan label, as if
        # they were two promotions. They are not. The identity is the campaign
        # it ran in and the family it was; which source could name it is an
        # attribute of the row, not part of what the row is.
        fam = family_label(o_type, o_detail, order_of)
        # The campaign and the mechanic are two axes, so they need not come off
        # the same plan line. The mechanic has to: it is what the price bought.
        # The campaign does not, and taking it only from the price-nearest line
        # threw away every campaign named by a line that fitted just as well -
        # the candidates are already sorted price-nearest first, so the first
        # that names one is the nearest that does.
        best = one_campaign(guess.get('camp'), canon)
        camp0 = best
        for cand in (guess.get('cands') or []):
            if camp0:
                break
            camp0 = one_campaign(cand.get('camp'), canon)
        rescued = bool(camp0 and not best)
        key = (camp0 or (NO_CAMPAIGN if guess['promo'] else NO_PLAN), fam)
        agg = by_promo.setdefault(key, [0.0, 0.0, 0.0, collections.Counter(),
                                        collections.Counter()])
        agg[0] += 1
        agg[1] += qty
        agg[2] += amount or 0.0
        agg[3][how] += 1
        agg[4][(promo or o_detail)[:60]] += 1
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
        if guess.get('added_back'):
            added_back_n += 1
        # A plan match that needed a loosened rule is not the same answer as
        # one that did not, and the page should not colour them alike.
        if how == 'plan' and (guess['off_by'] or 'starts with' in guess['how']
                              or 'is the start of' in guess['how']
                              or 'same first' in guess['how']):
            how_page = 'loose'
        else:
            how_page = how
        camp = guess.get('camp') or ['', '', '']
        page.append((how_page,
                     c.get('channel') or unset,
                     c.get('type') or unset, c.get('type2') or unset,
                     group, cell(r, O['portal']) or '(blank)',
                     # One campaign out of the plan's three columns. The two
                     # residuals stay apart: outside every campaign is not the
                     # same as no plan line fitting at all.
                     one_campaign(camp, canon)
                     or (NO_CAMPAIGN if guess['promo'] else NO_PLAN),
                     # And the rest of what it named, where it named more.
                     ' + '.join(all_campaigns(camp, canon)[1:])
                     or '(names only the one)',
                     fam, o_type, o_detail,
                     cell(r, O['cat']) or '(blank)',
                     order['date'].isoformat() if order['date'] else '',
                     qty, amount or 0.0))
        # The campaign is the plan's answer whoever won the attribution: the
        # rule says what was done to the price and the plan says which campaign
        # it belonged to, and reading one off the other would lose half of it.
        tier_rows.append({
            'priced': guess['priced'],
            'chan': ((c.get('type') or '?')
                     + ('/' + c['type2'] if c.get('type2') else '')),
            'want': expected_tiers(c.get('type', ''), c.get('type2', '')),
            'rule_fam': family_label(*mechanic_of(rules), order_of)
                        if rules else '',
            'plan_fam': (family_label(guess['type'], guess['detail'], order_of)
                         if guess['promo'] else ''),
            'cands': guess.get('cands') or [], 'paid': paid,
            'paid_plan': gross or paid})
        camp_rows.append({
            'camp': [camp0, '', ''],
            'qty': qty, 'amt': amount or 0.0,
            # Measured on the merged campaign, not on the nationwide column:
            # two candidate lines that differ only in which column named the
            # same campaign are not two answers.
            'camp_alts': len({one_campaign(x.get('camp'), canon)
                              for x in (guess.get('cands') or [])}),
            'camp_lost': rescued, 'fam': fam,
            # What the export itself says came off, before any plan is
            # consulted. A rate is taken as a rate; otherwise the list price and
            # what was paid are divided.
            'own_dc': own_dc,
            'div': cell(r, O['division']) or '(blank)',
            'fitted': bool(guess['promo']), 'type': o_type,
            'group': group, 'sku': cell(r, O['sku']),
            'day': order['date'].isoformat() if order['date'] else '',
            # What was paid, and the list price of the plan line it matched:
            # both consumer prices, so the discount is one division and needs
            # no GST divisor.
            'paid': paid,
            # And the same price before the trade-in and the points, which is
            # what the plan quotes a price for.
            'paid_plan': gross or paid,
            # The store's rule names its own window. An order outside it is the
            # engine still applying a promotion that had ended, which needs no
            # plan to spot and is the sharpest thing this table can show.
            'rule_out': any((d['start'] and order['date'] and
                             order['date'] < d['start'])
                            or (d['end'] and order['date']
                                and order['date'] > d['end'])
                            for d in rules),
            'rrp': ((guess.get('cands') or [{}])[0].get('prices') or {}).get('RRP')
                   if guess['promo'] else None,
            # What answered for this line, and what the export says about the
            # discount besides its size. Together these decide whether a
            # discount that happened was also named - which is a different
            # question from whether it can be measured.
            'how': how,
            'rule_raw': cell(r, O['rule']),
            'cust_dc': parse_number(cell(r, O['disc_all']))
                       if O['disc_all'] is not None else None,
            'trade': parse_number(cell(r, O['trade']))
                     if O['trade'] is not None else None,
            'points': parse_number(cell(r, O['points']))
                      if O['points'] is not None else None,
            'order': cell(r, O['order']),
            'amt_line': amount})
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
            (guess.get('camp') or [''])[0], *(guess.get('camp') or ['', '', ''])[1:],
            guess.get('camp_alts', 0) or '',
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

    if only and only_orders:
        # Everything else that came on the same orders. A promotion that does
        # not move the line price often arrives as a line of its own - the gift,
        # the trade-in credit, the bundled watch at a dollar - and a matcher
        # looking only at the product's own line cannot see it at all.
        beside = collections.Counter()
        b_units = collections.Counter()
        b_amt = collections.Counter()
        free = 0.0
        for r in o_body:
            if cell(r, O['order']) not in only_orders:
                continue
            sku = cell(r, O['sku'])
            if only in code_norm(sku):
                continue
            q = parse_number(cell(r, O['qty'])) or 0.0
            a = parse_number(cell(r, O['amount']))
            beside[sku] += 1
            b_units[sku] += q
            b_amt[sku] += a or 0.0
            if a is not None and abs(a) < 0.01:
                free += q
        if beside:
            print(f'\nwhat else came on the same {len(only_orders):,} order(s)'
                  f' - {sum(beside.values()):,} line(s)')
            for sku, n in beside.most_common(12):
                print(f'  {sku[:24]:<24}{n:>7,} line(s){b_units[sku]:>9,.0f} '
                      f'unit(s){b_amt[sku]:>14,.0f}'
                      + ('   at nothing' if abs(b_amt[sku]) < 0.01 else ''))
            if free:
                print(f'  {free:,.0f} of those unit(s) came at no charge - a '
                      f'promotion given as a line of its own\n  rather than as '
                      f'a discount, which no price comparison on the product\'s '
                      f'own line\n  can see')

    if only:
        mine = [r for r in plan_rows if only in r['code']]
        print(f'\nwhat the plan has for {args.only!r}: {len(mine):,} live '
              f'line(s) over {len({r["code"] for r in mine}):,} product code(s)')
        if not mine:
            print('  nothing. Every order of it must therefore come back as '
                  '"the plan has no line for\n  this product", whatever the '
                  'rule says - that is the plan missing, not the match failing.')
        for r in sorted(mine, key=lambda r: (r['start'] or date(1900, 1, 1),
                                             r['code']))[:25]:
            win = (f'{r["start"]:%d%b} - {r["end"]:%d%b}'
                   if r['start'] and r['end'] else 'no window')
            price = ', '.join(f'{c.replace("_Price", "")} {v:,.0f}'
                              for c, v in sorted(r['prices'].items()))
            print(f'  {r["code"][:18]:<18}{win:<16}{r["type"][:18]:<19}'
                  f'{(one_campaign(r.get("camp"), canon) or "-")[:18]:<19}'
                  f'{price[:46]}')
        if len(mine) > 25:
            print(f'  ... and {len(mine) - 25:,} more')

    if tier_rows:
        tier_report(tier_rows)
        rule_price_report(tier_rows, args.price_tolerance)
    if added_back_n:
        print(f'\n{added_back_n:,} order line(s) fit a plan line only once the '
              f'trade-in and the points\n  redeemed were added back to what '
              f'was paid. The plan prices the promotion; a trade-in is a '
              f'separate\n  transaction that lands in the same amount column, '
              f'so without this a Fold8 traded up reads\n  far under every '
              f'price the plan quotes and is thrown out on price - inside its '
              f'window, on\n  the right code, at the right price until the '
              f'trade-in came off it.')
    if narrowed_n:
        print(f'\n{narrowed_n:,} order line(s) carry a rule the line itself '
              f'rules out - the cell holds every rule\n  the order qualified '
              f'for, and an order is more than one line. A Fold8 bought with a '
              f'case\n  comes back on both lines with the same pair; the phone '
              f'lost the voucher and the case\n  lost the thirty percent, and '
              f'each line is now read as what happened to it.')
    if camp_rows:
        own_discount_report(camp_rows)
        unnamed_discount_report(camp_rows)
        days = [d for d in (o['day'] for o in camp_rows) if d]
        if days:
            lo = date(int(min(days)[:4]), int(min(days)[5:7]), 1)
            e = max(days)
            y, m = int(e[:4]), int(e[5:7])
            hi = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
            # With --only the orders are one product's; the plan side has to
            # be the same product's, or every campaign in the file turns up
            # with its full plan counts against nothing, and "planned and
            # nothing arrived" becomes a list of campaigns that were never
            # about this product in the first place.
            mine = ([r for r in plan_rows if only in r['code']] if only
                    else plan_rows)
            planned_vs_arrived(mine, camp_rows, lo, hi, canon,
                               what=args.only if only else '')
        campaign_report(camp_rows)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = outdir / 'promo_orders.csv'
    with lines.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Order', 'Product', 'Portal group', 'Date', 'Qty', 'Paid',
                    'Unit price compared', 'Source', 'Promotion', 'Rule raw',
                    'Voucher', 'Plan says', 'Plan matched by', 'Plan price used',
                    'Price gap', 'Days outside window', 'Other plan lines fit',
                    'Nationwide campaign', 'DTC campaign 1', 'DTC campaign 2',
                    'Campaigns that fit'])
        w.writerows(out)
    summary = outdir / 'promo_summary.csv'
    table = sorted(by_promo.items(), key=lambda kv: -kv[1][2])
    with summary.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Campaign', 'Promotion', 'Order lines', 'Qty', 'Amount',
                    'Named by', 'Most often written as'])
        w.writerows([camp, name, int(v[0]), v[1], round(v[2], 2),
                     ', '.join(f'{k} {n:,}' for k, n in v[3].most_common()),
                     v[4].most_common(1)[0][0] if v[4] else '']
                    for (camp, name), v in table)
    print(f'\n-> {lines}\n-> {summary}')

    wide = min(34, max((len(nm) for (_, nm), _ in table[:15]), default=10))
    print(f'\n  {"":<26}{"":<{wide}} {"Lines":>8} {"Qty":>9} {"Amount":>14}'
          f'  named by')
    for (camp, name), v in table[:15]:
        print(f'  {camp[:24]:<26}{name[:34]:<{wide}} {v[0]:>8,.0f} '
              f'{v[1]:>9,.0f} {v[2]:>14,.0f}  '
              + ', '.join(f'{k} {n:,}' for k, n in v[3].most_common(2)))
    if len(table) > 15:
        print(f'  ... and {len(table) - 15:,} more in {summary.name}')
    print('  one row per promotion, not per source: the rule and the plan are '
          'two descriptions of\n  the same offer, so "named by" says which of '
          'them could name it rather than\n  splitting the offer in two')

    reasons: dict[str, int] = {}
    # Three real rows per kind, kept as they were written. A tally says how big
    # a problem is and an example says what it is, and the two are not
    # substitutes: "the price paid is N% from the nearest" is a shape, while
    # "SM-S938BZKEXSA, 12 Sep, paid 1,799 against a plan line at 2,399" is
    # something a person can go and look up.
    examples: dict[str, list] = {}
    for row in out:
        if row[7] == 'none':
            why = row[12] or 'no plan line'
            # One reason per kind, not one per day count: the numbers vary
            # line by line and the tally is about the kinds.
            why = re.sub(r'\(.*?\)', '(...)', why)
            why = re.sub(r'[-+]?\d[\d,.]*', 'N', why)
            reasons[why] = reasons.get(why, 0) + 1
            if len(examples.setdefault(why, [])) < 3:
                examples[why].append(row)
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
            for row in examples.get(why, []):
                # order, product, date, units, what a unit came to, and the
                # rule the store itself applied - enough to find the order.
                print(f'            {str(row[1])[:22]:<22} {str(row[3]):<11}'
                      f'{row[4]:>5} unit(s) at {row[6] or "?":>10}'
                      f'   order {str(row[0])[:18]}')
                if row[9]:
                    print(f'            {"":<22} rule  {str(row[9])[:92]}')
                if row[12]:
                    print(f'            {"":<22} plan  {str(row[12])[:92]}')

    if args.html is not None:
        yymm, _ = months_in(d for _, d in sorted(
            {(i, r[-3]) for i, r in enumerate(page)}))
        path = (Path(args.html) if args.html else
                ROOT / 'dashboard' / f'promo_{yymm or "nodate"}.html')
        write_page(path, args, ' + '.join(f['path'].name for f in plans),
                   op, page, ranked, cancelled,
                   campaign_fit(camp_rows) if camp_rows else None)
    return 0


MONTH_NAME = ('January', 'February', 'March', 'April', 'May', 'June', 'July',
              'August', 'September', 'October', 'November', 'December')


def months_in(dates) -> tuple:
    """(yymm, a title) for the months these order dates fall in.

    Read off the orders rather than written into the code. The page was named
    promo_2608.html and titled "August 2026 Promotions" whatever month was fed
    to it, so a September run overwrote August's page with September's data
    under August's name - the one mistake a file name can make that nobody
    catches, because the file is there and it opens.
    """
    seen = collections.Counter(d[:7] for d in dates if d and len(d) >= 7)
    if not seen:
        return '', 'Promotions'
    keys = sorted(seen)
    def name(k):
        y, m = k.split('-')
        return f'{MONTH_NAME[int(m) - 1]} {y}'
    first, last = keys[0], keys[-1]
    yymm = f'{first[2:4]}{first[5:7]}'
    if first == last:
        return yymm, f'{name(first)} Promotions'
    # A span, named as one: two months in a file is worth seeing in its title.
    return (f'{yymm}-{last[2:4]}{last[5:7]}',
            f'{name(first)} - {name(last)} Promotions')


def write_page(path: Path, args, plan_name: str, op, page: list, reasons: list,
               cancelled: int, fit: dict | None = None,
               levels: list | None = None, cust_depth: int = 5,
               start: str = 'Campaign', campaign: str = 'Campaign',
               source_labels: list | None = None) -> None:
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
    # The campaign levels sit at the top of the offer half, because the
    # nationwide campaign is the only one of these that divides revenue - every
    # unit is in exactly one - and a drill should start from the level that can
    # be stacked honestly and get looser as it goes in, not the other way round.
    # The simple read has its own, shorter drill - it infers no channel and
    # names no mechanic - so the levels are an argument rather than a constant.
    LEVELS = levels or ['Channel', 'Type', 'Type2', 'Portal Group', 'Portal',
                        'Campaign', 'Also in', 'Promotion',
                        'Offer Type', 'Offer Detail', 'Product Category']
    sources: dict[str, int] = {}
    values: list[dict[str, int]] = [{} for _ in LEVELS]
    days = set()
    buckets: dict[tuple, list[float]] = {}

    def idx(d, v):
        return d.setdefault(v, len(d))

    n_lv = len(LEVELS)
    for row in page:
        how, levels = row[0], row[1:1 + n_lv]
        day, qty, amt = row[1 + n_lv], row[2 + n_lv], row[3 + n_lv]
        days.add(day)
        key = (idx(sources, how),) + tuple(idx(values[i], v)
                                           for i, v in enumerate(levels)) + (day,)
        b = buckets.setdefault(key, [0.0, 0.0, 0.0])
        b[0] += 1
        b[1] += qty
        b[2] += amt

    payload = {
        'title': months_in(days)[1],
        'plan': plan_name, 'orders': op.name,
        'lines': len(page), 'cancelled': cancelled,
        'sources': list(sources),
        'days': sorted(days),
        # Campaign is where the page opens: it is the one level a stacked bar
        # can divide revenue by, and the looser levels sit inside it.
        'startDim': LEVELS.index(start),
        'custDepth': cust_depth,
        'levels': [{'name': n, 'values': list(v)}
                   for n, v in zip(LEVELS, values)],
        'rows': [{'s': k[0], 'k': list(k[1:1 + len(LEVELS)]), 'd': k[-1],
                  'n': int(v[0]), 'q': round(v[1], 2), 'a': round(v[2], 2)}
                 for k, v in buckets.items()],
        'sourceLabels': source_labels,
        'reasons': [[w, n] for w, n in reasons[:12]],
        'campaignDim': LEVELS.index(campaign),
        'fit': fit,
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

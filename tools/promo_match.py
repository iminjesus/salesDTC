#!/usr/bin/env python3
"""Work out which promotion each order came in on.

    py tools\\promo_match.py --profile     # describe both files, change nothing
    py tools\\promo_match.py               # attribute, and cross-check the two

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
import csv
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import find, parse_number, pick_file, read_any    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Header names these exports have used. The first hit wins; --flags override.
NAMES = {
    'sku':     ('SKU', 'Product Code', 'Material', 'Material Code', 'Model',
                'Model Code', 'Product Number', 'Item Code', 'Item'),
    'promo':   ('Nationwide_Campaign', 'DTC_Campaign1', 'Promotion Name',
                'Promotion', 'Campaign', 'Program'),
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
}
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
class Plan:
    """The promotion plan, indexed by product code and by voucher."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.by_code: dict[str, list[dict]] = {}
        self.by_voucher: dict[str, list[dict]] = {}
        for r in rows:
            self.by_code.setdefault(r['code'], []).append(r)
            for v in r['vouchers']:
                self.by_voucher.setdefault(v, []).append(r)
        self.by_length = sorted(self.by_code, key=len, reverse=True)

    def candidates(self, code: str) -> tuple[list[dict], str]:
        if not code:
            return [], 'the order has no product code'
        if code in self.by_code:
            return self.by_code[code], 'code'
        # A plan that lists a model family where the order carries the full
        # selling code. An inference, so it says so.
        for planned in self.by_length:
            if len(planned) >= 6 and code.startswith(planned):
                return self.by_code[planned], f'code starts with {planned}'
        return [], 'the plan has no line for this product'


def from_plan(order: dict, plan: Plan, tol: float) -> dict:
    """The plan line this order best fits, and what had to be assumed."""
    cands, how = plan.candidates(order['code'])
    if not cands:
        return {'promo': '', 'how': how, 'gap': '', 'alts': 0,
                'priced': '', 'type': ''}

    if order['date'] is not None:
        dated = [c for c in cands if c['start'] or c['end']]
        live = [c for c in dated
                if (c['start'] is None or c['start'] <= order['date'])
                and (c['end'] is None or order['date'] <= c['end'])]
        undated = [c for c in cands if c not in dated]
        if dated and not live and not undated:
            return {'promo': '', 'gap': '', 'alts': len(dated), 'priced': '',
                    'type': '',
                    'how': how + ', but no promotion for it was running that day'}
        if dated:
            cands = live + undated
            how += ', in window'

    gap, priced_as = '', ''
    if order['price'] is not None:
        priced = [(c, col, p) for c in cands for col, p in c['prices'].items()]
        if priced:
            priced.sort(key=lambda t: abs(t[2] - order['price']))
            best, col, p = priced[0]
            gap = round(order['price'] - p, 2)
            if abs(gap) <= max(0.01, abs(p) * tol / 100):
                priced_as = col
                cands = [best] + [c for c in cands if c is not best]
                how += f', paid the {col}'
            else:
                nothing = [c for c in cands if not c['prices']]
                if not nothing:
                    return {'promo': '', 'gap': gap, 'alts': len(cands),
                            'priced': '', 'type': '',
                            'how': how + f', but the price paid is {gap:+,.2f} '
                                   f'from the nearest ({best["promo"]}, {col})'}
                cands, gap = nothing, ''
                how += ', price fits none of the priced lines'

    return {'promo': cands[0]['promo'], 'how': how, 'gap': gap,
            'type': cands[0]['type'], 'priced': priced_as,
            'alts': len(cands) - 1}


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
    ap.add_argument('--plan', default='MX_product')
    ap.add_argument('--orders', default='26 DTC Aug')
    ap.add_argument('--profile', action='store_true',
                    help='describe both files and stop')
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--price-tolerance', type=float, default=3.0, metavar='PCT',
                    help='how far the price paid may sit from a plan price and '
                         'still count, as a percent of it (default 3)')
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
    pp, op = pick_file(folder, args.plan), pick_file(folder, args.orders)
    for what, p, asked in (('plan', pp, args.plan), ('orders', op, args.orders)):
        if p is None:
            print(f'no {what} file matching {asked!r} in {folder.resolve()}',
                  file=sys.stderr)
            return 2

    p_rows, p_info = read_any(pp)
    o_rows, o_info = read_any(op)
    p_head, p_body = [h.strip() for h in p_rows[0]], p_rows[1:]
    o_head, o_body = [h.strip() for h in o_rows[0]], o_rows[1:]
    print('reading:')
    print(f'  {pp.name}: {p_info["format"]}, {p_info["encoding"]}, {len(p_body):,} rows')
    print(f'  {op.name}: {o_info["format"]}, {o_info["encoding"]}, {len(o_body):,} rows')

    if args.profile:
        profile(pp.name, p_head, p_body)
        profile(op.name, o_head, o_body)

    P = {k: choose(p_head, p_body, k, getattr(args, f'promo_{k}', None)
                   if k in ('sku', 'name', 'start', 'end', 'voucher') else None)
         for k in ('sku', 'promo', 'promo2', 'type', 'start', 'end', 'status',
                   'site', 'voucher')}
    P['sku'] = choose(p_head, p_body, 'sku', args.promo_sku)
    P['promo'] = choose(p_head, p_body, 'promo', args.promo_name)
    P['start'] = choose(p_head, p_body, 'start', args.promo_start)
    P['end'] = choose(p_head, p_body, 'end', args.promo_end)
    P['voucher'] = choose(p_head, p_body, 'voucher', args.promo_voucher)
    O = {
        'sku': choose(o_head, o_body, 'sku', args.order_sku),
        'date': choose(o_head, o_body, 'date', args.order_date),
        'amount': choose(o_head, o_body, 'amount', args.order_amount),
        'order': choose(o_head, o_body, 'order', args.order_no),
        'qty': choose(o_head, o_body, 'qty', args.order_qty),
        'rule': choose(o_head, o_body, 'rule', args.order_rule),
        'voucher': choose(o_head, o_body, 'voucher', args.order_voucher),
        'group': choose(o_head, o_body, 'group', None),
        'cancel': choose(o_head, o_body, 'cancel', None),
    }
    price_cols = [(c, find(p_head, c)) for c in PRICE_COLS]
    price_cols = [(c, i) for c, i in price_cols if i is not None]

    print('\ncolumns chosen  (--flags override any of these):')
    rows_out = [(pp.name, 'product code', P['sku'], p_head, '--promo-sku'),
                (pp.name, 'campaign', P['promo'], p_head, '--promo-name'),
                (pp.name, 'also labelled by', P['promo2'], p_head, ''),
                (pp.name, 'offer type', P['type'], p_head, ''),
                (pp.name, 'starts', P['start'], p_head, '--promo-start'),
                (pp.name, 'ends', P['end'], p_head, '--promo-end'),
                (pp.name, 'status', P['status'], p_head, ''),
                (pp.name, 'voucher', P['voucher'], p_head, '--promo-voucher'),
                (op.name, 'product code', O['sku'], o_head, '--order-sku'),
                (op.name, 'order date', O['date'], o_head, '--order-date'),
                (op.name, 'order number', O['order'], o_head, '--order-no'),
                (op.name, 'units', O['qty'], o_head, '--order-qty'),
                (op.name, 'paid', O['amount'], o_head, '--order-amount'),
                (op.name, 'promotion rule', O['rule'], o_head, '--order-rule'),
                (op.name, 'voucher', O['voucher'], o_head, '--order-voucher')]
    for side, what, i, head, flag in rows_out:
        print(f'  {side[:18]:<18} {what:<16} '
              + (repr(head[i]) if i is not None
                 else f'-- none --' + (f'  ({flag})' if flag else '')))
    print(f'  {pp.name[:18]:<18} {"prices":<16} '
          + (', '.join(c for c, _ in price_cols) or '-- none --'))
    if args.profile:
        return 0
    if P['sku'] is None or O['sku'] is None:
        print('\nWithout a product code on both sides nothing can be matched.',
              file=sys.stderr)
        return 1
    return run(args, pp, op, p_head, p_body, o_head, o_body, P, O, price_cols)


def run(args, pp, op, p_head, p_body, o_head, o_body, P, O, price_cols) -> int:
    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    # ── the plan ────────────────────────────────────────────────────────────
    plan_rows, dropped = [], 0
    for r in p_body:
        code = code_norm(cell(r, P['sku']))
        if not code:
            continue
        status = cell(r, P['status']).lower()
        if not args.keep_cancelled and status in DEAD:
            dropped += 1
            continue
        label = ' / '.join(x for x in (cell(r, P['promo']), cell(r, P['promo2']),
                                       cell(r, P['type']))
                           if x and x != '-') or '(unnamed plan line)'
        plan_rows.append({
            'code': code, 'promo': label, 'type': cell(r, P['type']),
            'start': to_date(cell(r, P['start'])),
            'end': to_date(cell(r, P['end'])),
            'site': cell(r, P['site']),
            'vouchers': [code_norm(v) for v in split_rules(cell(r, P['voucher']))],
            'prices': {c: p for c, i in price_cols
                       if (p := parse_number(cell(r, i))) is not None},
        })
    plan = Plan(plan_rows)
    dated = sum(1 for r in plan_rows if r['start'] or r['end'])
    print(f'\nplan: {len(plan_rows):,} line(s) over {len(plan.by_code):,} product '
          f'code(s); {dated:,} carry a window, {len(plan.by_voucher):,} voucher '
          f'code(s)' + (f'; {dropped:,} cancelled or unapproved line(s) left out'
                        if dropped else ''))

    # ── the orders ──────────────────────────────────────────────────────────
    out, gaps = [], []
    source = {'rule': 0, 'voucher': 0, 'plan': 0, 'none': 0}
    agree = {'same': 0, 'differ': 0, 'outside': 0}
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
        guess = from_plan(order, plan, args.price_tolerance)
        if guess['gap'] != '':
            gaps.append(guess['gap'])

        if rules:
            how, promo = 'rule', ' + '.join(d['what'] for d in rules)
            # The two name promotions in different vocabularies - a rule says
            # PWP, the plan says "Black Friday / PWP" - so comparing the names
            # would measure nothing. The mechanic is the part both spell, and
            # the rule's own window is a check that needs no plan at all.
            if guess['type']:
                kinds = {t[:3].upper() for d in rules for t in d['what'].split()}
                if kinds:
                    agree['same' if guess['type'][:3].upper() in kinds
                          else 'differ'] += 1
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
        out.append([
            cell(r, O['order']), cell(r, O['sku']), cell(r, O['group']),
            order['date'].isoformat() if order['date'] else '',
            qty, amount if amount is not None else '',
            round(paid, 2) if paid is not None else '',
            how, promo,
            '; '.join(d['raw'] for d in rules),
            '; '.join(vouchers),
            guess['promo'], guess['how'], guess['priced'], guess['gap'],
            guess['alts'] or '',
        ])

    n = len(out) or 1
    print(f'\nattributed {len(out):,} order line(s)'
          + (f' ({cancelled:,} cancelled left out)' if cancelled else '') + ':')
    for k, label in (('rule', "the store's own promotion rule"),
                     ('voucher', 'a voucher the plan lists'),
                     ('plan', 'inferred from the plan - code, window, price'),
                     ('none', 'nothing fits')):
        print(f'  {source[k]:>8,}  {source[k] * 100 / n:>5.1f}%  {label}')
    both = agree['same'] + agree['differ']
    if both:
        print(f'  of {both:,} line(s) the rule and the plan both answered for, '
              f"the mechanic matches on {agree['same']:,} and differs on "
              f"{agree['differ']:,}")
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
                    'Price gap', 'Other plan lines fit'])
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
            why = re.sub(r'\(.*?\)', '(...)', why)
            why = re.sub(r'[-+][\d,.]+', 'N', why)
            reasons[why] = reasons.get(why, 0) + 1
    if reasons:
        print('\nwhy nothing fit:')
        for why, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:8]:
            print(f'  {count:>8,}  {why}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

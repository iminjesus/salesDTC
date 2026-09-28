#!/usr/bin/env python3
"""Work out which promotion each order came in on.

    py tools\\promo_match.py --profile     # describe both files, change nothing
    py tools\\promo_match.py               # and attribute the orders
    py tools\\promo_match.py --order-sku Model --promo-start "Start Date"

Two files: a promotion plan (one row per product per promotion, with a window
and usually a price) and the orders themselves. An order belongs to a promotion
when the product matches, the order date falls inside the window, and - where
both files carry a price - the price paid is near the promotion's.

None of that is certain, so nothing is asserted quietly. Every match records
which rule found it and how far the price was off, every order that matched
more than one promotion is marked rather than silently assigned, and the run
prints the columns it chose so a wrong guess is visible before the numbers are.

Start with --profile. It prints every column of both files with samples, and
says which ones it would use; the flags below override any of them.
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
    'sku':    ('SKU', 'Material', 'Material Code', 'Model', 'Model Code',
               'Model Name', 'Product Number', 'Product Code', 'Item', 'Item Code',
               'Product'),
    'promo':  ('Promotion', 'Promotion Name', 'Promo', 'Promo Name', 'Campaign',
               'Program', 'Offer', 'Deal', 'Activity'),
    'start':  ('Start', 'Start Date', 'From', 'From Date', 'Valid From',
               'Begin', 'Period Start', 'Promo Start'),
    'end':    ('End', 'End Date', 'To', 'To Date', 'Valid To', 'Finish',
               'Period End', 'Promo End'),
    'price':  ('Promo Price', 'Promotion Price', 'Price', 'Selling Price',
               'Net Price', 'Unit Price', 'Deal Price', 'Offer Price', 'RRP'),
    'date':   ('Order Date', 'Date', 'Created', 'Created Date', 'Order Created',
               'Purchase Date', 'Transaction Date', 'Invoice Date', 'Placed'),
    'order':  ('Order', 'Order No', 'Order Number', 'Order ID', 'Sales Order',
               'Document', 'Doc No', 'Invoice No', 'Reference'),
    'qty':    ('Qty', 'Quantity', 'Order Qty', 'Units', 'Quantity(Net)'),
    'amount': ('Amount', 'Net Amount', 'Sales', 'Net Sales', 'Total', 'Line Total',
               'Value', 'Revenue'),
}

# ── reading the messy bits ──────────────────────────────────────────────────
DATE_PATTERNS = (
    '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y%m%d',
    '%d/%m/%y', '%m/%d/%y', '%d-%b-%Y', '%d-%b-%y', '%d %b %Y', '%b %d %Y',
    '%d.%m.%Y', '%Y.%m.%d',
)
EXCEL_EPOCH = date(1899, 12, 30)     # Excel's day 1 is 1900-01-01, with the leap bug


def to_date(v) -> date | None:
    """The date a cell holds, or None.

    Exports disagree about order and separator, and a spreadsheet round-trip
    turns a date into a serial number. Ambiguous day/month pairs are read as
    day-first, which is what an Australian export means.
    """
    t = str(v or '').strip()
    if not t:
        return None
    if ' ' in t and any(c in t for c in ':T'):
        t = re.split(r'[ T]', t)[0]              # drop a time part
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    n = parse_number(t)
    if n is not None and 20000 < n < 60000:      # an Excel serial, 1954..2064
        return EXCEL_EPOCH + timedelta(days=int(n))
    return None


def code_norm(v) -> str:
    """A product code with the punctuation and case an export disagrees on."""
    return re.sub(r'[^0-9A-Z]', '', str(v or '').upper())


# ── describing a file ───────────────────────────────────────────────────────
def profile(name: str, head: list[str], rows: list[list[str]]) -> None:
    print(f'\n{name}: {len(rows):,} rows, {len(head)} columns')
    width = max(len(h) for h in head) if head else 8
    for i, h in enumerate(head):
        vals = [(r[i].strip() if i < len(r) else '') for r in rows]
        filled = [v for v in vals if v]
        if not filled:
            print(f'  {h:<{min(width, 28)}}  empty')
            continue
        distinct = len(set(filled))
        dates = sum(1 for v in filled[:200] if to_date(v))
        nums = sum(1 for v in filled[:200] if parse_number(v) is not None)
        seen = min(200, len(filled))
        kind = ('date' if dates > seen * 0.8 else
                'number' if nums > seen * 0.8 else 'text')
        samples = ', '.join(sorted(set(filled), key=filled.index)[:3])
        print(f'  {h:<{min(width, 28)}}  {kind:<6} {len(filled) * 100 // len(vals):>3}% '
              f'filled, {distinct:>6,} distinct   e.g. {samples[:60]}')


def choose(head: list[str], rows: list[list[str]], what: str,
           override: str | None) -> int | None:
    """The column to use, by flag, then by name, then by what it holds."""
    if override:
        i = find(head, override)
        if i is None:
            print(f'  no column named {override!r}; columns are: '
                  + ', '.join(head), file=sys.stderr)
            raise SystemExit(2)
        return i
    i = find(head, *NAMES[what])
    if i is not None:
        return i
    if what in ('start', 'end', 'date'):         # fall back to what it looks like
        best = None
        for j, _ in enumerate(head):
            filled = [r[j].strip() for r in rows[:200] if j < len(r) and r[j].strip()]
            if filled and sum(1 for v in filled if to_date(v)) > len(filled) * 0.8:
                best = j if best is None else best
        return best
    return None


# ── matching ────────────────────────────────────────────────────────────────
class Plan:
    """The promotion plan, indexed the three ways a code can be written.

    A plan lists a model family, `SM-S931B`, where the order carries the full
    code it was sold under, `SM-S931BZKAXSA`. So an exact match is tried first,
    then the same code with punctuation removed, and only then the longest plan
    code that the order code starts with - which is reported as such, because
    it is an inference rather than a match.
    """

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.exact: dict[str, list[dict]] = {}
        for r in rows:
            self.exact.setdefault(r['code'], []).append(r)
        # Longest first, so the most specific family wins a prefix match.
        self.by_length = sorted(self.exact, key=len, reverse=True)

    def candidates(self, code: str) -> tuple[list[dict], str]:
        if not code:
            return [], 'no code'
        if code in self.exact:
            return self.exact[code], 'code'
        for plan_code in self.by_length:
            if len(plan_code) >= 5 and code.startswith(plan_code):
                return self.exact[plan_code], f'code starts with {plan_code}'
        return [], 'no promotion for this code'


def attribute(order: dict, plan: Plan, tol: float) -> dict:
    """Which promotion this order line came in on, and how sure that is.

    `tol` is how far, as a percentage of the promotion's price, the price paid
    may sit from it and still count. An order that paid the full price did not
    come in on a promotion, however neatly the code and the dates line up, and
    saying otherwise would credit a discount that was never given.
    """
    cands, how = plan.candidates(order['code'])
    if not cands:
        return {'promo': '', 'how': how, 'gap': '', 'alts': 0}

    # The window first: a promotion that was not running cannot have sold it.
    if order['date'] is not None:
        dated = [c for c in cands if c['start'] or c['end']]
        if dated:
            live = [c for c in dated
                    if (c['start'] is None or c['start'] <= order['date'])
                    and (c['end'] is None or order['date'] <= c['end'])]
            undated = [c for c in cands if c not in dated]
            if live or undated:
                cands = live + undated
                how += ', in window'
            else:
                return {'promo': '', 'how': how + ', but none was running that day',
                        'gap': '', 'alts': len(dated)}

    # Then the price, where both sides have one: the promotion whose price the
    # order actually paid is the one it came in on.
    gap = ''
    priced = [c for c in cands if c['price'] is not None]
    if order['price'] is not None and priced:
        priced.sort(key=lambda c: abs(c['price'] - order['price']))
        best = priced[0]
        gap = round(order['price'] - best['price'], 2)
        within = abs(gap) <= max(0.01, abs(best['price']) * tol / 100)
        if not within:
            unpriced = [c for c in cands if c['price'] is None]
            if not unpriced:
                return {'promo': '', 'gap': gap, 'alts': len(cands),
                        'how': how + f', but the price paid is {gap:+,.2f} from '
                               f'the nearest promotion ({best["promo"]})'}
            cands = unpriced            # only the ones that never quoted a price
            gap = ''
            how += ', price fits none of the priced ones'
        else:
            cands = priced + [c for c in cands if c['price'] is None]
            if len(priced) > 1:
                how += ', nearest price'

    return {'promo': cands[0]['promo'], 'how': how, 'gap': gap,
            'alts': len(cands) - 1}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--plan', default='MX_product',
                    help='the promotion plan file (default: MX_product)')
    ap.add_argument('--orders', default='26 DTC Aug',
                    help='the order file (default: "26 DTC Aug")')
    ap.add_argument('--profile', action='store_true',
                    help='describe both files and stop')
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--price-tolerance', type=float, default=3.0, metavar='PCT',
                    help='how far the price paid may sit from a promotion price '
                         'and still count, as a percent of it (default 3). '
                         'Raise it if the two files quote prices on different '
                         'bases; 0 turns the price test off')
    for flag, what in (('promo-sku', 'the product code in the plan'),
                       ('promo-name', 'the promotion name'),
                       ('promo-start', 'the first day it runs'),
                       ('promo-end', 'the last day it runs'),
                       ('promo-price', 'the price it sells at'),
                       ('order-sku', 'the product code on the order'),
                       ('order-date', 'the order date'),
                       ('order-price', 'the price paid per unit'),
                       ('order-no', 'the order number'),
                       ('order-qty', 'the units ordered'),
                       ('order-amount', 'the line value')):
        ap.add_argument(f'--{flag}', metavar='COLUMN', help=what)
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    pp = pick_file(folder, args.plan)
    op = pick_file(folder, args.orders)
    for what, p, asked in (('plan', pp, args.plan), ('orders', op, args.orders)):
        if p is None:
            print(f'no {what} file matching {asked!r} in {folder.resolve()}. '
                  'Files there: ' + ', '.join(sorted(x.name for x in folder.iterdir()
                                                     if x.is_file())),
                  file=sys.stderr)
            return 2

    p_rows, p_info = read_any(pp)
    o_rows, o_info = read_any(op)
    p_head, p_body = [h.strip() for h in p_rows[0]], p_rows[1:]
    o_head, o_body = [h.strip() for h in o_rows[0]], o_rows[1:]
    print('reading:')
    print(f'  {pp.name}: {p_info["format"]}, {p_info["encoding"]}, {len(p_body):,} rows')
    print(f'  {op.name}: {o_info["format"]}, {o_info["encoding"]}, {len(o_body):,} rows')

    profile(pp.name, p_head, p_body)
    profile(op.name, o_head, o_body)

    pick = {
        'p_sku':   choose(p_head, p_body, 'sku', args.promo_sku),
        'p_promo': choose(p_head, p_body, 'promo', args.promo_name),
        'p_start': choose(p_head, p_body, 'start', args.promo_start),
        'p_end':   choose(p_head, p_body, 'end', args.promo_end),
        'p_price': choose(p_head, p_body, 'price', args.promo_price),
        'o_sku':   choose(o_head, o_body, 'sku', args.order_sku),
        'o_date':  choose(o_head, o_body, 'date', args.order_date),
        'o_price': choose(o_head, o_body, 'price', args.order_price),
        'o_no':    choose(o_head, o_body, 'order', args.order_no),
        'o_qty':   choose(o_head, o_body, 'qty', args.order_qty),
        'o_amt':   choose(o_head, o_body, 'amount', args.order_amount),
    }
    print('\ncolumns chosen  (--flags override any of these):')
    for key, (side, label, flag) in {
            'p_sku':   (pp.name, 'product code', '--promo-sku'),
            'p_promo': (pp.name, 'promotion name', '--promo-name'),
            'p_start': (pp.name, 'starts', '--promo-start'),
            'p_end':   (pp.name, 'ends', '--promo-end'),
            'p_price': (pp.name, 'promo price', '--promo-price'),
            'o_sku':   (op.name, 'product code', '--order-sku'),
            'o_date':  (op.name, 'order date', '--order-date'),
            'o_price': (op.name, 'price paid', '--order-price'),
            'o_no':    (op.name, 'order number', '--order-no'),
            'o_qty':   (op.name, 'units', '--order-qty'),
            'o_amt':   (op.name, 'line value', '--order-amount'),
    }.items():
        head = p_head if key.startswith('p_') else o_head
        i = pick[key]
        print(f'  {side[:18]:<18} {label:<14} '
              + (repr(head[i]) if i is not None else f'-- none --  ({flag})'))

    if args.profile:
        return 0
    if pick['p_sku'] is None or pick['o_sku'] is None:
        print('\nWithout a product code on both sides nothing can be matched. '
              'Name them with --promo-sku and --order-sku.', file=sys.stderr)
        return 1

    def cell(r, i):
        return (r[i].strip() if i is not None and i < len(r) else '')

    plan_rows = []
    for r in p_body:
        code = code_norm(cell(r, pick['p_sku']))
        if not code:
            continue
        plan_rows.append({
            'code': code,
            'promo': cell(r, pick['p_promo']) or '(unnamed promotion)',
            'start': to_date(cell(r, pick['p_start'])),
            'end': to_date(cell(r, pick['p_end'])),
            'price': parse_number(cell(r, pick['p_price'])),
        })
    plan = Plan(plan_rows)
    dated = sum(1 for r in plan_rows if r['start'] or r['end'])
    priced = sum(1 for r in plan_rows if r['price'] is not None)
    print(f'\nplan: {len(plan_rows):,} promotion line(s) over '
          f'{len(plan.exact):,} product code(s); {dated:,} carry a date window, '
          f'{priced:,} carry a price')
    if not dated:
        print('  no usable dates, so the window test is skipped and a code that '
              'ran two promotions cannot be told apart by when it sold')

    out_rows = []
    gaps: list[float] = []
    tally = {'matched': 0, 'ambiguous': 0, 'unmatched': 0}
    by_promo: dict[str, list[float]] = {}
    for r in o_body:
        order = {
            'code': code_norm(cell(r, pick['o_sku'])),
            'date': to_date(cell(r, pick['o_date'])),
            'price': parse_number(cell(r, pick['o_price'])),
        }
        hit = attribute(order, plan, args.price_tolerance)
        if hit['gap'] != '':
            gaps.append(hit['gap'])
        qty = parse_number(cell(r, pick['o_qty'])) or 0.0
        amt = parse_number(cell(r, pick['o_amt'])) or 0.0
        if hit['promo']:
            tally['ambiguous' if hit['alts'] else 'matched'] += 1
            agg = by_promo.setdefault(hit['promo'], [0.0, 0.0, 0.0])
        else:
            tally['unmatched'] += 1
            agg = by_promo.setdefault('(no promotion)', [0.0, 0.0, 0.0])
        agg[0] += 1
        agg[1] += qty
        agg[2] += amt
        out_rows.append([
            cell(r, pick['o_no']), cell(r, pick['o_sku']),
            order['date'].isoformat() if order['date'] else '',
            cell(r, pick['o_price']), qty, amt,
            hit['promo'], hit['how'], hit['gap'],
            hit['alts'] or '',
        ])

    n = len(o_body) or 1
    print(f'\nattributed {len(o_body):,} order line(s):')
    for k, label in (('matched', 'one promotion fits'),
                     ('ambiguous', 'more than one fits - the best is used'),
                     ('unmatched', 'none fits')):
        print(f'  {tally[k]:>8,}  {tally[k] * 100 / n:>5.1f}%  {label}')
    # A price column on a different basis - one file including tax, the other
    # not - turns every gap into a rejection. The spread says which it is.
    if gaps:
        gaps.sort()
        mid = gaps[len(gaps) // 2]
        print(f'  price paid vs promotion price, over {len(gaps):,} comparison(s): '
              f'median {mid:+,.2f}, smallest {gaps[0]:+,.2f}, '
              f'largest {gaps[-1]:+,.2f}')
        if abs(mid) > 0.01:
            print('  a median far from zero means the two files quote prices on '
                  'different bases (tax in or out, per unit or per line); '
                  '--price-tolerance or --order-price is the fix')

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    lines = outdir / 'promo_orders.csv'
    with lines.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Order', 'Product', 'Date', 'Price paid', 'Qty', 'Amount',
                    'Promotion', 'Matched by', 'Price vs promo', 'Other fits'])
        w.writerows(out_rows)
    summary = outdir / 'promo_summary.csv'
    table = sorted(by_promo.items(), key=lambda kv: -kv[1][2])
    with summary.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Promotion', 'Order lines', 'Qty', 'Amount'])
        w.writerows([name, int(v[0]), v[1], round(v[2], 2)] for name, v in table)
    print(f'\n-> {lines}\n-> {summary}')

    wide = min(44, max((len(k) for k, _ in table[:15]), default=10))
    print(f'\n  {"":<{wide}} {"Lines":>8} {"Qty":>10} {"Amount":>16}')
    for name, v in table[:15]:
        print(f'  {name[:44]:<{wide}} {v[0]:>8,.0f} {v[1]:>10,.0f} {v[2]:>16,.0f}')
    if len(table) > 15:
        print(f'  ... and {len(table) - 15:,} more in {summary.name}')

    # "None fits" is several different answers, and which one it is decides
    # what to do about it - so they are counted apart rather than together.
    reasons: dict[str, int] = {}
    no_code: dict[str, int] = {}
    for row in out_rows:
        if row[6]:
            continue
        why = row[7]
        if why.startswith('no promotion for this code'):
            key = 'the plan has no line for this product'
            no_code[row[1] or '(blank)'] = no_code.get(row[1] or '(blank)', 0) + 1
        elif 'none was running that day' in why:
            key = 'no promotion was running on the order date'
        elif 'price paid is' in why:
            key = 'the price paid is not a promotion price'
        else:
            key = why
        reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        print('\nwhy the rest did not match:')
        for why, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f'  {count:>8,}  {why}')
    if no_code:
        worst = sorted(no_code.items(), key=lambda kv: -kv[1])[:8]
        print(f'\n{len(no_code):,} product code(s) are not in the plan at all. '
              'Most lines:')
        for code, count in worst:
            print(f'  {code[:34]:<34} {count:>6,} line(s)')
        print('  the plan is keyed on e.g. '
              + ', '.join(repr(c) for c in list(plan.exact)[:4]))
    return 0


if __name__ == '__main__':
    sys.exit(main())

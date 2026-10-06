#!/usr/bin/env python3
"""Average selling price over several months, as two Excel workbooks.

    py tools\\asp_xlsx.py --months 2607 2608 2609

Writes exactly two files:

    Material.xlsx     every material, all channels
    Online ASP.xlsx   every material, the online channel only

Per month a material gets its units, its net sales, the price those two come
to, the RRP the plan had on it, and the gap between the two as a percent -
then the same five over the span, and last the promotion its orders ran under.

**The totals are the profit export's.** Units and net sales are read from the
profit exports and from nothing else; the plan and the store's own orders are
read only to label what the profit export already counted - an RRP, a
discount, a promotion name. Neither can add a unit, move a dollar, or drop a
material from the sheet, so every column that sums sums to the same figure the
profit file does.

ASP is **net sales over net quantity**, and over a span it is the span's totals
divided - not the average of each month's own ASP. Three monthly prices
averaged flat would let a month that sold forty units weigh as much as one that
sold four thousand, which is how a quiet month comes to set the price of a busy
one. The monthly columns are there to be read; the ASP column is weighted.

Returns are netted off both sides by the export, so a material whose returns
outweigh its sales can end up at zero or below. Those are left blank and
counted rather than divided: a price of minus four hundred is not a price, and
a division by zero in a spreadsheet is worse than a gap.
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import customer as CUST                                        # noqa: E402
import promo as PR                                             # noqa: E402
import promo_match as PM                                       # noqa: E402
import xlsx as XL                                              # noqa: E402
from asp import (AMT_NET, CUSTOMER_KEYS, PRODUCT_COLS,          # noqa: E402
                 PRODUCT_KEYS, QTY_NET)
from rawdata import (find, key_norm, master, parse_number,      # noqa: E402
                     pick_file, pick_series, read_any)

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

# Where a product master might keep a list price, if it keeps one at all. Tried
# only after the plan, which is the file that is actually maintained month by
# month - a master's price is whatever it was when the material was created.
PRODUCT_RRP = ('RRP', 'RRP (incl GST)', 'RRP incl GST', 'RRP Incl. GST',
               'Recommended Retail Price', 'List Price', 'MSRP',
               'Retail Price', 'Launch RRP')

COLS_PER_MONTH = 5          # qty, net sales, ASP, RRP, DC %


def month_label(yymm: str) -> str:
    """2607 -> Jul 2026."""
    s = ''.join(ch for ch in yymm if ch.isdigit())[-4:]
    if len(s) != 4:
        return yymm
    y, m = int(s[:2]), int(s[2:])
    return f'{MONTHS[m - 1]} 20{y:02d}' if 1 <= m <= 12 else yymm


def month_span(yymm: str) -> tuple:
    """The first and last day of 2607, for testing a promotion window."""
    s = ''.join(ch for ch in yymm if ch.isdigit())[-4:]
    y, m = 2000 + int(s[:2]), int(s[2:])
    lo = date(y, m, 1)
    hi = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return lo, hi


def short_month(yymm: str) -> str:
    """2607 -> Jul 26, for a header that has to sit in a column."""
    s = ''.join(ch for ch in yymm if ch.isdigit())[-4:]
    y, m = int(s[:2]), int(s[2:])
    return f'{MONTHS[m - 1]} {y:02d}' if 1 <= m <= 12 else yymm


def cell(r, i):
    return (r[i].strip() if i is not None and i < len(r) else '')


# ── what the plan says a material was worth ─────────────────────────────────
class ListPrice:
    """The RRP a material carried in a given month.

    Two sources, and which one answered is reported rather than blended. The
    plan is asked first: it is kept month by month and carries the windows, so
    it knows that a price changed in the middle of August. The product master
    is the fallback and has no month at all - one price, repeated across the
    span, which is right for a material that never moved and wrong silently for
    one that did. So where both answer the plan wins, and the count of
    materials priced from each is printed.
    """

    def __init__(self, plan, prod, say=print):
        self.plan = plan
        self.prod = prod
        self.say = say
        self.cands: dict[str, tuple] = {}
        self.whence = collections.Counter()

    def _candidates(self, code):
        if code not in self.cands:
            self.cands[code] = (self.plan.candidates(code) if self.plan
                                else ([], 'no plan was read'))
        return self.cands[code]

    def of(self, sku: str, yymm: str):
        """(price, where it came from) - price None where neither file says."""
        code = PM.code_norm(sku)
        cands, _ = self._candidates(code)
        if cands:
            lo, hi = month_span(yymm)

            def covers(c):
                if c['start'] and c['start'] > hi:
                    return False
                if c['end'] and c['end'] < lo:
                    return False
                return True

            for pool, where in ((list(filter(covers, cands)), 'in month'),
                                (cands, 'another month')):
                vals = [c['prices']['RRP'] for c in pool if 'RRP' in c['prices']]
                if vals:
                    # The commonest value, and the highest where several are
                    # equally common: a list price, not one of the offers sat
                    # under it.
                    n = collections.Counter(vals)
                    top = max(n.values())
                    best = max(v for v in n if n[v] == top)
                    src = next((c['source'] for c in pool
                                if c['prices'].get('RRP') == best), '')
                    self.whence[f'{src or "plan"}, {where}'] += 1
                    return best, f'{src or "plan"}, {where}'
        got = parse_number((self.prod.get(key_norm(sku)) or {}).get('rrp'))
        if got:
            self.whence['product master'] += 1
            return got, 'product master'
        self.whence['nothing says'] += 1
        return None, 'neither the plan nor the product master has an RRP'

    def report(self):
        for where, n in self.whence.most_common():
            self.say(f'    {n:>7,}  {where}')


# ── what the store ran it under ─────────────────────────────────────────────
def promotions_of(path, detail=False, precedence=None, say=print) -> dict:
    """Units per promotion per material, from one month of store orders.

    A material's units in a month rarely sit on one promotion - most of MX's
    promoted units ran under more than one rule - so this keeps the whole
    split and the cell printed later names the biggest with its share. A single
    label with no share reads as "this is what it was", which for a material
    that was half one offer and half another is simply untrue.

    Nothing here touches a quantity in the workbook: these units are the
    store's own count of its own orders, used to decide which name to print
    beside the profit export's figures, never to replace them.
    """
    rows = PR.read_store(path, say=say)
    if rows is None:
        return {}
    out: dict[str, collections.Counter] = {}
    for r in rows:
        if 'CANCEL' in r['status']:
            continue
        code = PM.code_norm(r['sku'])
        if not code:
            continue
        raw = (r['raw'] or '').strip()
        if not raw or raw == '-':
            label = PR.NONE
        else:
            kind, offer, _ = PR.levels_of(raw)
            label = offer if detail else PR.family_of(offer, precedence)
        out.setdefault(code, collections.Counter())[label] += max(r['qty'], 0.0)
    return out


def promo_cell(tally) -> str:
    """The promotion a material-month mostly ran under, with its share."""
    if not tally:
        return ''
    live = {k: v for k, v in tally.items() if v > 0}
    if not live:
        return ''
    total = sum(live.values())
    # Sorted first, so two promotions on the same number of units always give
    # the same answer rather than one that depends on which order the export
    # happened to list them in.
    best = max(sorted(live), key=live.get)
    if live[best] >= total * 0.995:
        return best
    rest = len(live) - 1
    return (f'{best} ({live[best] / total * 100:.0f}% of units, {rest} other'
            + ('s)' if rest > 1 else ')'))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--months', nargs='+', default=['2607', '2608', '2609'],
                    metavar='YYMM', help='the months to read (default: '
                                         '2607 2608 2609)')
    ap.add_argument('--channel', default=CUST.ONLINE, metavar='NAME',
                    help=f'which channel the second workbook keeps '
                         f'(default: {CUST.ONLINE})')
    ap.add_argument('--plan', nargs='+', default=['MX_product', 'ce_product'],
                    metavar='STEM',
                    help='the promotion plan(s) the RRP is read from, one per '
                         'division, read together (default: MX_product '
                         'ce_product; a stem that names no file is skipped)')
    ap.add_argument('--gst', type=float, default=1.1, metavar='N',
                    help='what the RRP is divided by before it is compared '
                         'against net sales, because a plan RRP is a consumer '
                         'price and net sales is not (default 1.1; pass 1 if '
                         'your RRP is already ex GST)')
    ap.add_argument('--detail', action='store_true',
                    help='name the offer itself in the promotion column rather '
                         'than the family it belongs to')
    ap.add_argument('--precedence', metavar='LIST',
                    help='which family a unit counts as where it matches '
                         'several, highest first, comma separated (default: '
                         'the order of the table in promo.py)')
    ap.add_argument('--no-promotion', action='store_true',
                    help='skip the store exports, and the promotion columns '
                         'with them')
    ap.add_argument('--out', default=str(ROOT / 'docs'),
                    help='where the two workbooks go (default: docs/)')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    if args.gst <= 0:
        print('--gst has to be positive', file=sys.stderr)
        return 2
    order = [s.strip() for s in (args.precedence or '').split(',') if s.strip()]

    # One export per month asked for, by the digits in its name.
    want = []
    for ym in args.months:
        digits = ''.join(ch for ch in ym if ch.isdigit())[-4:]
        hit = [p for p in pick_series(folder, 'profit')
               if digits in ''.join(ch for ch in p.stem if ch.isdigit())]
        if not hit:
            print(f'no profit export for {ym} in {folder.resolve()}',
                  file=sys.stderr)
            return 2
        want.append((digits, hit[0]))

    def read_master(prefix, keys, want):
        """The first candidate that can actually be read.

        One unreadable workbook used to end a whole run after all the reading
        was done, so a master that will not open is reported and the next
        spelling of it is tried instead.
        """
        for cand in pick_series(folder, prefix):
            try:
                got = master(cand, keys, want, say=lambda *a: None)
            except (ValueError, OSError, IndexError, KeyError) as e:
                print(f'  {cand.name}: {e} - trying the next one')
                continue
            if got:
                return cand, got
        return None, {}

    wantp = dict(PRODUCT_COLS)
    wantp['rrp'] = PRODUCT_RRP
    pp, prod = read_master('product', PRODUCT_KEYS, wantp)
    print(f'product master: {pp.name}, {len(prod):,} material(s)' if pp
          else 'no product master could be read - the description, division, '
               'category and range columns will be blank')
    wantc = {slot: names for _, slot, names in CUST.LEVELS if names}
    wantc['account'] = CUST.ACCOUNT_NAMES
    cp, cust = read_master('customer', ('Sold-To', 'sold To', 'sold_to'), wantc)
    print(f'customer master: {cp.name}, {len(cust):,} account(s)' if cp
          else 'no customer master could be read - without it no row can be '
               'placed in a channel, so "Online ASP" would come out empty')
    if not cust:
        print('  stopping rather than writing an empty Online ASP workbook',
              file=sys.stderr)
        return 1

    # ── the plan, for the RRP ───────────────────────────────────────────────
    print('\nplan(s), for the RRP:')
    plan, pmeta = PM.load_plans(folder, args.plan)
    if not pmeta:
        print('  nothing readable - the RRP falls back to the product master')
        plan = None
    # Where more than one was read, where they differ from each other is the
    # first thing worth knowing: a column one file spells differently is read
    # as blank in the other, and a blank RRP is indistinguishable from a
    # material nobody priced.
    PM.plan_structure(pmeta)
    price = ListPrice(plan, prod)

    # ── the store's own orders, for the promotion ───────────────────────────
    promos: dict[str, dict] = {}
    if not args.no_promotion:
        print('\nstore orders, for the promotion columns only:')
        for digits, _ in want:
            lo, _ = month_span(digits)
            stems = (f'{digits[:2]} DTC {MONTHS[lo.month - 1]}',
                     f'dtc_{digits}', f'dtc{digits}', f'{digits}_dtc')
            sp = pick_file(folder, *stems)
            if sp is None:
                print(f'  {month_label(digits)}: no store export '
                      f'(tried {", ".join(repr(s) for s in stems)})')
                continue
            promos[digits] = promotions_of(sp, args.detail, order)
            print(f'    {len(promos[digits]):,} material code(s) with a '
                  f'promotion')

    # material -> {'qty': {month: n}, 'amt': {month: n}, 'on_qty': .., 'on_amt': ..}
    rows: dict[str, dict] = {}
    src = collections.Counter()      # what the exports themselves add up to
    lost = collections.Counter()     # and what could not be put on a material
    print('\nreading (these are the figures the workbook totals):')
    for digits, path in want:
        raw, info = read_any(path)
        head = [h.strip() for h in raw[0]]
        q_i, a_i = find(head, *QTY_NET), find(head, *AMT_NET)
        p_i, c_i = find(head, *PRODUCT_KEYS), find(head, *CUSTOMER_KEYS)
        print(f'  {path.name}: {info["format"]}, {len(raw) - 1:,} rows')
        if q_i is None or a_i is None or p_i is None:
            print('    needs a net quantity, a net sales and a product column'
                  ' - skipped', file=sys.stderr)
            return 1
        for r in raw[1:]:
            q = parse_number(cell(r, q_i)) or 0.0
            a = parse_number(cell(r, a_i)) or 0.0
            # Counted before anything is decided about the row, so the figure
            # the workbook is checked against is the export's own and not a
            # version of it this tool already agrees with.
            src['q'] += q
            src['a'] += a
            sku = cell(r, p_i)
            if not sku:
                lost['q'] += q
                lost['a'] += a
                lost['n'] += 1
                continue
            v = rows.setdefault(sku, {'qty': {}, 'amt': {},
                                      'on_qty': {}, 'on_amt': {}})
            v['qty'][digits] = v['qty'].get(digits, 0.0) + q
            v['amt'][digits] = v['amt'].get(digits, 0.0) + a
            c = cust.get(key_norm(cell(r, c_i))) or {}
            if CUST.channel_of(c.get('account'), bool(c)) == args.channel:
                v['on_qty'][digits] = v['on_qty'].get(digits, 0.0) + q
                v['on_amt'][digits] = v['on_amt'].get(digits, 0.0) + a

    if not rows:
        print('\nnothing to write.', file=sys.stderr)
        return 1

    months = [d for d, _ in want]
    # The RRP is a property of the material and the month, not of the channel,
    # so it is resolved once and both workbooks read the same answer.
    rrp = {sku: {m: price.of(sku, m)[0] for m in months} for sku in rows}
    print(f'\nRRP, for {len(rows):,} material code(s):')
    price.report()
    check(rows, rrp, months, args.gst)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for name, qk, ak in (('Material', 'qty', 'amt'),
                         ('Online ASP', 'on_qty', 'on_amt')):
        path = out / f'{name}.xlsx'
        made.append((path,) + write_book(path, name, rows, months, qk, ak,
                                        prod, rrp, promos, args))

    print()
    for path, n, blank, q, a in made:
        print(f'-> {path.name}  {n:,} material code(s), {q:,.0f} net unit(s), '
              f'{a:,.0f} net sales'
              + (f', {blank:,} with no price' if blank else ''))
        print(f'   {path.resolve()}')

    # The totals are the profit export's, so say so with the two figures side by
    # side rather than in a docstring. A gap here is a bug in this tool, and the
    # only honest place to find it is on the way out.
    print(f'\nagainst the profit exports: {src["q"]:,.0f} net unit(s), '
          f'{src["a"]:,.0f} net sales')
    _, _, _, mq, ma = made[0]
    gap_q, gap_a = mq - src['q'], ma - src['a']
    print(f'  Material.xlsx: {mq:,.0f} and {ma:,.0f} - '
          + ('they match' if abs(gap_q) < 0.5 and abs(gap_a) < 0.5
             else f'off by {gap_q:+,.0f} unit(s) and {gap_a:+,.0f}'))
    if lost['n']:
        print(f'  {lost["n"]:,} export row(s) carry no material code and are in '
              f'neither workbook: {lost["q"]:,.0f} unit(s), {lost["a"]:,.0f}')
    # A workbook keyed on the material cannot hold a row that has no material,
    # so that much of the gap is accounted for and named above. Anything left
    # over is not, and is the only thing worth a failing exit code.
    gap_q += lost['q']
    gap_a += lost['a']
    if abs(gap_q) >= 0.5 or abs(gap_a) >= 0.5:
        print(f'  {gap_q:+,.0f} unit(s) and {gap_a:+,.0f} are unaccounted for - '
              f'that is a fault in this tool, not in the export',
              file=sys.stderr)
    _, _, _, oq, oa = made[1]
    print(f'  Online ASP.xlsx: {oq:,.0f} and {oa:,.0f}, the {args.channel} '
          f'share of it'
          + (f' ({oa / src["a"] * 100:.1f}% of net sales)' if src['a'] else ''))
    return 0 if abs(gap_q) < 0.5 and abs(gap_a) < 0.5 else 1


def check(rows, rrp, months, gst) -> None:
    """Is the RRP on the same footing as net sales? Say, rather than assume.

    A plan RRP is what a customer sees on a shelf, so it includes GST; net
    sales does not, and comparing the two straight overstates every discount by
    a flat ninth. That is the whole of the --gst flag, and a flag whose default
    is wrong quietly spoils a column, so the ratio is printed both ways and
    the count of materials that came out above their own RRP with it.
    """
    pairs = []
    for sku, v in rows.items():
        for m in months:
            q, a, r = v['qty'].get(m, 0.0), v['amt'].get(m, 0.0), rrp[sku][m]
            if q > 0 and a > 0 and r:
                pairs.append(a / q / r)
    if not pairs:
        print('  nothing has both a price and an RRP, so no discount can be '
              'worked out')
        return
    pairs.sort()
    mid = pairs[len(pairs) // 2]
    over = sum(1 for p in pairs if p > 1.0)
    print(f'  {len(pairs):,} material-month(s) have both a realised price and '
          f'an RRP')
    print(f'    median realised / RRP: {mid:.3f} as the plan writes it, '
          f'{mid * gst:.3f} with GST taken off at {gst:g}')
    print(f'    {over:,} ({over / len(pairs) * 100:.1f}%) sold above the RRP as '
          f'written' + (' - if that share is large the RRP is already ex GST, '
                        'so run with --gst 1' if over > len(pairs) * 0.2 else ''))


def write_book(path, title, rows, months, qk, ak, prod, rrp, promos, args):
    """One workbook: a row per material code, the months beside, ASP weighted."""
    span = f'{month_label(months[0])} - {month_label(months[-1])}'
    head = ['Material code', 'Description', 'Division', 'Category', 'Range']
    for m in months:
        s = short_month(m)
        head += [f'{s} qty', f'{s} net sales', f'{s} ASP', f'{s} RRP',
                 f'{s} DC %']
    head += [f'{span} qty', f'{span} net sales', f'ASP ({span})',
             f'RRP ({span})', f'DC % ({span})']
    promo_cols = [m for m in months if promos.get(m)]
    for m in promo_cols:
        head.append(f'{short_month(m)} promotion')

    body = []
    for sku, v in rows.items():
        q = sum(v[qk].get(m, 0.0) for m in months)
        a = sum(v[ak].get(m, 0.0) for m in months)
        if not q and not a:
            continue                   # this material is not in this workbook
        body.append((sku, prod.get(key_norm(sku)) or {}, v, q, a))
    # Biggest first, so the sheet opens on what matters. Sorted here because a
    # spreadsheet cannot sort itself without a volatile array formula.
    body.sort(key=lambda t: -abs(t[4]))

    n_m = len(months)
    # The month columns, named one by one. A SUMPRODUCT over every fifth column
    # would do the same and nobody opening the sheet could check it; =F2+K2+P2
    # is read at a glance and is right or wrong on sight.
    L = XL.col_letter
    q_cells = [L(6 + COLS_PER_MONTH * k) for k in range(n_m)]
    a_cells = [L(7 + COLS_PER_MONTH * k) for k in range(n_m)]
    p_cells = [L(8 + COLS_PER_MONTH * k) for k in range(n_m)]
    r_cells = [L(9 + COLS_PER_MONTH * k) for k in range(n_m)]
    s0 = 6 + COLS_PER_MONTH * n_m
    qcol, acol, pcol, rcol = L(s0), L(s0 + 1), L(s0 + 2), L(s0 + 3)
    gst = f'/{args.gst:g}' if args.gst != 1 else ''

    def discount(asp, r):
        return round(1 - asp / (r / args.gst), 4) if asp > 0 and r else ''

    out, blank, tot_q, tot_a = [head], 0, 0.0, 0.0
    for i, (sku, p, v, q, a) in enumerate(body, start=2):
        r = [sku, p.get('desc', ''), p.get('division', ''),
             p.get('category', ''), p.get('range', '')]
        w_num = w_den = 0.0
        for k, m in enumerate(months):
            mq, ma = v[qk].get(m, 0.0), v[ak].get(m, 0.0)
            mr = rrp[sku][m]
            asp = ma / mq if mq > 0 else 0.0
            # The month's own price, and how far under the RRP it landed. The
            # RRP is divided by GST in the cell rather than before it, so the
            # assumption is visible to whoever opens the sheet and can be
            # edited there instead of being argued about.
            r += [mq, ma,
                  XL.Formula(f'IF({q_cells[k]}{i}>0,'
                             f'{a_cells[k]}{i}/{q_cells[k]}{i},"")',
                             round(asp, 2) if mq > 0 else ''),
                  mr if mr else '',
                  XL.Formula(f'IF(AND({r_cells[k]}{i}>0,{p_cells[k]}{i}>0),'
                             f'1-{p_cells[k]}{i}/({r_cells[k]}{i}{gst}),"")',
                             discount(asp, mr))]
            if mr and mq > 0:
                w_num += mq * mr
                w_den += mq
        # The span's RRP is the months' own, weighted by the units each sold,
        # and over only the months that have one: a month with units and no RRP
        # left in the denominator would drag the average down and show a
        # discount nobody gave.
        wr = round(w_num / w_den, 2) if w_den > 0 else ''
        r += [XL.Formula('+'.join(f'{c}{i}' for c in q_cells), q),
              XL.Formula('+'.join(f'{c}{i}' for c in a_cells), a),
              # Weighted over the span, and blank rather than wrong where the
              # returns outweigh the sales - minus four hundred is not a price.
              XL.Formula(f'IF({qcol}{i}>0,{acol}{i}/{qcol}{i},"")',
                         round(a / q, 2) if q > 0 else ''),
              wr,
              XL.Formula(f'IF(AND({rcol}{i}>0,{pcol}{i}>0),'
                         f'1-{pcol}{i}/({rcol}{i}{gst}),"")',
                         discount(a / q if q > 0 else 0.0, wr or 0))]
        for m in promo_cols:
            r.append(promo_cell(promos[m].get(PM.code_norm(sku))))
        out.append(r)
        tot_q += q
        tot_a += a
        if q <= 0:
            blank += 1

    out.append([])
    out.append([f'{title}: ASP is net sales over net quantity for {span} taken '
                'together - the span\'s totals divided, not the average of the '
                f'{n_m} months\' own prices, which would let a quiet month '
                'weigh as much as a busy one. A material code whose returns '
                'outweigh its sales has no price and is left blank.'])
    out.append(['RRP is the plan\'s, for a plan line live in that month, and '
                'the product master\'s where the plan has none; the span\'s is '
                'the months\' own weighted by the units each sold. DC % is how '
                'far the price realised sits under it'
                + (f', with the RRP divided by {args.gst:g} first because a '
                   'plan RRP includes GST and net sales does not - the divisor '
                   'is in the cell, so change it there if that is wrong'
                   if args.gst != 1 else ' (the RRP is taken as already ex GST)')
                + '. Both are blank where no RRP was found.'])
    if promo_cols:
        out.append(['The promotion is the one most of the material\'s units ran '
                    'under in that month, read from the store\'s own orders, '
                    'with its share of those units where it was not all of '
                    'them. Most promoted units ran under more than one rule, so '
                    'a share below 100% means the rest ran under something '
                    'else, not that the label is uncertain. The store\'s orders '
                    'are its own channel: a material sold mainly elsewhere '
                    'shows the promotion its store units ran under, and nothing '
                    'about the rest.'])
    out.append(['Source: ' + ', '.join(month_label(m) for m in months)
                + ' profit exports - units and net sales are theirs alone, and '
                  'the plan and the store orders only label them'
                + ('' if title == 'Material' else f'; {args.channel} only')
                + f'. {len(body):,} material code(s), {tot_q:,.0f} net unit(s), '
                + f'{tot_a:,.0f} net sales.'])

    per = [XL.INT, XL.INT, XL.MONEY, XL.MONEY, XL.PCT]
    styles = ([XL.PLAIN] * 5 + per * n_m
              + [XL.INT, XL.INT, XL.MONEY, XL.MONEY, XL.PCT]
              + [XL.PLAIN] * len(promo_cols))
    widths = ([16, 30, 12, 16, 16] + [11, 14, 11, 11, 9] * n_m
              + [12, 16, 12, 12, 11] + [46] * len(promo_cols))
    XL.write(path, 'ASP', out, widths=widths, styles=styles, freeze='B2')
    return len(body), blank, tot_q, tot_a


if __name__ == '__main__':
    sys.exit(main())

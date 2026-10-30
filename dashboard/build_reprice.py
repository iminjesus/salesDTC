#!/usr/bin/env python3
"""What the month would have looked like priced off its own history.

    py dashboard\\build_reprice.py            # -> dashboard/REPRICE_<MONTH>.html
    py dashboard\\build_reprice.py --open

The P&L page measures October against the price the GSCM sheet planned it at,
and the gap is large. Most of it is not a discount anyone gave: it is a plan
written before the month was traded.

So this asks the counterfactual. `tools/reprice.py` builds the price the plan
could have carried instead - the list price in the promotion plan, discounted
by what the same campaign has been selling at over the last six months - and
this page puts the two side by side on the month that actually happened:

    plan      actual amount - GSCM price   x units sold
    re-priced actual amount - re-priced    x units sold

Same units, same months, same materials. The only thing that moves is the
price the month was measured against, so the difference between the two is
exactly what a better forecast would have been worth.

Nothing here changes what was sold. It is a measurement of the plan, not of
the month.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'tools'))

import plan_price as PP                                         # noqa: E402
import promo_match as PM                                        # noqa: E402
import reprice as RP                                            # noqa: E402
import sap as SAP                                               # noqa: E402
from asp import PRODUCT_KEYS                                    # noqa: E402
from rawdata import (MONTHS, find, master, parse_number,        # noqa: E402
                     pick_file, pick_series, read_any)

LEVELS = [('Biz', ('Biz', 'Business', 'Business Unit')),
          ('Div 1', ('Div 1', 'Div1', 'Division 1', 'Division')),
          ('Div 2', ('Div 2', 'Div2', 'Division 2')),
          ('Div 3', ('Div 3', 'Div3', 'Category', 'Prod_group'))]
TOP = 20


def actuals(folder: Path, ym: int, say=print) -> dict:
    """{code: [units, amount]} - every order the month took in.

    Order base: a line counts on the day it was placed, which is the basis the
    achievement table calls Order base. Rejections are out; returns and credits
    are out, because a negative line divided by a negative quantity is not a
    price.
    """
    short = str(ym)[-4:]
    files = [p for p in pick_series(folder, 'orders') if short in p.stem]
    if not files:
        say(f'  no orders_{short} in the folder - there is nothing to measure')
        return {}
    out: dict = {}
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
            say(f'  {path.name}: a column is missing - skipped')
            continue
        cell = lambda r, i: (r[i].strip() if i is not None and i < len(r) else '')
        for r in rows[1:]:
            lines += 1
            if cell(r, col['reject']):
                continue
            day = SAP.to_date(cell(r, col['made']))
            if day is None or day.year * 100 + day.month != ym:
                continue
            qty = parse_number(cell(r, col['qty'])) or 0.0
            amt = parse_number(cell(r, col['amt'])) or 0.0
            if qty <= 0 or amt <= 0:
                continue
            t = out.setdefault(PM.code_norm(cell(r, col['sku'])), [0.0, 0.0])
            t[0] += qty
            t[1] += amt
            used += 1
    say(f'  {used:,} of {lines:,} order line(s) placed in {ym}; '
        f'{len(out):,} material(s) sold')
    return out


def rows_for(priced: dict, sold: dict, levels: dict, say=print) -> list:
    """One row per material that was both planned and sold."""
    out, off, idle = [], [0, 0.0], 0
    for code, v in priced.items():
        got = sold.get(code)
        if not got or got[0] <= 0:
            idle += 1
            continue
        q, a = got
        chain = (levels.get(code) or {})
        out.append({
            'code': code,
            'chain': [chain.get(s) or (v['chain'][i] if i < len(v['chain'])
                                       else '') or '(blank)'
                      for i, (_, s) in enumerate(
                          (('Biz', 'biz'), ('Div 1', 'div1'),
                           ('Div 2', 'div2'), ('Div 3', 'div3')))],
            'qty': q, 'amt': a,
            'plan': v['gscm'], 'new': v['price'], 'how': v['how'],
            'rrp': v['rrp'], 'promo': v['promo_days'],
            'wasImpact': a - v['gscm'] * q,
            'nowImpact': a - v['price'] * q,
        })
    for code, got in sold.items():
        if code not in priced and got[0] > 0:
            off[0] += 1
            off[1] += got[1]
    say(f'  {len(out):,} material(s) were planned and sold; '
        f'{idle:,} planned and not sold; '
        f'{off[0]:,} sold with no plan line ({off[1]:,.0f})')
    return out


def tree(rows: list) -> list:
    """Biz / Div 1 / Div 2, each node carrying its own subtree's figures."""
    root: dict = {'kids': {}, 'qty': 0.0, 'amt': 0.0, 'plan': 0.0, 'new': 0.0}
    for r in rows:
        node = root
        path = []
        for name in r['chain'][:3]:
            # A level repeating the one above it is a spelling, not a step.
            if path and name == path[-1]:
                continue
            path.append(name)
            node['qty'] += 0          # the root is added below, once
            node = node['kids'].setdefault(
                name, {'name': name, 'kids': {}, 'qty': 0.0, 'amt': 0.0,
                       'plan': 0.0, 'new': 0.0, 'depth': len(path) - 1})
            node['qty'] += r['qty']
            node['amt'] += r['amt']
            node['plan'] += r['plan'] * r['qty']
            node['new'] += r['new'] * r['qty']
        root['qty'] += r['qty']
        root['amt'] += r['amt']
        root['plan'] += r['plan'] * r['qty']
        root['new'] += r['new'] * r['qty']
    flat = []

    def walk(node, key=''):
        for k in sorted(node['kids'].values(),
                        key=lambda n: n['amt'] - n['plan']):
            k['key'] = key + '/' + k['name']
            k['has'] = bool(k['kids'])
            flat.append(k)
            walk(k, k['key'])
    walk(root)
    return flat, root


def money(v):
    return f'{round(v):,}'


def signed(v):
    return ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(round(v)):,}'


def kilo(v):
    a = abs(v)
    return (f'{v / 1e6:.1f}M' if a >= 1e6
            else f'{round(v / 1000):,}K' if a >= 1000 else f'{round(v):,}')


def page(ym, rows, flat, root, note, cur='AUD') -> str:
    was_down = sum(r['wasImpact'] for r in rows if r['wasImpact'] < 0)
    now_down = sum(r['nowImpact'] for r in rows if r['nowImpact'] < 0)
    name = f'{MONTHS[(ym % 100) - 1]} {ym // 100}'
    best = sorted(rows, key=lambda r: r['wasImpact'] - r['nowImpact'])[:TOP]
    worst = max((abs(r['wasImpact'] - r['nowImpact']) for r in best), default=1)

    def cell(r, key):
        v = r[key]
        return (f'<td class="{"neg" if v < 0 else ""}">{signed(v)}</td>')

    def line(n, nm, depth, has, key, q, amt, plan, new):
        gap1, gap2 = amt - plan, amt - new
        pp = plan / q if q else 0
        np_ = new / q if q else 0
        ap = amt / q if q else 0
        return (f'<tr class="d{depth}">'
                + f'<td class="tree d{depth}" data-k="{html.escape(key)}" '
                + f'data-kids="{1 if has else 0}"><span class="tw">'
                + ('▾' if has else '') + f'</span>{html.escape(nm)}</td>'
                + f'<td>{money(q)}</td><td>{money(ap)}</td>'
                + f'<td>{money(pp)}</td><td>{money(np_)}</td>'
                + f'<td class="{"neg" if gap1 < 0 else ""}">{signed(gap1)}</td>'
                + f'<td class="{"neg" if gap2 < 0 else ""}">{signed(gap2)}</td>'
                + f'<td class="good">{signed(gap2 - gap1)}</td></tr>')

    body = ''.join(
        line(i, n['name'], n['depth'], n['has'], n['key'], n['qty'], n['amt'],
             n['plan'], n['new']) for i, n in enumerate(flat))
    total = line(-1, 'Total', 0, False, '', root['qty'], root['amt'],
                 root['plan'], root['new'])
    tops = ''.join(
        '<div class="r"><div class="nm"><i>%d.</i>%s</div>'
        '<div class="t"><i style="width:%.1f%%"></i></div>'
        '<div class="v">%s</div><div class="s">%s &rarr; %s</div></div>'
        % (i + 1, html.escape(r['code']),
           abs(r['wasImpact'] - r['nowImpact']) / worst * 100,
           signed(r['nowImpact'] - r['wasImpact']),
           money(r['plan']), money(r['new']))
        for i, r in enumerate(best))

    return TEMPLATE.replace('__TITLE__', f'{name} re-priced').replace(
        '__NOTE__', html.escape(note)).replace('__BODY__', body).replace(
        '__TOTAL__', total).replace('__TOPS__', tops).replace(
        '__CUR__', cur).replace('__MONTH__', name).replace(
        '__TOP__', str(len(best))).replace(
        '__KPI__', json.dumps([
            ['Negative price impact, as planned', kilo(-was_down), 'neg',
             f'{sum(1 for r in rows if r["wasImpact"] < 0):,} materials under '
             'their GSCM price'],
            ['Re-priced off six months', kilo(-now_down), 'neg',
             f'{sum(1 for r in rows if r["nowImpact"] < 0):,} materials still '
             'under the new price'],
            # Both totals are negative, so the improvement is the newer one
            # less the older: a smaller hole is a positive number.
            ['What the forecast was worth', kilo(now_down - was_down), 'good',
             'the same units, measured against a price built from what they '
             'had been selling at'],
        ]))


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { --bg:#f6f6f4; --surface:#fff; --line:#e3e3df; --grid:#efefeb;
  --ink:#1b1b19; --ink-2:#4a4a46; --ink-3:#8a8a84; --accent:#2a78d6;
  --neg:#d14343; --good:#128a5a; --chip:#fff; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#191918; --surface:#201f1e; --line:#35342f; --grid:#2a2926;
  --ink:#f2f0eb; --ink-2:#c9c6bf; --ink-3:#8f8c85; --accent:#3987e5;
  --neg:#f08a7a; --good:#4ec38c; --chip:#232321; } }
:root[data-theme="dark"] { --bg:#191918; --surface:#201f1e; --line:#35342f;
  --grid:#2a2926; --ink:#f2f0eb; --ink-2:#c9c6bf; --ink-3:#8f8c85;
  --neg:#f08a7a; --good:#4ec38c; --chip:#232321; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width:min(1760px,97vw); margin:0 auto; padding:14px 18px 36px; }
h1 { font-size:17px; margin:0; }
.sub { color:var(--ink-3); font-size:12px; margin:2px 0 12px; }
.card { background:var(--surface); border:1px solid var(--line);
  border-radius:10px; padding:10px 14px; margin-bottom:10px; }
.kpis { display:flex; flex-wrap:wrap; gap:10px; margin:2px 0 14px; }
.kpi { flex:1 1 220px; background:var(--chip); border:1px solid var(--line);
  border-radius:8px; padding:9px 12px; }
.kpi .k { font-size:11px; color:var(--ink-3); text-transform:uppercase;
  letter-spacing:.04em; }
.kpi .v { font-size:22px; font-weight:650; letter-spacing:-.01em; }
.kpi .v.neg { color:var(--neg); } .kpi .v.good { color:var(--good); }
.kpi .n { font-size:11px; color:var(--ink-3); margin-top:2px; }
table { border-collapse:collapse; width:100%; font-size:13px;
  font-variant-numeric:tabular-nums; }
th,td { padding:7px 10px; border-bottom:1px solid var(--grid);
  text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
thead th { color:var(--ink-3); font-weight:600; font-size:11px;
  text-transform:uppercase; letter-spacing:.04em; }
thead th.grp { text-align:center; background:var(--chip); color:var(--ink-2); }
th.gl, td.gl { border-left:1px solid var(--line); }
td.neg { color:var(--neg); } td.good { color:var(--good); font-weight:600; }
td.tree[data-kids="1"] { cursor:pointer; }
td.tree .tw { display:inline-block; width:14px; color:var(--ink-3);
  font-size:10px; }
td.d0 { font-weight:600; } td.d1 { padding-left:22px; }
td.d2 { padding-left:40px; color:var(--ink-2); }
tr.d0 td { border-top:1px solid var(--grid); }
tr.shut { display:none; }
tfoot td { font-weight:650; border-top:1px solid var(--line); }
.rank .r { display:grid; grid-template-columns:1.5fr 2fr auto 1.1fr;
  align-items:center; gap:10px; padding:5px 0;
  border-bottom:1px solid var(--grid); }
.rank .r:last-child { border-bottom:0; }
.rank .nm { font-size:12.5px; font-weight:600; }
.rank .nm i { font-style:normal; color:var(--ink-3); font-weight:500;
  margin-right:5px; }
.rank .t { position:relative; height:10px; border-radius:5px;
  background:var(--grid); overflow:hidden; }
.rank .t i { position:absolute; left:0; top:0; bottom:0; border-radius:5px;
  background:var(--good); }
.rank .v { font-size:12.5px; font-weight:650; color:var(--good);
  font-variant-numeric:tabular-nums; }
.rank .s { font-size:11.5px; color:var(--ink-3); text-align:right;
  font-variant-numeric:tabular-nums; }
.hint { font-size:12px; color:var(--ink-3); margin-top:10px; }
.chartHead { display:flex; align-items:baseline; gap:10px; margin-bottom:6px; }
.chartHead .t { font-size:13px; font-weight:600; }
.ctl { font:inherit; font-size:12px; padding:5px 8px; border-radius:7px;
  border:1px solid var(--line); background:var(--surface); color:var(--ink-2);
  cursor:pointer; margin-left:auto; }
</style></head><body><div class="wrap">
<h1>__MONTH__ re-priced</h1>
<div class="sub">__NOTE__</div>
<div class="card"><div class="kpis" id="kpis"></div></div>

<div class="card">
  <div class="chartHead"><span class="t">By division &middot; __CUR__</span>
    <button class="ctl" id="all">Expand all</button></div>
  <table>
    <thead>
      <tr><th rowspan="2">Product</th>
          <th class="grp gl" colspan="2">Actual</th>
          <th class="grp gl" colspan="2">Price</th>
          <th class="grp gl" colspan="3">Price impact</th></tr>
      <tr><th class="gl">Units</th><th>Sold at</th>
          <th class="gl">GSCM plan</th><th>Re-priced</th>
          <th class="gl">As planned</th><th>Re-priced</th><th>Better by</th></tr>
    </thead>
    <tbody id="rows">__BODY__</tbody>
    <tfoot>__TOTAL__</tfoot>
  </table>
  <div class="hint">A division's price is its materials' prices over the units
    actually sold, so every column is on the same mix and the two impacts
    differ only by the price. <b>Better by</b> is what the re-priced plan
    would have taken off the gap.</div>
</div>

<div class="card">
  <div class="chartHead"><span class="t">Top __TOP__ materials by what the
    re-price is worth</span></div>
  <div class="rank">__TOPS__</div>
  <div class="hint">The two prices beside each one are the GSCM plan and the
    re-price.</div>
</div>
</div>
<script>
const KPI = __KPI__;
document.getElementById('kpis').innerHTML = KPI.map(
  ([k, v, c, n]) => `<div class="kpi"><div class="k">${k}</div>`
    + `<div class="v ${c}">${v}</div><div class="n">${n}</div></div>`).join('');

/* The tree opens to the divisions and the rest is a click, the way the P&L
   page's tables do - seventeen product groups under two businesses is a wall
   of rows nobody reads. */
const rows = [...document.querySelectorAll('#rows tr')];
const shut = new Set();
function draw() {
  rows.forEach(tr => {
    const td = tr.querySelector('td.tree');
    const key = td.dataset.k;
    const hidden = [...shut].some(s => key.startsWith(s + '/'));
    tr.classList.toggle('shut', hidden);
    if (td.dataset.kids === '1') {
      td.querySelector('.tw').textContent = shut.has(key) ? '\\u25b8' : '\\u25be';
    }
  });
}
document.getElementById('rows').onclick = e => {
  const td = e.target.closest('td.tree');
  if (!td || td.dataset.kids !== '1') return;
  const k = td.dataset.k;
  if (shut.has(k)) shut.delete(k); else shut.add(k);
  draw();
};
document.getElementById('all').onclick = e => {
  if (shut.size) { shut.clear(); e.target.textContent = 'Collapse'; }
  else {
    rows.forEach(tr => { const td = tr.querySelector('td.tree');
      if (td.dataset.kids === '1' && td.classList.contains('d1')) {
        shut.add(td.dataset.k); } });
    e.target.textContent = 'Expand all';
  }
  draw();
};
// Opens on the divisions: everything under Div 1 is shut.
rows.forEach(tr => { const td = tr.querySelector('td.tree');
  if (td.dataset.kids === '1' && td.classList.contains('d1')) {
    shut.add(td.dataset.k); } });
draw();
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--month', type=int, default=None, metavar='YYMM')
    ap.add_argument('--back', type=int, default=6, metavar='N',
                    help='months of history behind the re-price (default 6)')
    ap.add_argument('--plan', nargs='+', default=list(PM.PLAN_STEMS),
                    metavar='STEM')
    ap.add_argument('--out', default=None)
    ap.add_argument('--open', action='store_true')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        raise SystemExit(f'no such folder: {folder.resolve()}')

    ym = args.month
    if ym is None:
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

    priced = RP.reprice(folder, full, args.back, args.plan)

    print(f'\nwhat {full} actually took in:')
    sold = actuals(folder, full)
    pp = pick_file(folder, 'product')
    levels = {}
    if pp is not None:
        raw = master(pp, PRODUCT_KEYS,
                     {'biz': LEVELS[0][1], 'div1': LEVELS[1][1],
                      'div2': LEVELS[2][1], 'div3': LEVELS[3][1]},
                     say=lambda *a: None)
        levels = {PM.code_norm(k): v for k, v in raw.items()}
    rows = rows_for(priced, sold, levels)
    if not rows:
        raise SystemExit('nothing was both planned and sold - there is '
                         'nothing to compare')

    flat, root = tree(rows)
    was = sum(r['wasImpact'] for r in rows if r['wasImpact'] < 0)
    now = sum(r['nowImpact'] for r in rows if r['nowImpact'] < 0)
    print(f'\n  negative price impact as planned:   {-was:>14,.0f}')
    print(f'  negative price impact re-priced:    {-now:>14,.0f}')
    print(f'  what the forecast was worth:        {now - was:>14,.0f}')

    note = (f'{len(rows):,} materials planned and sold · order base, '
            f'every line placed in the month · history over the '
            f'{args.back} months before it')
    out = Path(args.out) if args.out else HERE / (
        f'REPRICE_{MONTHS[(full % 100) - 1].upper()}.html')
    out.write_text(page(full, rows, flat, root, note), encoding='utf-8')
    print(f'\n-> {out.resolve()}  '
          f'({len(out.read_text(encoding="utf-8")) / 1024:,.0f} KB, '
          'works offline)')
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == '__main__':
    sys.exit(main())

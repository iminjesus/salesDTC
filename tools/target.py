#!/usr/bin/env python3
"""The month's target, split down to the customer, for the daily chart.

    py tools\\target.py                      # what it reads and how it splits

The target is the Sokbo (S0x) of the DTC Blue File, in AUD, by product group -
one number per product group for the month. The daily chart is by customer as
well, so the number is split before it is drawn:

    product group target  x  that group's customer mix over the last six months

The mix is each customer's share of the group's net sales, month by month,
averaged over the six months - an average of the monthly shares, so a month
with a big one-off does not outweigh the other five. A customer is the whole
chain the page drills, Channel -> Type -> Portal Group -> Type2.

On the page the month's target is divided evenly over the calendar days of the
month (31 for October) and drawn as a line over the daily bars. Narrow the page
and the line narrows with it, because it is a sum over the same keys.

Only the standard library, like the rest of the tools.
"""
from __future__ import annotations

import calendar
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import (INLINE, ROW, VAL, MONTHS,                     # noqa: E402
                     col_index, key_norm, norm_stem, parse_number,
                     pick_series, unescape)

# The Blue File's product rows, by the label in its hierarchy column, and the
# Div 3 names the product master has used for each. The first that is in the
# data wins; the build says which.
DIV3 = {
    'TV':       ('TV', 'CTV'),
    'MON':      ('Monitor', 'MON', 'LCD'),
    'SD':       ('AV', 'SD', 'Audio'),
    'EB':       ('LFD', 'EMON', 'EB'),
    'REF':      ('REF',),
    'WM':       ('WM', 'W/M', 'Laundry'),
    'MWO':      ('MWO',),
    'V/C':      ('VC', 'V/C'),
    'SAC':      ('SAC',),
    'RAC':      ('RAC',),
    'ACP':      ('Air Purifier', 'AIRCARE', 'ACP', 'Aircare'),
    'SMP':      ('Mobile', 'SMP', 'A_SMART', 'Smartphone'),
    'Wearable': ('Wearable',),
    'Tablet':   ('Tablet',),
    'APS':      ('Accessories', 'APS', 'Accessory'),
    'SC+':      ('SC+', 'Service'),
    'DS':       ('Memory', 'DS'),
}
MONTH_NO = {m.upper(): i + 1 for i, m in enumerate(MONTHS)}
CUSTOMER = ('Channel', 'Type', 'Portal Group', 'Type2')
PRODUCT = ('Biz', 'Div 1', 'Div 2', 'Div 3')
HISTORY = 6
ONLINE = 'E-STORE'          # customer.ONLINE: the channel the target is for
# A cell, empty or not. rawdata's pattern reads `<c .../>` as the opening of a
# cell with a body and runs on into the next one, which an export never has
# but a formatted workbook like the Blue File is full of.
CELL = re.compile(r'<c\b([^>]*?)(?:/>|>(.*?)</c>)', re.S)


# ── reading the Blue File ──────────────────────────────────────────────────

def read_sheet(path: Path, want: str) -> tuple[str, dict]:
    """One sheet as {(row, col): text}, 1-based, rows kept where they are.

    rawdata.read_xlsx reads the first sheet and drops empty rows, which is
    right for an export and wrong here: the Blue File is a layout, and the
    version is found by its row.
    """
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if 'xl/sharedStrings.xml' in names:
            xml = z.read('xl/sharedStrings.xml').decode('utf-8', 'replace')
            shared = [unescape(''.join(INLINE.findall(si)))
                      for si in re.findall(r'<si>(.*?)</si>', xml, re.S)]
        book = z.read('xl/workbook.xml').decode('utf-8', 'replace')
        rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8', 'replace')
        target = {m.group(1): m.group(2) for m in re.finditer(
            r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="([^"]+)"', rels)}
        target.update({m.group(2): m.group(1) for m in re.finditer(
            r'<Relationship[^>]*Target="([^"]+)"[^>]*Id="([^"]+)"', rels)})
        sheets = [(unescape(m.group(1)), m.group(2)) for m in re.finditer(
            r'<sheet[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', book)]
        if not sheets:
            raise ValueError(f'{path.name}: no sheets')
        # The AUD sheet, named however this cut names it.
        pick = next((s for s in sheets if norm_stem(want) in norm_stem(s[0])),
                    None)
        if pick is None:
            raise ValueError(f'{path.name}: no sheet named like {want!r} - it '
                             'has ' + ', '.join(s[0] for s in sheets))
        part = target[pick[1]].lstrip('/')
        part = part if part.startswith('xl/') else 'xl/' + part
        xml = z.read(part).decode('utf-8', 'replace')
    grid = {}
    for row_xml in ROW.findall(xml):
        for attrs, body in CELL.findall(row_xml):
            m = re.search(r'r="([A-Z]+)(\d+)"', attrs)
            if not m or not body:
                continue
            r = int(m.group(2))
            c = col_index(m.group(1)) + 1
            if 't="s"' in attrs:
                v = VAL.search(body or '')
                text = shared[int(v.group(1))] if v and v.group(1).isdigit() else ''
            elif 't="inlineStr"' in attrs:
                text = unescape(''.join(INLINE.findall(body or '')))
            else:
                v = VAL.search(body or '')
                text = unescape(v.group(1)) if v else ''
            if text.strip():
                grid[(r, c)] = text.strip()
    return pick[0], grid


def read_target(path: Path, version: str | None = None,
                sheet: str = 'AUD', say=print) -> dict | None:
    """{'ym', 'version', 'currency', 'groups': {label: amount}} off the Blue File.

    The version is the column whose version row (row 6) says it - S0A by
    default, read off the file name (DTC_S0A_T0B -> S0A). The month comes from
    the month row above it and the year from A4, the way the Blue File lays
    them out. Product rows are the leaf rows: a code in column C and the
    product label in the last of D-H.
    """
    if version is None:
        m = re.search(r'S0[1-9A-C]', path.stem.upper())
        version = m.group(0) if m else 'S0A'
    name, g = read_sheet(path, sheet)
    vrow = 6
    cols = [c for (r, c), v in g.items()
            if r == vrow and v.strip().upper() == version.upper()]
    if not cols:
        say(f'  {path.name} / {name}: no column says {version!r} in row {vrow}')
        return None
    col = min(cols)
    mon = MONTH_NO.get(g.get((5, col), '').strip()[:3].upper())
    year = parse_number(g.get((4, 1), ''))
    if not mon or not year:
        say(f'  {path.name} / {name}: cannot tell the month of {version} '
            f'(row 5 says {g.get((5, col))!r}, A4 says {g.get((4, 1))!r})')
        return None
    groups = {}
    last = max(r for r, _ in g)
    for r in range(7, last + 1):
        if not g.get((r, 3)) or g.get((r, 9), '').upper() != 'DTC':
            continue
        label = next((g[(r, c)] for c in (8, 7, 6, 5, 4) if g.get((r, c))), None)
        amount = parse_number(g.get((r, col), ''))
        if label is None or amount is None:
            continue
        groups[label] = groups.get(label, 0.0) + amount
    ym = int(year) * 100 + mon
    cur = 'AUD' if 'AUD' in name.upper() else ('USD' if 'USD' in name.upper()
                                                else '')
    say(f'  {path.name} / {name}: {version} for {MONTHS[mon - 1]} {int(year)}, '
        f'{len(groups)} product group(s), {sum(groups.values()):,.0f} {cur}')
    return {'ym': ym, 'version': version.upper(), 'currency': cur,
            'file': path.name, 'groups': groups}


def find_target(folder: Path, name: str | None) -> Path | None:
    """The Blue File cut to read: --target NAME, or the newest DTC_S* file."""
    if name:
        p = Path(name)
        if p.is_file():
            return p
        hits = pick_series(folder, name)
        return hits[0] if hits else None
    hits = [p for p in pick_series(folder, 'DTC_S')
            if p.suffix.lower() in ('.xlsx', '.xlsm')]
    return hits[0] if hits else None


# ── the split ──────────────────────────────────────────────────────────────

def split(target: dict, months: list, say=print) -> dict:
    """The target as rows on the page's own key, ready for the payload.

    `months` are the month payloads the build made - each with its levels
    by name, its series, and combinations indexing into them - so the mix is
    read off exactly the numbers the monthly chart draws, after the drops.
    """
    ym = target['ym']
    past = sorted((m for m in months if m.get('ym') and m['ym'] < ym),
                  key=lambda m: m['ym'])[-HISTORY:]
    if len(past) < HISTORY:
        say(f'  only {len(past)} closed month(s) before {ym} in the folder - '
            f'the mix is their average')
    if not past:
        say('  no closed month to read a mix from - the target is drawn '
            'whole, without a customer split')

    # Each Div 3's share by customer, summed over the months it sold in, and
    # how many months that was - the average is the one over the other. A
    # customer missing from a month the group sold in adds nothing to the sum
    # and still counts in the months, which is a share of nought.
    shares: dict = {}
    sold: dict = {}
    parents: dict = {}
    for m in past:
        names = [lv['name'] for lv in m['levels']]
        try:
            ci = [names.index(n) for n in CUSTOMER]
            pi = [names.index(n) for n in PRODUCT]
        except ValueError as e:
            say(f'  {m.get("file")}: {e} - left out of the mix')
            continue
        keys = [s['key'] for s in m['series']]
        vi = keys.index('net') if 'net' in keys else keys.index('gross')
        by: dict = {}
        for c in m['combos']:
            k = c['k']
            val = lambda i: m['levels'][i]['values'][k[i]]
            g = val(pi[3])
            cust = tuple(val(i) for i in ci)
            # The target is the online business only; an offline sale is
            # someone else's month and no part of the mix.
            if cust[0] != ONLINE:
                continue
            row = by.setdefault(g, {})
            row[cust] = row.get(cust, 0.0) + c['v'][vi]
            par = tuple(val(i) for i in pi[:3])
            pp = parents.setdefault(g, {})
            pp[par] = pp.get(par, 0.0) + c['v'][vi]
        for g, row in by.items():
            tot = sum(row.values())
            if not tot:
                continue                     # a month with nothing in it
            sold[g] = sold.get(g, 0) + 1
            sh = shares.setdefault(g, {})
            for cust, v in row.items():
                sh[cust] = sh.get(cust, 0.0) + v / tot

    div3 = {key_norm(g): g for g in set(shares) | set(parents)}
    rows, unsplit, nomatch = [], [], []
    for label, amount in sorted(target['groups'].items(), key=lambda kv: -kv[1]):
        if not amount:
            continue
        cands = DIV3.get(label, (label,))
        g = next((div3[key_norm(c)] for c in cands if key_norm(c) in div3), None)
        if g is None:
            nomatch.append((label, amount))
            rows.append({'k': [None] * 7 + [cands[0]], 'v': round(amount)})
            continue
        par = max(parents.get(g, {(None, None, None): 1}).items(),
                  key=lambda kv: kv[1])[0]
        mix = shares.get(g)
        if not mix:
            unsplit.append((label, amount))
            rows.append({'k': [None] * 4 + list(par) + [g], 'v': round(amount)})
            continue
        avg = {c: v / sold[g] for c, v in mix.items()}
        tot = sum(avg.values()) or 1.0
        for cust, s in avg.items():
            v = amount * s / tot
            if round(v):
                rows.append({'k': list(cust) + list(par) + [g], 'v': round(v)})

    total = sum(target['groups'].values())
    say(f'  mix over {", ".join(str(m["ym"]) for m in past) or "nothing"}; '
        f'{len(rows):,} target row(s), {sum(r["v"] for r in rows):,} of '
        f'{total:,.0f}')
    for label, amount in nomatch:
        say(f'    {label}: no Div 3 in the data matches it ({amount:,.0f}) - '
            'drawn only while the product chain is not narrowed')
    for label, amount in unsplit:
        say(f'    {label}: no sales in the mix months ({amount:,.0f}) - drawn '
            'only while the customer chain is not narrowed')
    y, mo = divmod(ym, 100)
    return {'ym': ym, 'version': target['version'],
            'currency': target['currency'], 'file': target['file'],
            'days': calendar.monthrange(y, mo)[1],
            'mix': [m['ym'] for m in past],
            'levels': list(CUSTOMER + PRODUCT), 'rows': rows}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--target', default=None, metavar='NAME')
    ap.add_argument('--version', default=None, metavar='S0x')
    args = ap.parse_args()
    p = find_target(Path(args.dir), args.target)
    if p is None:
        print('no DTC_S* Blue File in', Path(args.dir).resolve(), file=sys.stderr)
        return 2
    t = read_target(p, args.version)
    if t is None:
        return 1
    for label, v in sorted(t['groups'].items(), key=lambda kv: -kv[1]):
        print(f'    {label:<10} {v:>14,.0f}  -> Div 3 '
              f'{" / ".join(DIV3.get(label, (label,)))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

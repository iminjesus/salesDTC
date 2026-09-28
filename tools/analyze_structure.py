#!/usr/bin/env python3
"""Load rawdata/ into SQLite and work out which figures are sums of which.

    py tools\\analyze_structure.py                  # load, analyse, report
    py tools\\analyze_structure.py --no-db          # analyse only
    py tools\\analyze_structure.py --file profit_2608_2

A P&L export prints a total and then the lines that make it up, and nothing in
the file marks which is which - the asterisks in the header are a habit, not a
guarantee. So this reads the numbers instead. For every numeric column it looks
for a set of other columns that adds up to it *on every single row*, keeps only
the relations that hold exactly, and prints the result as a tree.

Three things come out of a run:

  rawdata/sales.db       every file as a typed SQLite table, plus the discovered
                         parent/child edges in a `structure` table
  docs/structure.md      the tree, with what was checked and how closely it held
  docs/structure.json    the same, for dashboard/build_pnl.py to draw

Nothing leaves the machine and no server is involved.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import (column_names, parse_number, pick_file,  # noqa: E402
                     pick_latest, read_any)      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# A currency column that is out by less than a cent is rounding, not a different
# number. Bigger figures carry proportionally bigger rounding, hence the ratio.
ABS_TOL = 0.01
REL_TOL = 1e-9

# How many rows the search runs on. Every relation the search proposes is then
# re-checked against all of them, so this only trades time, never correctness.
SAMPLE = 240
MAX_CHILDREN = 40


# ── reading ─────────────────────────────────────────────────────────────────
def column_profile(head: list[str], rows: list[list[str]]) -> list[dict]:
    """One entry per column: what it holds and whether it can be added up."""
    width = max(len(head), max((len(r) for r in rows), default=0))
    out = []
    for i in range(width):
        vals = [(r[i] if i < len(r) else '') for r in rows]
        filled = [v for v in vals if str(v).strip()]
        ok = [n for n in (parse_number(v) for v in filled) if n is not None]
        numeric = bool(filled) and len(ok) >= 0.9 * len(filled)
        distinct = len(set(filled))
        # One entry per row, not one per readable cell. A column with a single
        # blank in it used to come out shorter than its neighbours, which slid
        # every row after that blank against them and quietly broke the
        # arithmetic the whole analysis rests on.
        per_row = [(parse_number(v) or 0.0) if str(v).strip() else 0.0
                   for v in vals]
        out.append({
            'pos': i,
            'header': head[i].strip() if i < len(head) else f'col{i + 1}',
            'filled': len(filled),
            'distinct': distinct,
            'numeric': numeric,
            'values': per_row if numeric else None,
            'negatives': any(n < 0 for n in ok),
            'fractional': any(abs(n - round(n)) > 1e-9 for n in ok),
            'total': sum(ok) if numeric else None,
        })
    return out


# A customer number, a material code and a Nielsen id all parse as numbers and
# none of them is an amount. Adding them up would be meaningless, so they are
# named out; --include overrides this for a column that really is a figure.
ID_WORDS = re.compile(
    r'\b(sold[ _-]?to|payer|customer|material|profit[ _-]?center|nielsen|neilson'
    r'|account|vendor|plant|order|invoice|doc(ument)?|id|code|no\.?|number'
    r'|year|period|month|date|yyyymm|week|currency|forex|division|channel)\b',
    re.I)


def is_measure(c: dict, n_rows: int) -> bool:
    """Can this column sensibly be added up?

    An amount goes negative, or carries cents, or repeats across rows. An
    identifier does none of those - and usually says so in its name.
    """
    if not c['numeric'] or c['filled'] == 0:
        return False
    if c['distinct'] <= 1:                       # Year, Period, Currency
        return False
    if ID_WORDS.search(c['header']) and not c['fractional']:
        return False
    if c['negatives'] or c['fractional']:
        return True
    return c['distinct'] <= max(50, 0.3 * n_rows)   # integers, but not an id


def near(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))


# ── the search ──────────────────────────────────────────────────────────────
class Finder:
    """Which columns add up to which, judged only on the values."""

    def __init__(self, cols: list[dict], measures: list[int], n_rows: int):
        self.cols = cols
        self.measures = measures
        self.n_rows = n_rows
        # The search runs on a sample: the biggest rows, which are the ones a
        # wrong relation shows up in, plus a spread of ordinary ones.
        pick = max(measures, key=lambda i: abs(cols[i]['total'] or 0))
        order = sorted(range(n_rows),
                       key=lambda r: -abs(self.at(pick, r)))
        rest = order[SAMPLE // 2:]
        random.Random(0).shuffle(rest)
        self.sample = order[:SAMPLE // 2] + rest[:SAMPLE - SAMPLE // 2]
        self.svec = {i: [self.at(i, r) for r in self.sample] for i in measures}
        # The peeling search runs far more comparisons than the exact one, so it
        # scores on the biggest rows only. Everything it proposes is still
        # checked against the whole file before it counts.
        self.gsize = min(48, len(self.sample))
        self.memo: dict[int, tuple] = {}
        self.parents: dict[int, list[int]] = {}      # child -> totals it feeds
        self.kids_of: dict[int, list[int]] = {}      # total -> its lines

    def at(self, col: int, row: int) -> float:
        v = self.cols[col]['values']
        return v[row] if v and row < len(v) else 0.0

    def vec(self, col: int) -> list[float]:
        return self.svec[col]

    def would_cycle(self, total: int, kids: list[int]) -> bool:
        """Would making these the lines of `total` define it in terms of itself?

        `Gross Sales = Gross Sales AMT + Other` can be rearranged into
        `Gross Sales AMT = Gross Sales - Other`, which is true and useless. A
        column may not be explained by anything it is already part of.
        """
        seen, stack = set(), list(kids)
        while stack:
            k = stack.pop()
            if k == total:
                return True
            if k in seen:
                continue
            seen.add(k)
            stack.extend(self.parents.get(k, ()))
            stack.extend(self.kids_of.get(k, ()))
        return False

    def record(self, total: int, kids: list[int]) -> None:
        self.kids_of[total] = list(kids)
        for k in kids:
            self.parents.setdefault(k, []).append(total)

    def forget(self, total: int) -> None:
        for k in self.kids_of.pop(total, []):
            if total in self.parents.get(k, []):
                self.parents[k].remove(total)

    def verify(self, total: int, kids: list[int], signs: list[int]) -> float | None:
        """Largest gap over every row, or None if the relation ever breaks."""
        worst = 0.0
        for r in range(self.n_rows):
            want = self.at(total, r)
            got = sum(s * self.at(k, r) for k, s in zip(kids, signs))
            if not near(want, got):
                return None
            worst = max(worst, abs(want - got))
        return worst

    # -- the layout the file is printed in: a total, then its own lines -----
    def subtree(self, i: int, limit: int) -> tuple[list[int], int]:
        """Children of column i taken from the block that follows it.

        Returns the immediate children and the position just past the whole
        subtree, or ([], i+1) if the following columns do not add up to it.
        A child may itself be a total, in which case its own lines are skipped
        rather than double counted.
        """
        if i in self.memo:
            return self.memo[i]
        self.memo[i] = ([], i + 1)               # guards the recursion
        want = self.vec(i)
        if not any(want):
            return self.memo[i]
        acc = [0.0] * len(self.sample)
        kids: list[int] = []
        j = i + 1
        while j < limit and len(kids) < MAX_CHILDREN:
            if j not in self.measures:
                j += 1
                continue
            grand, end = self.subtree(j, limit)
            here = self.vec(j)
            for k in range(len(acc)):
                acc[k] += here[k]
            kids.append(j)
            j = end if grand else j + 1
            if all(near(a, w) for a, w in zip(acc, want)):
                worst = self.verify(i, kids, [1] * len(kids))
                if worst is not None:
                    self.memo[i] = (list(kids), j)
                    self.record(i, kids)
                    return self.memo[i]
        return self.memo[i]

    # -- anything the layout does not explain -------------------------------
    def try_combo(self, t: int, kids: tuple, signs: tuple) -> float | None:
        """Does this exact combination hold? Checked on the sample, then on all."""
        tv = self.svec[t]
        vs = [self.svec[k] for k in kids]
        for x in range(len(tv)):
            got = 0.0
            for v, sg in zip(vs, signs):
                got += sg * v[x]
            if not near(tv[x], got):
                return None
        if self.would_cycle(t, list(kids)):
            return None
        return self.verify(t, list(kids), list(signs))

    def combinations(self, t: int, pool: list[int], size: int):
        """Every set of `size` columns and every arrangement of their signs.

        Sizes are tried smallest first, so `net sales = gross - deductions` wins
        over any longer sum that happens to reach the same number.
        """
        import itertools
        pool = [j for j in pool if j != t]
        for kids in itertools.combinations(pool, size):
            for signs in itertools.product((1, -1), repeat=size):
                got = self.try_combo(t, kids, signs)
                if got is not None:
                    return list(kids), list(signs), got
        return None

    def greedy(self, t: int, pool: list[int]) -> tuple | None:
        """Peel columns off the remainder until nothing is left.

        The catch-all for a total whose lines are scattered through the row.
        Each step takes the column that shrinks the remainder most; a step that
        does not shrink it ends the search rather than guessing.
        """
        resid = self.svec[t][:self.gsize]
        scale = max((abs(v) for v in resid), default=0.0)
        if scale == 0:
            return None
        kids: list[int] = []
        signs: list[int] = []
        for _ in range(12):
            if all(abs(v) <= max(ABS_TOL, REL_TOL * scale) for v in resid):
                if not kids or self.would_cycle(t, kids):
                    return None
                got = self.verify(t, kids, signs)
                return (kids, signs, got) if got is not None else None
            here = sum(abs(v) for v in resid)
            best = None
            for j in pool:
                if j == t or j in kids:
                    continue
                v = self.svec[j]
                for sign in (1, -1):
                    m = 0.0
                    for x in range(self.gsize):
                        m += abs(resid[x] - sign * v[x])
                    if best is None or m < best[0]:
                        best = (m, j, sign)
            if best is None or best[0] >= here - ABS_TOL:
                return None
            _, j, sign = best
            v = self.svec[j]
            resid = [resid[x] - sign * v[x] for x in range(self.gsize)]
            kids.append(j)
            signs.append(sign)
        return None

    def explain(self, t: int, totals: list[int], measures: list[int],
                mode: str = 'strict'):
        """The simplest relation that holds exactly, or nothing.

        Order matters: a relation between two subtotals is the one an accountant
        would write, so it is tried before any longer sum of detail lines. The
        three-column pass is capped at the largest subtotals, because every
        column added multiplies the combinations to walk. `cheap` is for the
        later rounds, which only exist to catch a total that needed a subtotal
        the first round had not found yet.
        """
        big = sorted(totals, key=lambda j: -abs(self.cols[j]['total'] or 0))[:40]
        if mode == 'strict':
            # A statement prints a derived total after the lines it draws on, so
            # the first round only looks left. Without it, `gross margin = net
            # sales - cost of goods sold` is just as happily reported the other
            # way round - true, and backwards - and whichever is found first
            # blocks the other as a circular definition.
            totals = [j for j in totals if j < t]
            measures = [j for j in measures if j < t]
            big = [j for j in big if j < t]
        rounds = ([(totals, 2), (big, 3)] if mode == 'cheap'
                  else [(totals, 2), (measures, 2), (big, 3)])
        for pool, size in rounds:
            if len(pool) < size:
                continue
            hit = self.combinations(t, pool, size)
            if hit:
                return hit
        if mode == 'cheap':
            return None
        return self.greedy(t, [j for j in measures if j != t])



def analyse(cols: list[dict], measures: list[int], n_rows: int,
            say=print) -> list[dict]:
    """Every relation between the amount columns that holds on every row."""
    say('\nworking out which figures are sums of which...')
    f = Finder(cols, measures, n_rows)
    n_cols = len(cols)
    nodes: list[dict] = []
    for i in measures:
        kids, _ = f.subtree(i, n_cols)
        if kids:
            worst = f.verify(i, kids, [1] * len(kids))
            nodes.append({'pos': i, 'children': kids, 'signs': [1] * len(kids),
                          'how': 'block', 'max_diff': worst or 0.0})
    explained = {n['pos'] for n in nodes}
    claimed = {k for n in nodes for k in n['children']}
    # Only the figures the layout left standing on their own are worth a wider
    # search. A detail line that already feeds a total needs no explaining, and
    # searching one would only restate the total it belongs to.
    orphans = [i for i in measures if i not in explained and i not in claimed]
    say(f'  {len(nodes)} total(s) read straight off the layout, '
          f'{len(orphans)} column(s) left to place', flush=True)

    # Whatever the layout did not account for gets the wider search - a total
    # that is a difference, or whose lines sit elsewhere in the row. Each
    # relation found makes a new subtotal available to the next round.
    for attempt in range(4):
        totals = sorted(explained)
        found_any = False
        todo = [i for i in orphans if i not in explained]
        for n_done, i in enumerate(todo):
            if len(todo) > 24 and n_done and n_done % 24 == 0:
                say(f'    {n_done}/{len(todo)}', flush=True)
            hit = f.explain(i, totals, measures,
                            ('strict', 'loose', 'cheap', 'cheap')[attempt])
            if not hit:
                continue
            kids, signs, worst = hit
            kids, signs = order_terms(kids, signs)
            f.record(i, kids)
            nodes.append({'pos': i, 'children': kids, 'signs': signs,
                          'how': 'derived', 'max_diff': worst or 0.0})
            explained.add(i)
            found_any = True
        if not found_any:
            break

    # A relation found early could only draw on the subtotals known at the time,
    # so operating profit may have come out as a long sum of detail lines when
    # `gross margin less operating expense` was available by the end. With every
    # subtotal now known, take the shortest form of each.
    for n in nodes:
        if n['how'] != 'derived' or len(n['children']) <= 2:
            continue
        f.forget(n['pos'])
        hit = f.explain(n['pos'], sorted(explained - {n['pos']}), measures, 'loose')
        if hit and len(hit[0]) < len(n['children']):
            n['children'], n['signs'] = order_terms(hit[0], hit[1])
            n['max_diff'] = hit[2] or 0.0
        f.record(n['pos'], n['children'])
    nodes.sort(key=lambda n: n['pos'])

    found = len(nodes)
    leaves = len(measures) - found
    say(f'  {found} of {len(measures)} amount columns are the sum of others; '
          f'{leaves} are figures in their own right')

    return nodes


def order_terms(kids: list[int], signs: list[int]) -> tuple[list, list]:
    """What is added first, what is taken away after - the way it is written."""
    pairs = sorted(zip(kids, signs), key=lambda ks: (-ks[1], ks[0]))
    return [k for k, _ in pairs], [s for _, s in pairs]


# ── database ────────────────────────────────────────────────────────────────
def load_db(db: Path, tables: dict) -> None:
    """Every file as a typed table, with the original headers kept beside it.

    Columns that hold amounts become REAL so SQL can sum them; everything else
    stays TEXT, because a customer number with a leading zero is not a number.
    """
    conn = sqlite3.connect(db)
    conn.execute('DROP TABLE IF EXISTS column_map')
    conn.execute('CREATE TABLE column_map (table_name TEXT, pos INT, '
                 'header TEXT, column_name TEXT, type TEXT)')
    for table, (head, rows, cols) in tables.items():
        names = column_names([c['header'] for c in cols], len(cols))
        types = ['REAL' if c.get('measure') else 'TEXT' for c in cols]
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ('
                     + ', '.join(f'"{n}" {t}' for n, t in zip(names, types)) + ')')
        body = []
        for r in rows:
            out = []
            for i, t in enumerate(types):
                v = r[i].strip() if i < len(r) else ''
                out.append(parse_number(v) if t == 'REAL' else v)
            body.append(out)
        conn.executemany(f'INSERT INTO "{table}" VALUES '
                         f'({", ".join("?" * len(names))})', body)
        conn.executemany('INSERT INTO column_map VALUES (?,?,?,?,?)',
                         [(table, c['pos'], c['header'], n, t)
                          for c, n, t in zip(cols, names, types)])
        print(f'  {table}: {len(body):,} rows, {len(names)} columns '
              f'({sum(t == "REAL" for t in types)} numeric)')
    conn.commit()
    conn.close()


def save_edges(db: Path, table: str, nodes: list[dict], cols: list[dict]) -> None:
    conn = sqlite3.connect(db)
    conn.execute('DROP TABLE IF EXISTS structure')
    conn.execute('CREATE TABLE structure (table_name TEXT, parent TEXT, '
                 'child TEXT, sign INT, ordinal INT, how TEXT, max_diff REAL)')
    conn.executemany('INSERT INTO structure VALUES (?,?,?,?,?,?,?)', [
        (table, cols[n['pos']]['header'], cols[k]['header'], s, o,
         n['how'], n['max_diff'])
        for n in nodes
        for o, (k, s) in enumerate(zip(n['children'], n['signs']))])
    conn.commit()
    conn.close()


# ── reporting ───────────────────────────────────────────────────────────────
def build_tree(nodes: list[dict], measures: list[int]) -> tuple[list[int], list[int]]:
    """The totals nothing else claims, and the figures no total uses."""
    claimed = {k for n in nodes for k in n['children']}
    totals = {n['pos'] for n in nodes}
    roots = [i for i in measures if i not in claimed and i in totals]
    loose = [i for i in measures if i not in claimed and i not in totals]
    return roots, loose


def render(nodes: list[dict], cols: list[dict], roots: list[int]) -> list[str]:
    node_at = {n['pos']: n for n in nodes}
    lines: list[str] = []

    def walk(pos: int, depth: int, sign: int, seen: set) -> None:
        c = cols[pos]
        mark = '- ' if sign < 0 else ''
        amount = f"{c['total']:>18,.0f}" if c['total'] is not None else ' ' * 18
        node = node_at.get(pos)
        tag = ''
        if node:
            tag = ('   = the same figure' if len(node['children']) == 1
                   and node['signs'][0] > 0 else
                   f"   = {len(node['children'])} item(s)")
            if node['how'] == 'derived':
                tag += ' (not printed as a block)'
        lines.append(f"{amount}  {'    ' * depth}{mark}{c['header']}{tag}")
        if node and pos not in seen:
            seen = seen | {pos}
            for k, s in zip(node['children'], node['signs']):
                walk(k, depth + 1, s, seen)

    for r in roots:
        walk(r, 0, 1, set())
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata', help='folder holding the files')
    ap.add_argument('--file', default=None,
                    help='the export to analyse (default: the highest-numbered '
                         'profit_* file in the folder)')
    ap.add_argument('--db', default=None, help='SQLite file (default: <dir>/sales.db)')
    ap.add_argument('--no-db', action='store_true', help='skip the database')
    ap.add_argument('--json', default=str(ROOT / 'docs' / 'structure.json'))
    ap.add_argument('--md', default=str(ROOT / 'docs' / 'structure.md'))
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    target = (folder / args.file if args.file and (folder / args.file).is_file()
              else pick_file(folder, args.file) if args.file
              else pick_latest(folder, 'profit'))
    if target is None:
        print(f'no profit export found in {folder.resolve()}', file=sys.stderr)
        return 2

    print('reading:')
    # Everything in the folder, not just the three files the chart needs - the
    # point of the database is that whatever was dropped in can be queried.
    tables = {}
    others = sorted(p for p in folder.iterdir()
                    if p.is_file() and p != target
                    and p.suffix.lower() in ('.csv', '.txt', '.tsv', '.xlsx',
                                             '.xlsb', ''))
    for p in others:
        try:
            rows, info = read_any(p)
        except Exception as exc:
            print(f'  {p.name}: cannot read ({exc})')
            continue
        if not rows:
            print(f'  {p.name}: empty')
            continue
        cols = column_profile(rows[0], rows[1:])
        n_rows = len(rows) - 1
        for c in cols:
            # A column of amounts becomes REAL so SQL can sum it; a code stays
            # TEXT, because a customer number with a leading zero is not a
            # number. The profit export's own columns are judged by the
            # analysis below; these are judged here.
            c['measure'] = is_measure(c, n_rows)
        table = re.sub(r'[^0-9a-z]+', '_', p.stem.lower()).strip('_') or p.stem
        tables[table] = ([h.strip() for h in rows[0]], rows[1:], cols)
        print(f'  {p.name}: {info["format"]}, {info["encoding"]}, {n_rows:,} rows, '
              f'{len(cols)} columns -> table {table!r}')

    rows, info = read_any(target)
    head = [h.strip() for h in rows[0]]
    body = rows[1:]
    print(f'  {target.name}: {info["format"]}, {info["encoding"]}, {len(body):,} rows, '
          f'{len(head)} columns')

    cols = column_profile(head, body)
    measures = [c['pos'] for c in cols if is_measure(c, len(body))]
    for c in cols:
        c['measure'] = c['pos'] in measures
    dims = [c for c in cols if not c['measure']]

    print(f'\n{len(measures)} column(s) hold amounts; {len(dims)} describe the row:')
    print('  dimensions: ' + ', '.join(c['header'] for c in dims[:18])
          + (' ...' if len(dims) > 18 else ''))

    if not args.no_db:
        db = Path(args.db) if args.db else folder / 'sales.db'
        tables[target.stem.lower()] = (head, body, cols)
        print(f'\nsqlite -> {db.resolve()}')
        load_db(db, tables)

    nodes = analyse(cols, measures, len(body))

    roots, loose = build_tree(nodes, measures)
    lines = render(nodes, cols, roots)
    print('\n' + f"{'total':>18}  structure")
    print('-' * 78)
    for ln in lines[:80]:
        print(ln)
    if len(lines) > 80:
        print(f'  ... {len(lines) - 80} more line(s) - the whole tree is in {args.md}')
    if loose:
        print(f'\n{len(loose)} amount column(s) no total uses: '
              + ', '.join(cols[i]['header'] for i in loose[:12])
              + (' ...' if len(loose) > 12 else ''))

    md = Path(args.md)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(
        f'# {target.name} - what adds up to what\n\n'
        f'{len(body):,} rows, {len(head)} columns, {len(measures)} of them amounts.\n'
        'Every relation below was checked on every row; none of them is a guess '
        'from the column names.\n\n'
        '```\n' + f"{'total':>18}  structure\n" + '\n'.join(lines) + '\n```\n\n'
        + (('## Not part of any total\n\n'
            + '\n'.join(f"- `{cols[i]['header']}`" for i in loose) + '\n\n')
           if loose else '')
        + '## Relations\n\n'
        + '\n'.join(
            f"- `{cols[n['pos']]['header']}` = "
            + ' '.join(('+ ' if s > 0 else '- ') + f"`{cols[k]['header']}`"
                       for k, s in zip(n['children'], n['signs'])).lstrip('+ ')
            + f"  _(holds on all {len(body):,} rows, worst gap {n['max_diff']:.4f})_"
            for n in nodes) + '\n',
        encoding='utf-8')

    payload = {
        'file': target.name,
        'rows': len(body),
        'columns': [{'pos': c['pos'], 'header': c['header'], 'measure': c['measure'],
                     'total': round(c['total'], 2) if c['total'] is not None else None,
                     'distinct': c['distinct']} for c in cols],
        'nodes': [{'pos': n['pos'], 'header': cols[n['pos']]['header'],
                   'children': n['children'], 'signs': n['signs'],
                   'how': n['how'], 'max_diff': n['max_diff']} for n in nodes],
        'roots': roots,
        'loose': loose,
    }
    Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                               encoding='utf-8')
    if not args.no_db:
        save_edges(Path(args.db) if args.db else folder / 'sales.db',
                   target.stem.lower(), nodes, cols)
    print(f'\n-> {md}\n-> {args.json}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

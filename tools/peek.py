#!/usr/bin/env python3
"""What is actually in a file: its columns, with letters, and a few rows.

    py tools\\peek.py target
    py tools\\peek.py orders --rows 5
    py tools\\peek.py profit --find commission

Three times in a row now a question has turned on a column nobody could name
from memory - which letter the commission sat in, what the order export calls
its dates, what a target file is keyed on - and each time the answer took a
round trip. This prints the file instead: the format it is really in, how many
rows and columns, every header with its spreadsheet letter, and the first rows
laid out down the page so a value lines up with the header it belongs to.

The name is a prefix, resolved the way every other tool resolves one, so
`target` finds `target_2610.csv` and the newest cut of a series wins.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rawdata import pick_file, pick_series, read_any       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def col_letter(i: int) -> str:
    """The spreadsheet letter of a 0-based column, so A is 0 and AK is 36."""
    out, n = '', i + 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def looks_empty(v: str) -> bool:
    return not str(v or '').strip()


def peek(path: Path, rows: int, find: str, say=print) -> None:
    body, info = read_any(path)
    if not body:
        say(f'{path.name}: empty')
        return
    head = [h.strip() for h in body[0]]
    data = body[1:]
    say(f'\n{path.name}: {info.get("format", "?")}, {len(data):,} row(s), '
        f'{len(head)} column(s)')
    hit = [t.strip().lower() for t in find.split(',') if t.strip()]
    # Down the page rather than across it: a row of forty values wraps in a
    # terminal and stops lining up with its header, which is the one thing
    # this is for.
    show = data[:rows]
    wide = max([6] + [len(h) for h in head])
    say('  ' + 'col'.rjust(4) + '  ' + 'header'.ljust(wide)
        + ''.join(f'  {"row " + str(i + 1):<22}' for i in range(len(show))))
    for i, h in enumerate(head):
        mark = '  <--' if hit and any(t in h.lower() for t in hit) else ''
        line = f'  {col_letter(i):>4}  {(h or "(blank)"):<{wide}}'
        for r in show:
            v = r[i].strip() if i < len(r) else ''
            line += f'  {(v or "-")[:20]:<22}'
        say(line.rstrip() + mark)
    # A column that is empty everywhere is the one that gets picked by name and
    # then charts as zero, so it is worth saying before anyone reads it.
    blank = [col_letter(i) + ' ' + (head[i] or '(blank)')
             for i in range(len(head))
             if all(looks_empty(r[i] if i < len(r) else '') for r in data)]
    if blank:
        say(f'\n  empty in every row: {", ".join(blank[:12])}'
            + (f' and {len(blank) - 12} more' if len(blank) > 12 else ''))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('name', nargs='*',
                    help='the file, by name or by prefix; with none, every '
                         'file in the folder is listed')
    ap.add_argument('--dir', default='rawdata')
    ap.add_argument('--rows', type=int, default=3, metavar='N',
                    help='how many rows to show (default 3)')
    ap.add_argument('--find', default='', metavar='WORD',
                    help='mark the headers containing this, comma-separated')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_absolute():
        folder = ROOT / folder
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2
    if not args.name:
        print(f'{folder.resolve()}')
        for p in sorted(folder.iterdir()):
            if p.is_file():
                print(f'  {p.name:<40}{p.stat().st_size / 1024:>10,.0f} KB')
        print('\nname one of them to see its columns.')
        return 0
    for name in args.name:
        path = pick_file(folder, name)
        if path is None:
            near = [p.name for p in folder.iterdir()
                    if p.is_file() and name.lower()[:4] in p.name.lower()]
            print(f'\nno file like {name!r} in {folder.resolve()}'
                  + (f' - did you mean {", ".join(near[:5])}?' if near else ''))
            continue
        other = [p.name for p in pick_series(folder, name)[1:4]]
        try:
            peek(path, max(0, args.rows), args.find)
        except (ValueError, OSError) as e:
            print(f'\n{path.name}: {e}')
            continue
        if other:
            print(f'  also matching {name!r}: {", ".join(other)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

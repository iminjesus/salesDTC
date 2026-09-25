#!/usr/bin/env python3
"""Read the files in rawdata/ directly - no database server, no LOAD DATA.

    py tools\\rawdata.py                    # look at rawdata\\ and report what is there
    py tools\\rawdata.py --sqlite           # also load everything into rawdata\\sales.db
    py tools\\rawdata.py --clean-csv        # also write tidy UTF-8 csvs to rawdata\\clean\\

What it handles, by looking at the bytes rather than the file extension:

  * text files - comma, tab, semicolon or pipe separated, CRLF/LF/CR line endings,
    UTF-8 (with or without a byte order mark), UTF-16, Windows ANSI (cp1252) or
    Korean ANSI (cp949). A .csv that is really one of these is read correctly
    whatever it is named.
  * .xlsx workbooks, including one misnamed .csv - read straight from the zip,
    no Excel and no third-party library.
  * .xlsb workbooks - these need `py -m pip install pyxlsb`; the script says so
    rather than failing obscurely.

With --sqlite you get a single file you can query with ordinary SQL, no server
and nothing to install:

    py -c "import sqlite3;c=sqlite3.connect(r'rawdata\\sales.db');print(c.execute('select count(*) from customer_2608').fetchone())"

DB Browser for SQLite opens the same file if you would rather click around.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ENCODINGS = ('utf-8-sig', 'utf-8', 'cp1252', 'cp949', 'latin-1')
DELIMS = (',', '\t', ';', '|')


# ── what is this file, really ───────────────────────────────────────────────
def sniff_kind(path: Path) -> str:
    head = path.open('rb').read(8)
    if head[:2] == b'PK':
        return 'zip'                       # xlsx / xlsb / anything else zipped
    if head[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        return 'xls'                       # pre-2007 binary workbook
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return 'utf16'
    return 'text'


def decode(raw: bytes) -> tuple[str, str]:
    """Return (text, encoding name). UTF-16 is detected by its byte order mark."""
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16'), 'utf-16'
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        # cp1252 and latin-1 decode any byte at all, so only accept them when the
        # result has no control characters - that is what a binary file looks like.
        # Tab, newline and carriage return are of course fine.
        if enc in ('cp1252', 'cp949', 'latin-1'):
            ctrl = sum(1 for ch in text[:4000]
                       if ord(ch) < 32 and ch not in '\t\n\r')
            if ctrl:
                continue
        return text, enc
    return raw.decode('latin-1'), 'latin-1 (fallback)'


def sniff_delim(header: str) -> str:
    counts = {d: header.count(d) for d in DELIMS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ','


def read_text_table(path: Path) -> tuple[list[list[str]], dict]:
    raw = path.read_bytes()
    text, enc = decode(raw)
    newline = '\r\n' if '\r\n' in text else ('\r' if '\r' in text else '\n')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    delim = sniff_delim(text.split('\n', 1)[0])
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    return rows, {'format': 'text', 'encoding': enc, 'delimiter': delim,
                  'line_ending': {'\r\n': 'CRLF', '\n': 'LF', '\r': 'CR'}[newline]}


# ── xlsx, straight out of the zip ───────────────────────────────────────────
CELL = re.compile(r'<c\b([^>]*)>(.*?)</c>|<c\b([^>]*)/>', re.S)
ROW = re.compile(r'<row\b[^>]*>(.*?)</row>', re.S)
VAL = re.compile(r'<v>(.*?)</v>', re.S)
INLINE = re.compile(r'<t[^>]*>(.*?)</t>', re.S)
REF = re.compile(r'r="([A-Z]+)\d+"')


def unescape(s: str) -> str:
    return (s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
             .replace('&apos;', "'").replace('&amp;', '&'))


def col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(path: Path) -> tuple[list[list[str]], dict]:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if not any(n.startswith('xl/worksheets/') for n in names):
            raise ValueError('zip, but not an xlsx workbook')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            xml = z.read('xl/sharedStrings.xml').decode('utf-8', 'replace')
            shared = [unescape(''.join(INLINE.findall(si)))
                      for si in re.findall(r'<si>(.*?)</si>', xml, re.S)]
        sheet = sorted(n for n in names if re.match(r'xl/worksheets/sheet\d+\.xml$', n))[0]
        xml = z.read(sheet).decode('utf-8', 'replace')

    rows = []
    for row_xml in ROW.findall(xml):
        cells: dict[int, str] = {}
        for attrs, body, attrs_empty in CELL.findall(row_xml):
            attrs = attrs or attrs_empty
            m = REF.search(attrs)
            idx = col_index(m.group(1)) if m else len(cells)
            if 't="s"' in attrs:
                v = VAL.search(body or '')
                cells[idx] = shared[int(v.group(1))] if v and v.group(1).isdigit() else ''
            elif 't="inlineStr"' in attrs:
                cells[idx] = unescape(''.join(INLINE.findall(body or '')))
            else:
                v = VAL.search(body or '')
                cells[idx] = unescape(v.group(1)) if v else ''
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, '') for i in range(width)])
    rows = [r for r in rows if any(c.strip() for c in r)]
    return rows, {'format': 'xlsx', 'encoding': 'utf-8', 'delimiter': '-',
                  'line_ending': '-'}


def read_xlsb(path: Path) -> tuple[list[list[str]], dict]:
    try:
        from pyxlsb import open_workbook
    except ImportError:
        raise ValueError('this is an .xlsb workbook - run "py -m pip install pyxlsb", '
                         'or open it in Excel and Save As "CSV UTF-8"')
    rows = []
    with open_workbook(str(path)) as wb:
        with wb.get_sheet(1) as sheet:
            for row in sheet.rows():
                values = ['' if c.v is None else str(c.v) for c in row]
                if any(v.strip() for v in values):
                    rows.append(values)
    return rows, {'format': 'xlsb', 'encoding': '-', 'delimiter': '-', 'line_ending': '-'}


def read_any(path: Path) -> tuple[list[list[str]], dict]:
    kind = sniff_kind(path)
    if kind == 'zip':
        try:
            return read_xlsx(path)
        except ValueError:
            return read_xlsb(path)         # .xlsb is zipped too
    if kind == 'xls':
        raise ValueError('pre-2007 .xls workbook - open it in Excel and '
                         'Save As "CSV UTF-8"')
    return read_text_table(path)


# ── tidying and output ──────────────────────────────────────────────────────
def column_names(header: list[str], width: int) -> list[str]:
    names, seen = [], {}
    for i in range(width):
        raw = header[i].strip() if i < len(header) else ''
        name = re.sub(r'[^0-9a-zA-Z]+', '_', raw).strip('_').lower() or f'col{i + 1}'
        if name[0].isdigit():
            name = 'c_' + name
        seen[name] = seen.get(name, 0) + 1
        names.append(name if seen[name] == 1 else f'{name}_{seen[name]}')
    return names


def to_sqlite(conn, table: str, names: list[str], body: list[list[str]]) -> int:
    cols = ', '.join(f'"{n}" TEXT' for n in names)
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(f'CREATE TABLE "{table}" ({cols})')
    marks = ', '.join('?' * len(names))
    conn.executemany(f'INSERT INTO "{table}" VALUES ({marks})',
                     [(r + [''] * len(names))[:len(names)] for r in body])
    conn.commit()
    return len(body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default='rawdata', help='folder to read (default: rawdata)')
    ap.add_argument('--sqlite', nargs='?', const='', metavar='DB',
                    help='load every file into this SQLite database '
                         '(default: <dir>/sales.db)')
    ap.add_argument('--clean-csv', action='store_true',
                    help='also write tidy UTF-8 csvs to <dir>/clean/')
    ap.add_argument('--rows', type=int, default=3, help='sample rows to print')
    args = ap.parse_args()

    folder = Path(args.dir)
    if not folder.is_dir():
        print(f'no such folder: {folder.resolve()}', file=sys.stderr)
        return 2

    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in
                   ('.csv', '.txt', '.tsv', '.xlsx', '.xlsb', '.xls', ''))
    if not files:
        print(f'no data files in {folder.resolve()}')
        return 1

    conn = None
    if args.sqlite is not None:
        db = Path(args.sqlite) if args.sqlite else folder / 'sales.db'
        conn = sqlite3.connect(db)
        print(f'sqlite -> {db.resolve()}\n')

    clean_dir = folder / 'clean'
    if args.clean_csv:
        clean_dir.mkdir(exist_ok=True)

    for path in files:
        size = path.stat().st_size / 1024
        print(f'== {path.name}  ({size:,.0f} KB)')
        try:
            rows, info = read_any(path)
        except Exception as exc:
            print(f'   cannot read: {exc}\n')
            continue
        if not rows:
            print('   empty\n')
            continue

        header, body = rows[0], rows[1:]
        width = max(len(r) for r in rows)
        names = column_names(header, width)
        print(f"   {info['format']}, {info['encoding']}, "
              f"separator {info['delimiter']!r}, {info['line_ending']}")
        print(f'   {len(body):,} rows x {width} columns')
        print(f"   columns: {', '.join(names)}")
        for r in body[:args.rows]:
            cells = [(c[:18] + '…') if len(c) > 19 else c for c in r[:8]]
            print('     ' + ' | '.join(cells))

        table = re.sub(r'[^0-9a-zA-Z]+', '_', path.stem).strip('_').lower()
        if conn is not None:
            n = to_sqlite(conn, table, names, body)
            print(f'   -> sqlite table "{table}" ({n:,} rows)')
        if args.clean_csv:
            out = clean_dir / f'{table}.csv'
            with out.open('w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(names)
                w.writerows(body)
            print(f'   -> {out}')
        print()

    if conn is not None:
        tables = [r[0] for r in conn.execute(
            "select name from sqlite_master where type='table' order by name")]
        print('tables:', ', '.join(tables))
        conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())

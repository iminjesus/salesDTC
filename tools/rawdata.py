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
import math
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


def find(headers: list[str], *candidates: str) -> int | None:
    """Index of the first header matching one of these names.

    By name, not position, and ignoring case, spaces and punctuation - the same
    column arrives as `Sold-To`, `sold To` and `Sold_To` in different exports.
    """
    lookup = {re.sub(r'[^a-z0-9]', '', h.lower()): i for i, h in enumerate(headers)}
    for c in candidates:
        key = re.sub(r'[^a-z0-9]', '', c.lower())
        if key in lookup:
            return lookup[key]
    return None


def key_norm(v) -> str:
    """Match keys across exports that disagree about padding and case.

    SAP writes the same customer as 2234755 in one extract and 0002234755 in
    the next, and a spreadsheet round-trip can leave 2234755.0 behind. All
    three have to land on the same customer.
    """
    t = str(v or '').strip().upper()
    if t.endswith('.0') and t[:-2].isdigit():
        t = t[:-2]
    if t.isdigit():
        t = t.lstrip('0') or '0'
    return t


MASTER_RAW: dict[str, tuple] = {}     # file name -> (header, rows), for diagnostics


def master(path: Path, key_names: tuple, wanted: dict, say=print) -> dict:
    """One row per key, built from the first row that fills each column.

    The same Sold-To is listed more than once, and the repeats are often a stub
    with the detail columns empty. Taking the last row wins meant a stub could
    blank out a real account - which is how a whole Type2 disappears from a
    filter while plainly sitting in the file. So each column is filled from the
    first row that has anything in it, and a later row that disagrees is
    reported rather than applied.
    """
    rows, _ = read_any(path)
    head = [h.strip() for h in rows[0]]
    MASTER_RAW[path.name] = (head, rows[1:])
    k = find(head, *key_names)
    if k is None:
        return {}
    cols = {slot: find(head, *names) for slot, names in wanted.items()}
    out: dict[str, dict] = {}
    repeats = 0
    clashes: dict[str, set] = {}
    for r in rows[1:]:
        key = key_norm(r[k] if k < len(r) else '')
        if not key:
            continue
        row = {s: (r[i].strip() if i is not None and i < len(r) else '')
               for s, i in cols.items()}
        prev = out.get(key)
        if prev is None:
            out[key] = row
            continue
        repeats += 1
        for slot, v in row.items():
            if not v:
                continue
            if not prev[slot]:
                prev[slot] = v
            elif prev[slot] != v:
                clashes.setdefault(key, set()).add(f'{slot} {prev[slot]} / {v}')
    if repeats:
        say(f'  {repeats:,} repeated key(s) in {path.name}; each column is taken '
            f'from the first row that fills it'
            + (f', and {len(clashes):,} key(s) disagreed - the later value was '
               'left:' if clashes else ''))
        for key, variants in list(sorted(clashes.items()))[:5]:
            say(f'    {key}: ' + '  |  '.join(sorted(variants)))
        if len(clashes) > 5:
            say(f'    ... and {len(clashes) - 5:,} more')
    return out


def norm_stem(s) -> str:
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


# The exports are named and dated by month, and a tool that reads two of them
# has to know it is reading the same month twice. One definition, so the page
# and the tests that check it cannot disagree about which month is which.
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def month_of(head: list[str], body: list[list[str]], name: str, say=print):
    """The month an export covers, as YYYYMM.

    From the export's own column where it has one, since that is the month the
    rows are in; from the digits in the file name otherwise, which is what the
    person who exported it meant.
    """
    i = find(head, 'YYYYMM', 'Year Month', 'Period', 'Fiscal Period')
    if i is not None:
        seen: dict[int, int] = {}
        for row in body:
            v = re.sub(r'\D', '', row[i] if i < len(row) else '')
            if len(v) == 6:
                n = int(v)
                seen[n] = seen.get(n, 0) + 1
        if seen:
            best = max(seen, key=seen.get)
            if len(seen) > 1 and body:
                say(f'  {len(seen)} different months in {head[i]!r}; {best} '
                    f'holds {seen[best] / len(body) * 100:.0f}% of the rows and '
                    'is taken as the month')
            return best
    # A six-digit run is already YYYYMM; a four-digit one is YYMM, which is how
    # these files are named - profit_2609 is September 2026, not the year 2609.
    six = re.findall(r'(?<!\d)(20\d{4})(?!\d)', name)
    if six:
        return int(six[0])
    four = re.findall(r'(?<!\d)(\d{4})(?!\d)', name)
    for v in four:
        if 1 <= int(v) % 100 <= 12:
            return 2000 * 100 + int(v)
    return None


def month_name(ym: int, series: str = '26 DTC') -> str:
    """'26 DTC Sep' for 202609 - how these exports have been named."""
    return f'{str(ym // 100)[-2:]} DTC {MONTHS[(ym % 100) - 1]}'


def month_before(ym: int) -> int:
    return ym - 1 if ym % 100 > 1 else (ym // 100 - 1) * 100 + 12


def pick_amount(head: list[str], names: tuple, prefer: str | None = None):
    """Which money column to read, when the export carries several currencies.

    An order export can hold both `AUD Revenue excl. GST` and `USD Revenue excl.
    GST`, and taking whichever is listed first would pair one currency against
    another without a word. So the choice can be steered by the currency the
    other side is in, and the caller is handed the alternatives to print.
    """
    hits = [(n, find(head, n)) for n in names]
    hits = [(n, i) for n, i in hits if i is not None]
    if not hits:
        return None, []
    if prefer:
        want = prefer.strip().upper()
        for n, i in hits:
            if want in head[i].upper():
                return i, [head[j] for _, j in hits]
    return hits[0][1], [head[j] for _, j in hits]


def currency_of(column: str | None) -> str | None:
    """'USD' from 'USD Revenue excl. GST', when the name says so at all."""
    if not column:
        return None
    for code in ('AUD', 'USD', 'KRW', 'EUR', 'GBP', 'JPY', 'NZD', 'SGD'):
        if re.search(rf'(?<![A-Z]){code}(?![A-Z])', column.upper()):
            return code
    return None


def pick_file(folder: Path, *stems: str):
    """The file named like one of these stems, exact match first."""
    for stem in stems:
        hits = sorted(p for p in folder.iterdir()
                      if p.is_file() and norm_stem(p.stem) == norm_stem(stem))
        if hits:
            return hits[0]
    for stem in stems:
        hits = sorted(p for p in folder.iterdir()
                      if p.is_file() and norm_stem(p.stem).startswith(norm_stem(stem)))
        if hits:
            return hits[0]
    return None


def pick_latest(folder: Path, prefix: str):
    """The newest export of a series: profit_2608_3 over profit_2608_1.

    The exports get re-cut and renamed, so the numbers in the name decide -
    read left to right, as many as there are. Nothing in the tools needs
    editing when the next one lands.
    """
    hits = [p for p in folder.iterdir()
            if p.is_file() and norm_stem(p.stem).startswith(norm_stem(prefix))
            and p.suffix.lower() != '.db']
    if not hits:
        return None
    def rank(p):
        return ([int(n) for n in re.findall(r'\d+', p.stem)], p.name)
    return max(hits, key=rank)


def parse_number(v) -> float | None:
    """The number a cell holds, or None if it does not hold one.

    Amounts leave SAP and Excel in several shapes: 1,234.56 with separators,
    (1,234.56) in accounting form, 1234.56- with the sign trailing, and the odd
    $ or stray space. Everything else - '#N/A', a blank, a description - is not
    a number and says so rather than counting as zero.

    That includes 'NaN' and 'inf', which a broken formula leaves behind and
    float() accepts without complaint. They are not amounts: summing them
    poisons a whole column, and rounding one raises.
    """
    t = str(v or '').strip().replace(',', '').replace('$', '').replace(' ', '')
    if not t or t in ('-', '#N/A', 'N/A', 'NULL', '#DIV/0!', '#REF!'):
        return None
    if t.startswith('(') and t.endswith(')'):
        t = '-' + t[1:-1]
    elif t.endswith('-'):                      # SAP trailing sign: 1234.56-
        t = '-' + t[:-1]
    elif t.endswith('+'):
        t = t[:-1]
    try:
        n = float(t)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


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

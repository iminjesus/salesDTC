#!/usr/bin/env python3
"""Write a workbook, with nothing but the standard library.

An .xlsx is a zip of XML, and `rawdata.py` already reads one that way, so
writing one needs no package either. That matters here: this toolchain runs
where installing things is not an option, and a report nobody can generate is
not a report.

What it supports is what the reports need and no more - one sheet, a styled
header, numbers, text, formulas, column widths, a frozen top row and a filter.
Formulas are written without a cached value, so Excel computes them on open;
anything reading the file without opening it sees an empty cell, which is why
the totals are also passed in and checked by the caller rather than trusted
from here.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

ESC = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;'}
# XML 1.0 forbids most control characters outright - a stray one in a product
# description makes the whole workbook unopenable rather than that one cell odd.
BAD = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def esc(v) -> str:
    return BAD.sub('', ''.join(ESC.get(c, c) for c in str(v)))


def col_letter(n: int) -> str:
    """1 -> A, 27 -> AA."""
    s = ''
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Formula(str):
    """A formula, with the value it comes to.

    Both go in the cell, which is how Excel stores one itself: the sheet
    recalculates when its inputs change, and anything reading the file without
    opening it - a previewer, a script, pandas - still sees the number instead
    of a blank. Written with the formula alone, every computed cell reads as
    empty until something opens the workbook and recalculates it.
    """

    def __new__(cls, text, value=None):
        s = super().__new__(cls, text)
        s.value = value
        return s


# style ids the sheet refers to by index into cellXfs, below
PLAIN, HEADER, INT, MONEY, NOTE = 0, 1, 2, 3, 4

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="2">
  <numFmt numFmtId="164" formatCode="#,##0;(#,##0);-"/>
  <numFmt numFmtId="165" formatCode="#,##0.00;(#,##0.00);-"/>
</numFmts>
<fonts count="4">
  <font><sz val="11"/><name val="Arial"/></font>
  <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Arial"/></font>
  <font><i/><sz val="9"/><color rgb="FF595959"/><name val="Arial"/></font>
  <font><sz val="11"/><name val="Arial"/></font>
</fonts>
<fills count="3">
  <fill><patternFill patternType="none"/></fill>
  <fill><patternFill patternType="gray125"/></fill>
  <fill><patternFill patternType="solid"><fgColor rgb="FF44546A"/>
    <bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
  <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1"
      applyFill="1" applyAlignment="1">
    <alignment horizontal="center" vertical="center" wrapText="1"/></xf>
  <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  <xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
  <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>'''

ROOT_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

WB_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''


def write(path: Path, sheet: str, rows: list, *, widths=(), styles=(),
          freeze: str = 'A2', autofilter: bool = True) -> None:
    """One sheet of `rows`, each a list of values, Formula, or None.

    `styles` is one style id per column, applied from the second row down;
    the first row always takes the header style.
    """
    body = []
    for n, row in enumerate(rows, start=1):
        cells = []
        for c, v in enumerate(row, start=1):
            if v is None or v == '':
                continue
            ref = f'{col_letter(c)}{n}'
            s = HEADER if n == 1 else (styles[c - 1] if c - 1 < len(styles)
                                       else PLAIN)
            if isinstance(v, Formula):
                got = getattr(v, 'value', None)
                cached = ('' if got is None
                          else f'<v>{esc(got) if isinstance(got, str) else got}</v>')
                kind = ' t="str"' if isinstance(got, str) else ''
                cells.append(f'<c r="{ref}" s="{s}"{kind}>'
                             f'<f>{esc(v)}</f>{cached}</c>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                cells.append(f'<c r="{ref}" s="{s}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{s}" t="inlineStr">'
                             f'<is><t xml:space="preserve">{esc(v)}</t></is></c>')
        body.append(f'<row r="{n}">{"".join(cells)}</row>')

    wide = ''.join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1)) if widths else ''
    last = f'{col_letter(max((len(r) for r in rows), default=1))}{len(rows)}'
    pane = (f'<sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="{freeze}"'
            f' activePane="bottomLeft" state="frozen"/></sheetView>'
            if freeze else '<sheetView workbookViewId="0"/>')
    # The filter covers the header and the data, never the trailing notes -
    # a note swept into a filter turns into a phantom row of the table.
    n_data = len(rows)
    while n_data > 1 and sum(1 for v in rows[n_data - 1] if v not in (None, '')) <= 1:
        n_data -= 1
    filt = (f'<autoFilter ref="A1:{col_letter(len(rows[0]))}{n_data}"/>'
            if autofilter and rows else '')

    sheet_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<worksheet xmlns="http://schemas.openxmlformats.org/'
                 'spreadsheetml/2006/main">'
                 f'<sheetViews>{pane}</sheetViews>'
                 + (f'<cols>{wide}</cols>' if wide else '')
                 + f'<sheetData>{"".join(body)}</sheetData>{filt}</worksheet>')

    wb_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/'
              'spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats'
              '.org/officeDocument/2006/relationships">'
              f'<sheets><sheet name="{esc(sheet)[:31]}" sheetId="1" '
              'r:id="rId1"/></sheets></workbook>')

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', ROOT_RELS)
        z.writestr('xl/workbook.xml', wb_xml)
        z.writestr('xl/_rels/workbook.xml.rels', WB_RELS)
        z.writestr('xl/styles.xml', STYLES)
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml)

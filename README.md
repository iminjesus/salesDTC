# salesDTC

MySQL schema for the sales dashboard, plus a price crawler.

## Tables

Both are loaded from the CSVs in `rawdata/` with `LOAD DATA LOCAL INFILE`. Each table's
columns are exactly the columns of its file, in the same order, so the load needs no
column list, and every column carries its original header as a comment.

| File | Table | Source |
|---|---|---|
| `sql/customer.sql` | `customer` | `rawdata/customer_2608.csv`, keyed by SAP Sold-To |
| `sql/product.sql` | `product` | `rawdata/product_2608.csv`, keyed by SKU |
| `sql/load.sql` | — | loads both files and checks the result |
| `sql/probe_file.sql` | — | run this when a load misbehaves: reads the file as raw lines and reports its line endings, separator and encoding |

```sql
-- in MySQL Workbench
sql/customer.sql
sql/product.sql
```

Then run `sql/load.sql`, which truncates and loads both files and prints the row
counts, warnings, a sample of each table and two sanity counts. The same statement is
also at the bottom of each CREATE script if you would rather run one at a time.

Things worth knowing before the load:

- `LOAD DATA LOCAL INFILE` needs `local_infile` on both sides: `SET GLOBAL local_infile = 1`
  on the server, and `OPT_LOCAL_INFILE=1` in the Workbench connection under
  Advanced → Others.
- **Error 1300** means `CHARACTER SET` does not match the file. Excel's plain
  "CSV (Comma delimited)" is the Windows code page, not UTF-8:
  `latin1` for Excel ANSI on a Western Windows (MySQL's latin1 is really
  Windows-1252, so ™, – and ® come through), `euckr` for a Windows ANSI file with
  Hangul in it, `utf8mb4` only if it was saved as "CSV UTF-8". The scripts default to
  `latin1`.
- `utf8mb4` matters for the product file: descriptions carry characters like the
  trademark sign in `Slim S-pen™ Case`.
- `Range` is a reserved word in MySQL, so that column is `product_range`.
- **Columns full of random accented characters** means the file is not text at all.
  A `.csv` name does not make it one — renaming a workbook, or saving it in a binary
  format under that extension, leaves it binary. Open it in Excel and use
  **Save As → CSV UTF-8 (Comma delimited)**, then load with `utf8mb4`.
  `sql/probe_file.sql` names the format outright.
- **Warning 1265 `Data truncated` on every column, with far fewer rows than the file
  has**, means the rows are not being split: several real rows are arriving as one
  line. Run `sql/probe_file.sql` — it reports the file's line endings, field separator
  and encoding without depending on the load settings being right. Usually the fix is
  `LINES TERMINATED BY '\n'` instead of `'\r\n'`.
- Both tables have a primary key (`sold_to`, `sku`). Under `LOAD DATA LOCAL` a duplicate
  key is a **warning**, not an error, and the row is skipped silently — so check the row
  count and `SHOW WARNINGS` after every load.

## No database? Read the files directly

If `LOAD DATA` is not available — company policy, no server, no `local_infile` —
`tools/rawdata.py` reads the files in `rawdata/` without any of it. Python only, and
only the standard library:

```powershell
py tools\rawdata.py                 # what is in rawdata\: format, encoding, columns, rows
py tools\rawdata.py --sqlite        # load it all into rawdata\sales.db
py tools\rawdata.py --clean-csv     # write tidy UTF-8 csvs to rawdata\clean\
```

It identifies each file by its bytes rather than its name, so the encoding and
separator problems above do not arise: UTF-8 with or without a BOM, UTF-16, Windows
ANSI and Korean ANSI, comma/tab/semicolon/pipe, CRLF/LF/CR, and `.xlsx` workbooks —
including one saved under a `.csv` name — are all read correctly. `.xlsb` needs
`py -m pip install pyxlsb`, and the script says so.

`--sqlite` gives a single file you can query with ordinary SQL, no server:

```powershell
py -c "import sqlite3;c=sqlite3.connect(r'rawdata\sales.db');print(c.execute('select portal_group, count(*) from customer_2608 group by 1').fetchall())"
```

DB Browser for SQLite opens the same file if you would rather click around. The
`--clean-csv` output is also what to feed MySQL later, if the policy changes.

## Crawler

`crawler/retail/` pulls competitor prices for a brand into a CSV — on-sale flag, product
name, original price, sale price, % off — from JB Hi-Fi and Harvey Norman. See its own
README.

## History

The 251-column P&L schema (`sales_2526.pnl_fact`) that used to live in `sql/` was
removed on request; the table itself is untouched in the database. It is still in git
history, and `python3 tools/generate_ddl.py` regenerates every one of those files from
`docs/excel_header.txt`. `docs/column_map.csv` remains as the header-to-column mapping.

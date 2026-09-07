# salesDTC — customer / product-group P&L

Database schema and load scripts for the 251-column P&L sheet that used to live in Excel.
Column order and meaning map 1:1 to the original header; the full mapping is in
`docs/column_map.csv`.

## Quick start (MySQL)

Run **`sql/mysql/00_setup.sql`** in MySQL Workbench and hit Execute All. It creates the
`sales_2526` database, the cleanup functions, the table, loads the CSV and prints the
reconciliation counters. Two things to check before running:

- the file path in the `LOAD DATA` statement — use forward slashes, since a backslash is
  an escape character
- Workbench connection → Advanced → Others must contain `OPT_LOCAL_INFILE=1`, otherwise
  the load fails with error 3948

For a tab-separated file, change the `FIELDS` line to `FIELDS TERMINATED BY '\t' ESCAPED BY ''`.

Excel's plain **CSV (Comma delimited)** is written in the Windows ANSI code page, not
UTF-8, and loading it as `utf8mb4` fails with **error 1300**. Either change the
`CHARACTER SET` line in the load statement to `euckr` (Korean Windows ANSI), or re-save
the file from Excel as **CSV UTF-8** and leave the script alone.

## Table

`sales_2526.pnl_fact` — one row per **year x period x customer (`sold_to`) x material
group x profit center x division x distribution channel x currency**.

| Block | Columns | Examples |
|---|---|---|
| Header / aggregation keys | 1–9 | `cus_group`, `record_type`, `division2`, `prod_group`, `fiscal_year`, `sold_to`, `forex_rate`, `sales_usd`, `op_profit_usd` |
| SAP dimensions | 10–17 | `customer`, `material_group`, `nielsen_id`, `profit_center`, `sap_division`, `distribution_channel`, `period`, `doc_currency` |
| Quantity | 18–20 | `qty_gross`, `qty_return`, `qty_net` |
| P&L lines | 21–251 | `s_*` sales, `sc_*` COGS, `sa_*` selling, `rd_*` R&D, `ga_*` G&A, `op_*`/`oe_*` non-operating, `eg_*`/`el_*` equity, `fp_*`/`fe_*` financial |

Two naming rules cover everything:

- the 51 subtotal lines marked `*` in the sheet take a `tot_` prefix
  (`*Net Sales` → `tot_net_sales`). They are sums of the detail lines below them, so
  adding `sum(tot_*)` and `sum(detail)` together double counts.
- account prefixes `S.` `SC.` `SA.` `RD.` `GA.` … stay as lowercase prefixes
  (`SC.Mfg Repair&Maint` → `sc_mfg_repair_and_maint`).

Three easily confused columns are spelled out. They are different axes:

| Excel header | Example | Column | Meaning |
|---|---|---|---|
| Division 2 | `DA` | `division2` | business division |
| Prod_group | `REF`, `MWO` | `prod_group` | product group |
| Division | `E2`, `E5` | `sap_division` | SAP division |
| Currency | `AUD` | `doc_currency` | document currency (`sales_usd` is it translated at `forex_rate`) |

## Files

| File | Contents |
|---|---|
| `sql/mysql/00_setup.sql` | **one-file setup** — database + functions + table + CSV load + checks |
| `sql/mysql/01_pnl_fact.sql` | table only |
| `sql/mysql/02_v_pnl_excel.sql` | view exposing the original Excel headers |
| `sql/mysql/03_staging.sql` | cleanup functions + all-text staging table |
| `sql/mysql/04_load_from_staging.sql` | staging → fact |
| `sql/mysql/05_checks.sql` | reconciliation (zero rows means clean) |
| `sql/mysql/06_load_direct.sql` | file → fact, no staging table |
| `sql/mysql/07_load_infile_columns.sql` | explicit column list — for files with extra or reordered columns |
| `sql/postgres/01_pnl_fact.sql` ~ `05_checks.sql` | PostgreSQL set |
| `sql/sqlserver/01_pnl_fact.sql` | SQL Server table |
| `docs/column_map.csv` | Excel header ↔ column name ↔ type, 251 rows |
| `docs/excel_header.txt` | the original header line (generator input) |
| `tools/generate_ddl.py` | regenerates every SQL file from that header |

## Loading notes

The values arrive as `1,268.93` (thousands separator), blank, `#N/A` and `(12.50)`
(accounting negative), so they cannot go straight into a `decimal` column —
`to_num()` / `to_txt()` handle all four. Two ways to apply them:

- **direct** (`06_load_direct.sql`, and what `00_setup.sql` does): each field is read
  into a `@variable` and converted in the `SET` clause. One step fewer.
- **via staging** (`03` → `07` → `04`): the raw file is kept as text first, which is
  handy when you want to inspect what actually arrived.

If the file carries columns the table does not, or in a different order, drop the
matching `@variable` from the `SET` clause (direct) or replace those names with
`@skip1, @skip2 …` (staging).

Under `LOAD DATA LOCAL`, a duplicate natural key is **warning 1062** rather than an
error and the row is skipped silently. Re-running is safe, but always check the row
count and `SHOW WARNINGS`.

MySQL 8 refuses the all-text staging table because of the InnoDB row size limit
(8126 bytes, error 1118); `03_staging.sql` turns `innodb_strict_mode` off just for the
create. MariaDB does not hit this.

PostgreSQL uses a `sales` schema instead of a database, and `\copy` instead of
`LOAD DATA`; see the header comments in each file.

## Regenerating

Replace `docs/excel_header.txt` and re-run:

```sh
python3 tools/generate_ddl.py
```

Every setting in the generator is keyed by the Excel header string, so columns can be
dropped, added or reordered in the sheet. Name overrides (typo fixes, disambiguation)
live in the `NAME` dict.

## Verified

Run against PostgreSQL 16, MySQL 8.0.46 and MariaDB 10.11: 254 columns
(251 + `pnl_id` + load metadata) created, the two sample rows loaded from an
Excel-style comma CSV (including quoted `"1,268.93"`) in both UTF-8 and Windows ANSI
(CP949, loaded with `CHARACTER SET euckr`), values matching the source,
duplicate reload blocked, original headers restored through `v_pnl_excel`, and all
reconciliation checks passing. The SQL Server file is syntax-only — it has not been run.

## Open questions

- **Natural key** — `ux_pnl_fact_natural` treats `fiscal_year, period, sold_to,
  material_group, profit_center, sap_division, distribution_channel, doc_currency` as
  unique. The older sheet had a `Ver` column that is gone, so loading the same period
  under two versions now collides. To keep versions side by side, bring `Ver` back into
  the sheet (the generator picks it up automatically) or delete the period before reloading.
- **`*Profit Before Tax`** is not in the reconciliation checks: the sign convention for
  the non-operating, equity and financial blocks cannot be pinned down from the sample
  rows alone.
- Amounts are `decimal(18,2)`, quantities `decimal(18,3)`, the FX rate `decimal(18,9)`.

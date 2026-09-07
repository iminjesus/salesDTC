#!/usr/bin/env python3
"""Generate the P&L DDL from docs/excel_header.txt (one tab-separated header line).

    python3 tools/generate_ddl.py

Outputs
    sql/mysql/00_setup.sql                one-file setup: database + table + CSV load
    sql/mysql/01_pnl_fact.sql             fact table
    sql/mysql/02_v_pnl_excel.sql          view exposing the original Excel headers
    sql/mysql/03_staging.sql              cleanup functions + all-text staging table
    sql/mysql/04_load_from_staging.sql    staging -> fact
    sql/mysql/06_load_direct.sql          file -> fact, no staging table
    sql/mysql/07_load_infile_columns.sql  explicit column list for staging loads
    sql/mysql/08_probe_file.sql           read the file as raw lines to diagnose a load
    sql/postgres/01_pnl_fact.sql          fact table + indexes + column comments
    sql/postgres/02_v_pnl_excel.sql       view exposing the original Excel headers
    sql/postgres/03_staging.sql           all-text staging table + cleanup functions
    sql/postgres/04_load_from_staging.sql staging -> fact
    sql/sqlserver/01_pnl_fact.sql         fact table
    docs/column_map.csv                   Excel header <-> column name <-> type

Every setting below is keyed by the Excel header string, so columns can be dropped,
added or reordered in the sheet: replace excel_header.txt and re-run. Settings whose
header is not present are simply ignored.
"""
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = os.path.join(ROOT, 'docs', 'excel_header.txt')

MYSQL_DB = 'sales_2526'
PG_SCHEMA = 'sales'
DATA_FILE = 'C:/work/sales_dashboard/salesDTC/rawdata/sales_2526.csv'

# ── Column names: only headers whose auto-derived name would be unclear ──────
NAME = {
    # header / dimension block
    'Cus_group':            'cus_group',
    'Type':                 'record_type',
    'Division 2':           'division2',            # business division (DA/AV/MX)
    'Prod_group':           'prod_group',           # product group (REF/MWO/CTV)
    'Year':                 'fiscal_year',
    'Ver':                  'version',
    'sold To':              'sold_to',
    'Forex':                'forex_rate',
    'Sales U$':             'sales_usd',
    'Op Profit U$':         'op_profit_usd',
    'Month':                'month_nm',
    'Division':             'sap_division',         # SAP division (E2/E5) - not division2
    'Distribution Channel': 'distribution_channel',
    'Currency':             'doc_currency',         # document currency (AUD)
    'Quantity(Gross)':      'qty_gross',
    'Quantity(Return)':     'qty_return',
    'Quantity(Net)':        'qty_net',
    # P&L lines that are typos in the source or would collide
    '*Delear Discount':          'tot_dealer_discount',      # sheet typo (Dealer)
    'SC.Othres(RD)':             'sc_others_rd',             # sheet typo (Others)
    'RD Labor':                  'rd_labor',
    '*Non-Op. Incom. & Ex':      'tot_non_op_income_and_expense',
    '*Financial  Incom. & Exp.': 'tot_financial_income_and_expense',
    '*Other Exp.':               'tot_other_exp_detail',     # vs *Other Expense
    '*Cost of Goods Sold':       'tot_cogs',
    '*Ref. CoGS':                'tot_ref_cogs',
    '*Logistic Cost(C Type)':    'tot_logistic_cost_c_type',
}

# ── Types: anything not listed is a P&L amount (MEASURE) ────────────────────
TYPES = {
    'Cus_group': 'varchar(20)',  'Account': 'varchar(20)',   'Site': 'varchar(20)',
    'Type': 'varchar(10)',       'Division 2': 'varchar(20)','Prod_group': 'varchar(20)',
    'Division': 'varchar(10)',   'Year': 'smallint',         'Ver': 'varchar(20)',
    'sold To': 'varchar(20)',    'Forex': 'numeric(18,9)',   'Sales U$': 'numeric(18,2)',
    'Op Profit U$': 'numeric(18,2)', 'Flag': 'varchar(10)',  'Month': 'varchar(10)',
    'PP1': 'varchar(20)',        'Customer': 'varchar(20)',  'Material Group': 'varchar(20)',
    'Nielsen ID': 'varchar(20)', 'Profit Center': 'varchar(20)',
    'Distribution Channel': 'varchar(10)', 'Period': 'varchar(10)',
    'Currency': 'varchar(10)',
    'Quantity(Gross)': 'numeric(18,3)', 'Quantity(Return)': 'numeric(18,3)',
    'Quantity(Net)': 'numeric(18,3)',
}
MEASURE = 'numeric(18,2)'
NOT_NULL = ('Year', 'Ver', 'Period')

# ── Section banners emitted into the DDL (skipped if the header is absent) ──
SECTIONS = {
    'Cus_group':           'Header / aggregation keys (left block of the sheet)',
    'Customer':            'SAP dimensions',
    'Quantity(Gross)':     'Quantity',
    '*S.RRP':              'Sales',
    '*Cost of Goods Sold': 'Cost of goods sold',
    '*Gross Margin':       'Gross margin / operating expense',
    '*R&D Expense':        'R&D expense',
    '*G&A Expense':        'G&A expense',
    '*Operating Profit':   'Operating profit and below',
}

# ── Natural key candidates; only headers present in the sheet are used ──────
NATURAL_KEY = ['Year', 'Ver', 'Period', 'sold To', 'Material Group',
               'Profit Center', 'Division', 'Distribution Channel', 'Currency']


def normalize(src):
    """'SC.Mfg Repair&Maint' -> 'sc_mfg_repair_and_maint',  '*Net Sales' -> 'tot_net_sales'"""
    s = src.strip()
    is_total = s.startswith('*')          # '*' marks a subtotal line in the sheet
    s = s.lstrip('*').strip()
    s = s.replace('&', ' and ').replace('/', ' ')
    s = re.sub(r'^(S|SC|SA|RD|GA|OP|OE|EG|EL|FP|FE)\.\s*',
               lambda m: m.group(1).lower() + '_', s)
    s = re.sub(r'[^0-9A-Za-z]+', '_', s).strip('_').lower()
    s = re.sub(r'_+', '_', s)
    return ('tot_' + s) if is_total else s


def load_columns():
    with open(HEADER, encoding='utf-8') as f:
        headers = [h.strip() for h in f.read().rstrip('\n').split('\t')]
    cols, used, seen_src = [], set(), {}
    for pos, src in enumerate(headers, 1):
        name = NAME.get(src) or normalize(src)
        if name in used:
            raise SystemExit(
                f'column name collision: {name!r} (pos {pos}, header {src!r}). '
                'Disambiguate it in NAME.')
        used.add(name)
        typ = TYPES.get(src, MEASURE)
        # a header repeated in the sheet would collide as a view alias
        seen_src[src] = seen_src.get(src, 0) + 1
        alias = src if seen_src[src] == 1 else f'{src} ({seen_src[src]})'
        cols.append({
            'pos': pos,
            'src': src,
            'name': name,
            'alias': alias,
            'total': src.startswith('*'),
            'type': typ,
            'numeric': typ.startswith(('numeric', 'smallint')),
            'not_null': src in NOT_NULL,
        })
    return cols


def natural_key(cols):
    by_src = {c['src']: c['name'] for c in cols}
    return [by_src[h] for h in NATURAL_KEY if h in by_src]


def key_block(cols, indent='    '):
    keys = natural_key(cols)
    lines, cur = [], indent
    for i, k in enumerate(keys):
        piece = k + (',' if i < len(keys) - 1 else '')
        if len(cur) + len(piece) > 76:
            lines.append(cur.rstrip())
            cur = indent
        cur += piece + ' '
    lines.append(cur.rstrip())
    return '\n'.join(lines)


def write(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print('wrote', rel)


def my_type(c):
    return c['type'].replace('numeric', 'decimal')


def column_lines(cols, width, dialect='pg'):
    """Column definitions with section banners. dialect: pg | mssql | mysql"""
    out = []
    for c in cols:
        if c['src'] in SECTIONS:
            out += ['', f"    -- == {SECTIONS[c['src']]} " + '=' * 8]
        typ = c['type'] if dialect == 'pg' else my_type(c)
        typ += ' NOT NULL' if c['not_null'] else ''
        if dialect == 'mysql':
            cmt = c['src'].replace("'", "''")
            out.append(f"    {c['name']:<{width}}{typ:<22} COMMENT '{cmt}',")
        else:
            out.append(f"    {c['name']:<{width}}{(typ + ','):<24}-- {c['src']}")
    return out


# ── Cleanup functions, shared by the MySQL scripts ──────────────────────────
MYSQL_FUNCS = r"""
-- Excel-style number string -> decimal  ("1,268.93", "(1,234)", "", "-", "#N/A")
-- Anything that is not a plain number becomes NULL rather than raising, so a
-- misaligned file cannot abort the load halfway through. The reconciliation
-- queries at the end are what tell you the file was misaligned.
DROP FUNCTION IF EXISTS to_num;
DROP FUNCTION IF EXISTS to_txt;
DELIMITER $$

CREATE FUNCTION to_num(v text) RETURNS decimal(18,4)
DETERMINISTIC
BEGIN
    DECLARE t varchar(255);
    SET t = LEFT(REPLACE(REPLACE(REPLACE(TRIM(COALESCE(v, '')), ',', ''),
                                 '$', ''), ' ', ''), 255);
    IF t = '' OR t IN ('-', '#N/A', 'N/A', '#DIV/0!', '#VALUE!') THEN
        RETURN NULL;
    END IF;
    IF t LIKE '(%)' THEN                       -- accounting negative (12.50) -> -12.50
        SET t = CONCAT('-', SUBSTRING(t, 2, CHAR_LENGTH(t) - 2));
    END IF;
    -- '[.]' not '\.': MySQL strips the backslash in a string literal, which would
    -- turn the dot into "any character" and let text like 'A123' reach the CAST.
    IF t NOT REGEXP '^-?[0-9]*[.]?[0-9]+$' THEN
        RETURN NULL;
    END IF;
    -- decimal(18,4) holds at most 14 integer digits; anything wider would raise 1264.
    IF CHAR_LENGTH(SUBSTRING_INDEX(REPLACE(t, '-', ''), '.', 1)) > 14 THEN
        RETURN NULL;
    END IF;
    RETURN CAST(t AS decimal(18,4));
END$$

-- Dimension text: trim, and turn blank / #N/A into NULL
CREATE FUNCTION to_txt(v text) RETURNS varchar(260)
DETERMINISTIC
BEGIN
    DECLARE t varchar(260);
    SET t = LEFT(TRIM(COALESCE(v, '')), 260);
    IF t = '' OR t = '#N/A' THEN
        RETURN NULL;
    END IF;
    RETURN t;
END$$

DELIMITER ;
""".strip()

LOAD_HINTS = [
    '-- Before running, check two things:',
    '--   1) the file path below. Use forward slashes; a backslash is an escape char.',
    '--   2) Workbench connection > Advanced > Others must have OPT_LOCAL_INFILE=1,',
    '--      otherwise the load fails with error 3948.',
    '--',
    '-- For a tab-separated file, change the FIELDS line to:',
    "--     FIELDS TERMINATED BY '\\t' ESCAPED BY ''",
    '--',
    '-- Excel saves plain "CSV (Comma delimited)" in the Windows ANSI code page, not',
    '-- UTF-8. Loading that as utf8mb4 fails with error 1300 - either set',
    '-- CHARACTER SET euckr below, or re-save the file as "CSV UTF-8" from Excel.',
]


def load_stmt(table, cols, var_prefix=True):
    """The LOAD DATA statement, reading every field into a @variable."""
    L = [f"LOAD DATA LOCAL INFILE '{DATA_FILE}'",
         f'    INTO TABLE {table}',
         '    CHARACTER SET utf8mb4   -- error 1300 means the file is not UTF-8:',
         '                            -- use euckr for a Korean Windows ANSI csv,',
         '                            -- or re-save it from Excel as "CSV UTF-8"',
         "    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY ''",
         "    LINES TERMINATED BY '\\r\\n'",
         '    IGNORE 1 LINES          -- skip the header row',
         '(']
    for i, c in enumerate(cols):
        nm = ('@' + c['name']) if var_prefix else c['name']
        L.append(f"    {nm}{',' if i < len(cols) - 1 else ''}")
    L.append(')')
    if var_prefix:
        L.append('SET')
        for i, c in enumerate(cols):
            fn = 'to_num' if c['numeric'] else 'to_txt'
            L.append(f"    {c['name']} = {fn}(@{c['name']}){',' if i < len(cols) - 1 else ';'}")
    else:
        L[-1] = ');'
    return L


VERIFY = [
    'SELECT count(*) AS loaded_rows FROM pnl_fact;',
    'SHOW WARNINGS;',
    '',
    '-- Values that could not be parsed as a number land as NULL. A handful is normal',
    '-- (blank cells, #N/A); a large count means the file is misaligned or the wrong',
    '-- delimiter/character set is in use - run 08_probe_file.sql.',
    'SELECT count(*) AS rows_total,',
    '       sum(tot_net_sales IS NULL)        AS null_net_sales,',
    '       sum(tot_operating_profit IS NULL) AS null_op_profit',
    'FROM   pnl_fact;',
    '',
    '-- Eyeball a few rows to confirm values landed in the right columns.',
    'SELECT sold_to, material_group, prod_group, period,',
    '       tot_net_sales, tot_cogs, tot_gross_margin, tot_operating_profit',
    'FROM   pnl_fact',
    'LIMIT  5;',
    '',
    '-- Reconciliation: all four counters must be 0.',
    '--   non-zero -> columns are shifted',
    '--   NULL     -> nothing parsed at all, so the delimiter, line ending or',
    '--               character set is wrong. Run 08_probe_file.sql.',
    'SELECT',
    '    sum(abs(tot_net_sales - (tot_s_gross_sales - tot_sales_deduction)) > 0.05)'
    ' AS err_net_sales,',
    '    sum(abs(tot_gross_margin - (tot_net_sales - tot_cogs)) > 0.05)'
    ' AS err_gross_margin,',
    '    sum(abs(tot_operating_expense - (tot_sales_expense + tot_r_and_d_expense'
    ' + tot_g_and_a_expense)) > 0.05) AS err_op_expense,',
    '    sum(abs(tot_operating_profit - (tot_gross_margin - tot_operating_expense)) > 0.05)'
    ' AS err_op_profit',
    'FROM pnl_fact;',
]


def mysql_table(cols, db_line=True):
    w = max(len(c['name']) for c in cols) + 2
    L = []
    if db_line:
        L += [f'CREATE DATABASE IF NOT EXISTS {MYSQL_DB} '
              'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;',
              f'USE {MYSQL_DB};',
              '']
    L += ['DROP TABLE IF EXISTS pnl_fact;',
          'CREATE TABLE pnl_fact (',
          '    pnl_id           bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,']
    L += column_lines(cols, w, 'mysql')
    L += ['',
          f"    {'loaded_at':<{w}}datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),",
          '',
          '    -- One row per period x customer x material group x profit center.',
          '    -- Loading the same file twice does not pile up duplicates: under',
          '    -- LOAD DATA LOCAL a duplicate key is warning 1062 and the row is skipped.',
          '    UNIQUE KEY ux_pnl_fact_natural (',
          key_block(cols, indent='        '),
          '    ),',
          '    KEY ix_pnl_fact_period   (fiscal_year, period),',
          '    KEY ix_pnl_fact_customer (sold_to, fiscal_year, period),',
          '    KEY ix_pnl_fact_matgrp   (material_group, fiscal_year, period)',
          ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC',
          "  COMMENT='P&L by customer and material group. tot_* are the sheet''s "
          "* subtotal lines.';"]
    return L


# ── Generators ──────────────────────────────────────────────────────────────
def gen_mysql_oneshot(cols):
    L = [f'-- One-file setup for {MYSQL_DB}: database -> table -> CSV load -> checks.',
         '-- Open in MySQL Workbench and hit Execute All. Nothing else is needed.',
         '--']
    L += LOAD_HINTS
    L += ['',
          'SET GLOBAL local_infile = 1;',
          '',
          '-- == 1. Cleanup functions ' + '=' * 8,
          '--    "1,268.93" -> 1268.93,  "" / "#N/A" -> NULL,  "(12.50)" -> -12.50',
          '',
          f'CREATE DATABASE IF NOT EXISTS {MYSQL_DB} '
          'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;',
          f'USE {MYSQL_DB};',
          '',
          MYSQL_FUNCS,
          '',
          '-- == 2. Table ' + '=' * 8,
          '--    Column order matches the sheet 1:1; each comment is the original header.',
          '']
    L += mysql_table(cols, db_line=False)
    L += ['',
          '-- == 3. Load ' + '=' * 8,
          '--    Every field is read into a @variable and converted in the SET clause.',
          '']
    L += load_stmt('pnl_fact', cols)
    L += ['', '-- == 4. Verify ' + '=' * 8, '']
    L += VERIFY
    L += ['']
    return '\n'.join(L)


def gen_mysql(cols):
    L = [f'-- MySQL: fact table only, {len(cols)} columns straight from the sheet.',
         "-- tot_* are the sheet's * subtotal lines (sums of the detail lines below them,",
         '-- so do not add both when aggregating).',
         '-- MySQL has no schema/database distinction, so this uses a database.',
         '']
    L += mysql_table(cols)
    L += ['']
    return '\n'.join(L)


def gen_mysql_view(cols):
    L = ['-- View that gives the original Excel headers back (MySQL quotes with backticks).',
         f'USE {MYSQL_DB};',
         '',
         'CREATE OR REPLACE VIEW v_pnl_excel AS',
         'SELECT']
    for i, c in enumerate(cols):
        L.append(f"    {c['name']:<30} AS `{c['alias']}`{',' if i < len(cols) - 1 else ''}")
    L += ['FROM pnl_fact;', '']
    return '\n'.join(L)


def gen_mysql_staging(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- Cleanup functions plus an all-text staging table holding the raw file.',
         '-- Thousands separators, blanks and #N/A pass through here and are converted',
         '-- by 04_load_from_staging.sql.',
         '--',
         '-- To skip staging entirely, run only the two functions below and use',
         '-- 06_load_direct.sql instead - one step fewer.',
         f'USE {MYSQL_DB};',
         '',
         MYSQL_FUNCS,
         '',
         '-- MySQL 8 refuses a table of 251 text columns because of the InnoDB row size',
         '-- limit (8126 bytes, error 1118). The values are short, so the DYNAMIC row',
         '-- format stores them off-page at runtime; only the create-time check needs',
         '-- to be relaxed.',
         'SET SESSION innodb_strict_mode = OFF;',
         '',
         'DROP TABLE IF EXISTS pnl_stg;',
         'CREATE TABLE pnl_stg (']
    L += [f"    {c['name']:<{w}}text{',' if i < len(cols) - 1 else ''}"
          for i, c in enumerate(cols)]
    L += [') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;', '']
    return '\n'.join(L)


def gen_mysql_load(cols):
    L = ['-- staging -> fact.',
         '--   1) TRUNCATE TABLE pnl_stg;',
         '--   2) load the file into pnl_stg (07_load_infile_columns.sql, or the',
         '--      Table Data Import Wizard if LOAD DATA LOCAL is unavailable)',
         '--   3) run this file',
         '--   4) TRUNCATE TABLE pnl_stg;',
         '',
         f'USE {MYSQL_DB};',
         '',
         'INSERT INTO pnl_fact (']
    L += [f"    {c['name']}{',' if i < len(cols) - 1 else ''}" for i, c in enumerate(cols)]
    L += [') SELECT']
    for i, c in enumerate(cols):
        fn = 'to_num' if c['numeric'] else 'to_txt'
        L.append(f"    {fn}({c['name']}){',' if i < len(cols) - 1 else ''}")
    L += ['FROM pnl_stg;', '']
    return '\n'.join(L)


def gen_mysql_direct(cols):
    L = ['-- File -> pnl_fact directly, without a staging table.',
         '-- The to_num()/to_txt() functions from 03_staging.sql must exist',
         '-- (running just the two CREATE FUNCTION blocks there is enough).',
         '--']
    L += LOAD_HINTS
    L += ['--',
          '-- If the file carries columns that do not belong in the table, drop the',
          '-- matching @variable from the SET clause - unused @variables are discarded.',
          '--',
          '-- Under LOCAL, a duplicate natural key is warning 1062 rather than an error',
          '-- and that row is skipped silently. Re-running is safe, but always check the',
          '-- row count and SHOW WARNINGS below.',
          '',
          f'USE {MYSQL_DB};',
          '']
    L += load_stmt('pnl_fact', cols)
    L += ['', '']
    L += VERIFY
    L += ['']
    return '\n'.join(L)


def gen_mysql_infile(cols):
    L = ['-- Load the file into pnl_stg with an explicit column list.',
         '--',
         '-- Use this when the file has columns the table does not (an Excel index',
         '-- column, headers only the older sheet had) or when the order differs:',
         '-- replace those positions with @skip1, @skip2 ... and their values are',
         '-- discarded. The list order must match the file, not the table.',
         '--']
    L += LOAD_HINTS
    L += ['',
          f'USE {MYSQL_DB};',
          '',
          'TRUNCATE TABLE pnl_stg;',
          '']
    L += load_stmt('pnl_stg', cols, var_prefix=False)
    L += ['',
          'SELECT count(*) AS staged FROM pnl_stg;',
          'SHOW WARNINGS;',
          '',
          '-- Then run 04_load_from_staging.sql, followed by 05_checks.sql.',
          '']
    return '\n'.join(L)


def gen_postgres(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = [f'-- P&L by customer and material group: {len(cols)} columns straight from the sheet.',
         "-- tot_* are the sheet's * subtotal lines (sums of the detail lines below them,",
         '-- so do not add both when aggregating).',
         '',
         f'CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA};',
         '',
         f'DROP TABLE IF EXISTS {PG_SCHEMA}.pnl_fact CASCADE;',
         '',
         f'CREATE TABLE {PG_SCHEMA}.pnl_fact (',
         '    pnl_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,']
    L += column_lines(cols, w)
    L += ['',
          '    -- == Load metadata ' + '=' * 8,
          f"    {'source_file':<{w}}varchar(260),",
          f"    {'loaded_at':<{w}}timestamptz NOT NULL DEFAULT now()",
          ');',
          '',
          '-- Natural key: one row per period x customer x material group x profit center.',
          '-- Drop this index if the source has NULLs in the key columns, and delete the',
          '-- period before reloading instead.',
          f'CREATE UNIQUE INDEX ux_pnl_fact_natural ON {PG_SCHEMA}.pnl_fact (',
          key_block(cols),
          ');',
          '',
          f'CREATE INDEX ix_pnl_fact_period   ON {PG_SCHEMA}.pnl_fact (fiscal_year, period);',
          f'CREATE INDEX ix_pnl_fact_customer ON {PG_SCHEMA}.pnl_fact '
          '(sold_to, fiscal_year, period);',
          f'CREATE INDEX ix_pnl_fact_matgrp   ON {PG_SCHEMA}.pnl_fact '
          '(material_group, fiscal_year, period);',
          '',
          f"COMMENT ON TABLE {PG_SCHEMA}.pnl_fact IS "
          "'P&L by customer and material group. tot_* are the sheet''s * subtotal lines.';",
          '']
    for c in cols:
        L.append(f"COMMENT ON COLUMN {PG_SCHEMA}.pnl_fact.{c['name']} IS "
                 f"'{c['src'].replace(chr(39), chr(39) * 2)}';")
    return '\n'.join(L) + '\n'


def gen_pg_view(cols):
    L = ['-- View that gives the original Excel headers back.',
         f"--   \\copy (SELECT * FROM {PG_SCHEMA}.v_pnl_excel) TO 'pnl.csv' "
         'WITH (FORMAT csv, HEADER true)',
         f'CREATE OR REPLACE VIEW {PG_SCHEMA}.v_pnl_excel AS',
         'SELECT']
    for i, c in enumerate(cols):
        L.append(f"    {c['name']:<30} AS \"{c['alias']}\"{',' if i < len(cols) - 1 else ''}")
    L += [f'FROM {PG_SCHEMA}.pnl_fact;', '']
    return '\n'.join(L)


def gen_pg_staging(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- All-text staging table holding the raw TSV: thousands separators, blanks',
         '-- and #N/A pass through here and are converted by 04_load_from_staging.sql.',
         '',
         f'DROP TABLE IF EXISTS {PG_SCHEMA}.pnl_stg;',
         f'CREATE TABLE {PG_SCHEMA}.pnl_stg (']
    L += [f"    {c['name']:<{w}}text{',' if i < len(cols) - 1 else ''}"
          for i, c in enumerate(cols)]
    L += [');', '', r'''
-- Excel-style number string -> numeric  ("1,268.93", "(1,234)", "", "-", "#N/A")
CREATE OR REPLACE FUNCTION sales.to_num(v text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t text;
BEGIN
    t := btrim(coalesce(v, ''));
    t := replace(replace(replace(t, ',', ''), '$', ''), ' ', '');
    IF t = '' OR t IN ('-', '#N/A', 'N/A', '#DIV/0!', '#VALUE!') THEN
        RETURN NULL;
    END IF;
    IF t LIKE '(%)' THEN                       -- accounting negative (12.50) -> -12.50
        t := '-' || btrim(t, '()');
    END IF;
    RETURN t::numeric;
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

-- Dimension text: trim, and turn blank / #N/A into NULL
CREATE OR REPLACE FUNCTION sales.to_txt(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(nullif(btrim(coalesce(v, '')), ''), '#N/A')
$$;
'''.strip(), '']
    return '\n'.join(L)


def gen_pg_load(cols):
    L = ['-- staging -> fact.',
         f'--   1) TRUNCATE {PG_SCHEMA}.pnl_stg;',
         f"--   2) \\copy {PG_SCHEMA}.pnl_stg FROM 'pnl.tsv' "
         "WITH (FORMAT csv, DELIMITER E'\\t', HEADER true, QUOTE E'\\b')",
         '--      (QUOTE is a backspace so quotes inside Excel values pass through)',
         '--   3) run this file',
         f'--   4) TRUNCATE {PG_SCHEMA}.pnl_stg;',
         '',
         f'INSERT INTO {PG_SCHEMA}.pnl_fact (']
    L += [f"    {c['name']}{',' if i < len(cols) - 1 else ''}" for i, c in enumerate(cols)]
    L += [') SELECT']
    for i, c in enumerate(cols):
        fn = f'{PG_SCHEMA}.to_num' if c['numeric'] else f'{PG_SCHEMA}.to_txt'
        cast = '::smallint' if c['type'] == 'smallint' else ''
        L.append(f"    {fn}({c['name']}){cast}{',' if i < len(cols) - 1 else ''}")
    L += [f'FROM {PG_SCHEMA}.pnl_stg;', '']
    return '\n'.join(L)


def gen_sqlserver(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- SQL Server. Same columns as the PostgreSQL version.',
         '-- Note: a SQL Server UNIQUE INDEX treats NULLs as equal, so drop the index',
         '--       or make it filtered if the source has NULLs in the key columns.',
         '',
         f"IF SCHEMA_ID('{PG_SCHEMA}') IS NULL EXEC('CREATE SCHEMA {PG_SCHEMA}');",
         'GO',
         '',
         f"IF OBJECT_ID('{PG_SCHEMA}.pnl_fact','U') IS NOT NULL "
         f'DROP TABLE {PG_SCHEMA}.pnl_fact;',
         'GO',
         '',
         f'CREATE TABLE {PG_SCHEMA}.pnl_fact (',
         '    pnl_id           bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,']
    L += column_lines(cols, w, 'mssql')
    L += ['',
          '    -- == Load metadata ' + '=' * 8,
          f"    {'source_file':<{w}}varchar(260),",
          f"    {'loaded_at':<{w}}datetime2(3) NOT NULL "
          'CONSTRAINT df_pnl_loaded_at DEFAULT sysutcdatetime()',
          ');',
          'GO',
          '',
          f'CREATE UNIQUE INDEX ux_pnl_fact_natural ON {PG_SCHEMA}.pnl_fact (',
          key_block(cols),
          ');',
          f'CREATE INDEX ix_pnl_fact_period   ON {PG_SCHEMA}.pnl_fact (fiscal_year, period);',
          f'CREATE INDEX ix_pnl_fact_customer ON {PG_SCHEMA}.pnl_fact '
          '(sold_to, fiscal_year, period);',
          f'CREATE INDEX ix_pnl_fact_matgrp   ON {PG_SCHEMA}.pnl_fact '
          '(material_group, fiscal_year, period);',
          'GO',
          '']
    return '\n'.join(L)


def gen_mysql_probe(cols):
    """Read the file as whole lines to find the real delimiter and line ending."""
    L = ['-- File probe: run this first when a load fails and you are not sure what the',
         '-- file actually looks like. It reads whole lines, splitting nothing.',
         '--',
         '-- How to read the result:',
         '--   lines_read = 1        -> the line ending is wrong. The file is probably LF',
         "--                           only, so use LINES TERMINATED BY '\\n'.",
         f'--   comma_fields ~ {len(cols)}    -> comma separated, keep FIELDS TERMINATED BY \',\'',
         '--                           (a few more is fine: quoted values like "1,268.93"',
         '--                            carry commas of their own)',
         f'--   tab_fields   = {len(cols)}    -> tab separated, use FIELDS TERMINATED BY \'\\t\'',
         '--   garbled Korean in head -> wrong CHARACTER SET (try euckr)',
         '--',
         '-- Change CHARACTER SET / LINES TERMINATED BY here the same way as in the load.',
         '',
         f'USE {MYSQL_DB};',
         '',
         'DROP TABLE IF EXISTS raw_probe;',
         'CREATE TABLE raw_probe (line text) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;',
         '',
         f"LOAD DATA LOCAL INFILE '{DATA_FILE}'",
         '    INTO TABLE raw_probe',
         '    CHARACTER SET utf8mb4',
         "    FIELDS TERMINATED BY '\\0' ESCAPED BY ''    -- split nothing",
         "    LINES TERMINATED BY '\\r\\n';",
         '',
         'SELECT count(*) AS lines_read FROM raw_probe;',
         '',
         'SELECT CHAR_LENGTH(line)                                        AS len,',
         "       CHAR_LENGTH(line) - CHAR_LENGTH(REPLACE(line, ',',  '')) + 1 AS comma_fields,",
         "       CHAR_LENGTH(line) - CHAR_LENGTH(REPLACE(line, '\\t', '')) + 1 AS tab_fields,",
         '       LEFT(line, 120)                                          AS head',
         'FROM   raw_probe',
         'LIMIT  3;',
         '',
         '-- DROP TABLE raw_probe;',
         '']
    return '\n'.join(L)



def main():
    cols = load_columns()
    write('sql/mysql/00_setup.sql', gen_mysql_oneshot(cols))
    write('sql/mysql/01_pnl_fact.sql', gen_mysql(cols))
    write('sql/mysql/02_v_pnl_excel.sql', gen_mysql_view(cols))
    write('sql/mysql/03_staging.sql', gen_mysql_staging(cols))
    write('sql/mysql/04_load_from_staging.sql', gen_mysql_load(cols))
    write('sql/mysql/06_load_direct.sql', gen_mysql_direct(cols))
    write('sql/mysql/07_load_infile_columns.sql', gen_mysql_infile(cols))
    write('sql/mysql/08_probe_file.sql', gen_mysql_probe(cols))
    write('sql/postgres/01_pnl_fact.sql', gen_postgres(cols))
    write('sql/postgres/02_v_pnl_excel.sql', gen_pg_view(cols))
    write('sql/postgres/03_staging.sql', gen_pg_staging(cols))
    write('sql/postgres/04_load_from_staging.sql', gen_pg_load(cols))
    write('sql/sqlserver/01_pnl_fact.sql', gen_sqlserver(cols))
    with open(os.path.join(ROOT, 'docs', 'column_map.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['pos', 'excel_header', 'column_name', 'sql_type', 'is_subtotal'])
        w.writerows([[c['pos'], c['src'], c['name'], c['type'], 'Y' if c['total'] else '']
                     for c in cols])
    print('wrote docs/column_map.csv')
    print(f'{len(cols)} columns, {sum(c["total"] for c in cols)} subtotal(*) lines')
    print('natural key:', ', '.join(natural_key(cols)))


if __name__ == '__main__':
    main()

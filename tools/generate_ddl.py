#!/usr/bin/env python3
"""docs/excel_header.txt (엑셀 원본 헤더 1줄, tab 구분) 로부터 DDL 을 생성한다.

    python3 tools/generate_ddl.py

산출물
    sql/postgres/01_pnl_fact.sql          팩트 테이블 + 인덱스 + 컬럼 COMMENT
    sql/postgres/02_v_pnl_excel.sql       엑셀 원본 헤더로 되돌려주는 뷰
    sql/postgres/03_staging.sql           TSV 를 그대로 받는 text staging + 변환 함수
    sql/postgres/04_load_from_staging.sql staging → 팩트 변환 INSERT
    sql/sqlserver/01_pnl_fact.sql         SQL Server 판 팩트 테이블
    sql/mysql/00_setup_sales_2526.sql     한 파일로 끝나는 MySQL 셋업 (DB+테이블+적재)
    sql/mysql/01_pnl_fact.sql             MySQL 판 (01~04 한 벌)
    sql/mysql/02_v_pnl_excel.sql
    sql/mysql/03_staging.sql
    sql/mysql/04_load_from_staging.sql
    sql/mysql/06_load_direct.sql          staging 없이 파일 → pnl_fact 직접 적재
    sql/mysql/07_load_infile_columns.sql  staging 적재용 컬럼 목록 명시판
    docs/column_map.csv                   엑셀 헤더 ↔ 컬럼명 ↔ 타입 매핑표

설정은 전부 '엑셀 헤더 문자열' 을 키로 쓴다. 시트에서 컬럼이 빠지거나 순서가 바뀌어도
excel_header.txt 만 갈아끼우고 다시 돌리면 된다. 헤더에 없는 설정 항목은 그냥 무시된다.
"""
import csv
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = os.path.join(ROOT, 'docs', 'excel_header.txt')

# ── 컬럼명: 자동 변환만으로 뜻이 안 사는 헤더만 손으로 지정 ──────────
# (원본 문자열은 COMMENT 와 docs/column_map.csv 에 그대로 남는다)
NAME = {
    # 헤더/차원 블록
    'Cus_group':            'cus_group',
    'Type':                 'record_type',
    'Division 2':           'division2',            # 사업본부 (DA/AV/MX)
    'Prod_group':           'prod_group',           # 제품군 (REF/MWO/CTV)
    'Year':                 'fiscal_year',
    'Ver':                  'version',
    'sold To':              'sold_to',
    'Forex':                'forex_rate',
    'Sales U$':             'sales_usd',
    'Op Profit U$':         'op_profit_usd',
    'Month':                'month_nm',
    'Division':             'sap_division',         # SAP 사업부 (E2/E5) — division2 와 다름
    'Distribution Channel': 'distribution_channel',
    'Currency':             'doc_currency',         # 전표 통화 (AUD)
    'Quantity(Gross)':      'qty_gross',
    'Quantity(Return)':     'qty_return',
    'Quantity(Net)':        'qty_net',
    # 손익 계정 중 원본 오타이거나 자동 변환이 헷갈리는 것
    '*Delear Discount':          'tot_dealer_discount',      # 원본 오타(Dealer)
    'SC.Othres(RD)':             'sc_others_rd',             # 원본 오타(Others)
    'RD Labor':                  'rd_labor',
    '*Non-Op. Incom. & Ex':      'tot_non_op_income_and_expense',
    '*Financial  Incom. & Exp.': 'tot_financial_income_and_expense',
    '*Other Exp.':               'tot_other_exp_detail',     # *Other Expense 와 구분
    '*Cost of Goods Sold':       'tot_cogs',
    '*Ref. CoGS':                'tot_ref_cogs',
    '*Logistic Cost(C Type)':    'tot_logistic_cost_c_type',
}

# ── 타입: 여기 없는 컬럼은 전부 손익 금액(MEASURE) ────────────────
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

# ── DDL 안에 넣을 섹션 주석 (해당 헤더가 없으면 그 섹션은 생략된다) ──
SECTIONS = {
    'Cus_group':           '헤더/집계 키 (엑셀 좌측 블록)',
    'Customer':            'SAP 원장 차원 (Dimension)',
    'Quantity(Gross)':     '수량 (Quantity)',
    '*S.RRP':              '매출 (Sales)',
    '*Cost of Goods Sold': '매출원가 (Cost of Goods Sold)',
    '*Gross Margin':       '매출총이익 / 판관비 (Gross Margin & Operating Expense)',
    '*R&D Expense':        '연구개발비 (R&D Expense)',
    '*G&A Expense':        '일반관리비 (G&A Expense)',
    '*Operating Profit':   '영업이익 이하 (Operating Profit & below)',
}

# ── 자연키 후보. 헤더에 실제로 있는 것만 인덱스에 들어간다 ──────────
NATURAL_KEY = ['Year', 'Ver', 'Period', 'sold To', 'Material Group',
               'Profit Center', 'Division', 'Distribution Channel', 'Currency']


def normalize(src):
    """'SC.Mfg Repair&Maint' -> 'sc_mfg_repair_and_maint',  '*Net Sales' -> 'tot_net_sales'"""
    s = src.strip()
    is_total = s.startswith('*')          # 엑셀의 * 는 소계 라인
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
                f'컬럼명 충돌: {name!r} (pos {pos}, 헤더 {src!r}). NAME 에 구분해서 지정할 것.')
        used.add(name)
        typ = TYPES.get(src, MEASURE)
        # 같은 헤더가 두 번 나오면 뷰에서 별칭이 겹치므로 뒤엣것에 번호를 붙인다
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


def column_lines(cols, width, sqlserver=False):
    out = []
    for c in cols:
        if c['src'] in SECTIONS:
            out += ['', f"    -- ══ {SECTIONS[c['src']]} " + '═' * 8]
        typ = c['type'].replace('numeric', 'decimal') if sqlserver else c['type']
        typ += ' NOT NULL' if c['not_null'] else ''
        out.append(f"    {c['name']:<{width}}{(typ + ','):<24}-- {c['src']}")
    return out


def gen_postgres(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = [f'-- 고객 x 제품군 단위 손익(P&L) 플랫 테이블 — 엑셀 원본 {len(cols)} 컬럼 그대로.',
         '-- tot_* 는 원본에서 * 가 붙은 소계 라인이다 (하위 계정의 합계이므로 중복 집계 주의).',
         '',
         'CREATE SCHEMA IF NOT EXISTS sales;',
         '',
         'DROP TABLE IF EXISTS sales.pnl_fact CASCADE;',
         '',
         'CREATE TABLE sales.pnl_fact (',
         '    pnl_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,']
    L += column_lines(cols, w)
    L += ['',
          '    -- ══ 적재 메타데이터 ════════',
          f"    {'source_file':<{w}}varchar(260),",
          f"    {'loaded_at':<{w}}timestamptz NOT NULL DEFAULT now()",
          ');',
          '',
          '-- 자연키: 같은 기간의 같은 고객 x 제품군 x 손익센터 조합은 1행.',
          '-- 재적재 시 중복을 막아준다. 키 컬럼에 NULL 이 섞이는 소스라면 이 인덱스는 빼고',
          '-- 적재 전 DELETE 로 해당 기간을 지우는 방식을 쓸 것.',
          'CREATE UNIQUE INDEX ux_pnl_fact_natural ON sales.pnl_fact (',
          key_block(cols),
          ');',
          '',
          'CREATE INDEX ix_pnl_fact_period   ON sales.pnl_fact (fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_customer ON sales.pnl_fact (sold_to, fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_matgrp   ON sales.pnl_fact (material_group, fiscal_year, period);',
          '',
          "COMMENT ON TABLE sales.pnl_fact IS "
          "'고객/제품군 단위 손익(P&L) 플랫 테이블. tot_* 컬럼은 엑셀 원본의 * 소계 라인.';",
          '']
    for c in cols:
        L.append(f"COMMENT ON COLUMN sales.pnl_fact.{c['name']} IS "
                 f"'{c['src'].replace(chr(39), chr(39) * 2)}';")
    return '\n'.join(L) + '\n'


def gen_sqlserver(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- SQL Server 판. Postgres 판(sql/postgres/01_pnl_fact.sql)과 컬럼 구성은 동일하다.',
         "-- 주의: SQL Server 의 UNIQUE INDEX 는 NULL 끼리도 같은 값으로 보므로,",
         '--       자연키에 NULL 이 들어오는 소스라면 인덱스를 빼거나 필터 인덱스로 바꿀 것.',
         '',
         "IF SCHEMA_ID('sales') IS NULL EXEC('CREATE SCHEMA sales');",
         'GO',
         '',
         "IF OBJECT_ID('sales.pnl_fact','U') IS NOT NULL DROP TABLE sales.pnl_fact;",
         'GO',
         '',
         'CREATE TABLE sales.pnl_fact (',
         '    pnl_id           bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,']
    L += column_lines(cols, w, sqlserver=True)
    L += ['',
          '    -- ══ 적재 메타데이터 ════════',
          f"    {'source_file':<{w}}varchar(260),",
          f"    {'loaded_at':<{w}}datetime2(3) NOT NULL "
          'CONSTRAINT df_pnl_loaded_at DEFAULT sysutcdatetime()',
          ');',
          'GO',
          '',
          'CREATE UNIQUE INDEX ux_pnl_fact_natural ON sales.pnl_fact (',
          key_block(cols),
          ');',
          'CREATE INDEX ix_pnl_fact_period   ON sales.pnl_fact (fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_customer ON sales.pnl_fact (sold_to, fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_matgrp   ON sales.pnl_fact (material_group, fiscal_year, period);',
          'GO',
          '']
    return '\n'.join(L) + '\n'


def gen_view(cols):
    L = ['-- 엑셀 원본 헤더 그대로 내보내기용 뷰.',
         "--   \\copy (SELECT * FROM sales.v_pnl_excel) TO 'pnl.csv' WITH (FORMAT csv, HEADER true)",
         'CREATE OR REPLACE VIEW sales.v_pnl_excel AS',
         'SELECT']
    for i, c in enumerate(cols):
        L.append(f"    {c['name']:<30} AS \"{c['alias']}\"{',' if i < len(cols) - 1 else ''}")
    L += ['FROM sales.pnl_fact;', '']
    return '\n'.join(L)


def gen_staging(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- 엑셀에서 뽑은 TSV 를 있는 그대로 받는 임시 테이블: 전 컬럼 text.',
         '-- "1,268.93" 같은 천단위 콤마, 빈칸, #N/A 를 일단 통과시킨 뒤 04 스크립트에서 변환한다.',
         '',
         'DROP TABLE IF EXISTS sales.pnl_stg;',
         'CREATE TABLE sales.pnl_stg (']
    L += [f"    {c['name']:<{w}}text{',' if i < len(cols) - 1 else ''}"
          for i, c in enumerate(cols)]
    L += [');', '', r'''
-- 엑셀식 숫자 문자열 → numeric   ("1,268.93", "(1,234)", "", "-", "#N/A")
CREATE OR REPLACE FUNCTION sales.to_num(v text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE t text;
BEGIN
    t := btrim(coalesce(v, ''));
    t := replace(replace(replace(t, ',', ''), '$', ''), ' ', '');
    IF t = '' OR t IN ('-', '#N/A', 'N/A', '#DIV/0!', '#VALUE!') THEN
        RETURN NULL;
    END IF;
    IF t LIKE '(%)' THEN                       -- 회계식 음수 표기 (12.50) → -12.50
        t := '-' || btrim(t, '()');
    END IF;
    RETURN t::numeric;
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

-- 텍스트 차원값 정리: 앞뒤 공백 제거, 빈칸/#N/A 는 NULL
CREATE OR REPLACE FUNCTION sales.to_txt(v text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(nullif(btrim(coalesce(v, '')), ''), '#N/A')
$$;
'''.strip(), '']
    return '\n'.join(L)


def gen_load(cols):
    L = ['-- staging → 팩트 변환 적재.',
         '--   1) TRUNCATE sales.pnl_stg;',
         "--   2) \\copy sales.pnl_stg FROM 'pnl.tsv' "
         "WITH (FORMAT csv, DELIMITER E'\\t', HEADER true, QUOTE E'\\b')",
         '--      (QUOTE 를 백스페이스로 둬서 엑셀 값 안의 따옴표를 그대로 통과시킨다)',
         '--   3) 이 파일 실행',
         '--   4) TRUNCATE sales.pnl_stg;',
         '',
         'INSERT INTO sales.pnl_fact (']
    L += [f"    {c['name']}{',' if i < len(cols) - 1 else ''}" for i, c in enumerate(cols)]
    L += [') SELECT']
    for i, c in enumerate(cols):
        fn = 'sales.to_num' if c['numeric'] else 'sales.to_txt'
        cast = '::smallint' if c['type'] == 'smallint' else ''
        L.append(f"    {fn}({c['name']}){cast}{',' if i < len(cols) - 1 else ''}")
    L += ['FROM sales.pnl_stg;', '']
    return '\n'.join(L)


# ── MySQL ────────────────────────────────────────────────────────
# MySQL 은 schema = database 라서 sales 스키마 대신 DB 를 하나 쓴다.
# 컬럼 COMMENT 는 CREATE TABLE 안에 인라인으로 들어간다.
MYSQL_DB = 'sales_pnl'


def my_type(c):
    t = c['type'].replace('numeric', 'decimal')
    return t


def gen_mysql(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = [f'-- MySQL 판. 엑셀 원본 {len(cols)} 컬럼 그대로.',
         '-- tot_* 는 원본에서 * 가 붙은 소계 라인이다 (하위 계정의 합계이므로 중복 집계 주의).',
         '-- MySQL 은 스키마와 DB 가 같은 개념이라 sales 스키마 대신 DB 를 하나 쓴다.',
         f'-- 다른 DB 에 넣으려면 아래 두 줄만 바꾸면 된다.',
         '',
         f'CREATE DATABASE IF NOT EXISTS {MYSQL_DB} '
         'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;',
         f'USE {MYSQL_DB};',
         '',
         'DROP TABLE IF EXISTS pnl_fact;',
         '',
         'CREATE TABLE pnl_fact (',
         '    pnl_id           bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,']
    for c in cols:
        if c['src'] in SECTIONS:
            L += ['', f"    -- ══ {SECTIONS[c['src']]} " + '═' * 8]
        typ = my_type(c) + (' NOT NULL' if c['not_null'] else '')
        cmt = c['src'].replace("\\", "\\\\").replace("'", "''")
        L.append(f"    {c['name']:<{w}}{typ:<22} COMMENT '{cmt}',")
    L += ['',
          '    -- ══ 적재 메타데이터 ════════',
          f"    {'source_file':<{w}}varchar(260),",
          f"    {'loaded_at':<{w}}datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),",
          '',
          '    -- 자연키: 같은 기간의 같은 고객 x 제품군 x 손익센터 조합은 1행.',
          '    -- 재적재 시 중복을 막아준다. 키 컬럼에 NULL 이 섞이는 소스라면 이 인덱스를 빼고',
          '    -- 적재 전 DELETE 로 해당 기간을 지우는 방식을 쓸 것.',
          '    UNIQUE KEY ux_pnl_fact_natural (',
          key_block(cols, indent='        '),
          '    ),',
          '    KEY ix_pnl_fact_period   (fiscal_year, period),',
          '    KEY ix_pnl_fact_customer (sold_to, fiscal_year, period),',
          '    KEY ix_pnl_fact_matgrp   (material_group, fiscal_year, period)',
          ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC",
          "  COMMENT='고객/제품군 단위 손익(P&L) 플랫 테이블. tot_* 는 엑셀 원본의 * 소계 라인.';",
          '']
    return '\n'.join(L)


def gen_mysql_view(cols):
    L = ['-- 엑셀 원본 헤더 그대로 내보내기용 뷰 (MySQL 은 식별자에 백틱을 쓴다).',
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
    L = ['-- 변환 함수 + 원본 TSV/CSV 를 그대로 받는 임시 테이블(전 컬럼 text).',
         '-- "1,268.93" 같은 천단위 콤마, 빈칸, #N/A 를 일단 통과시킨 뒤 04 에서 변환한다.',
         '--',
         '-- staging 없이 바로 넣고 싶으면 이 파일의 함수 부분만 실행하고',
         '-- 06_load_direct.sql 을 쓰면 된다. 그 편이 단계가 하나 적다.',
         f'USE {MYSQL_DB};',
         '',
         FUNCS,
         '',
         '-- 아래 text 251개 테이블은 MySQL 8 의 InnoDB 행 크기 제한(8126 byte)에 걸려',
         '-- 그냥 만들면 Error 1118 이 난다. 값이 실제로는 짧아서 DYNAMIC 행 포맷이',
         '-- 알아서 밖으로 빼주므로, 생성할 때만 strict 검사를 끄면 된다.',
         'SET SESSION innodb_strict_mode = OFF;',
         '',
         'DROP TABLE IF EXISTS pnl_stg;',
         'CREATE TABLE pnl_stg (']
    L += [f"    {c['name']:<{w}}text{',' if i < len(cols) - 1 else ''}"
          for i, c in enumerate(cols)]
    L += [') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;', '']
    return '\n'.join(L)


FUNCS = r"""
-- 엑셀식 숫자 문자열 → decimal   ("1,268.93", "(1,234)", "", "-", "#N/A")
DROP FUNCTION IF EXISTS to_num;
DROP FUNCTION IF EXISTS to_txt;
DELIMITER $$

CREATE FUNCTION to_num(v text) RETURNS decimal(18,4)
DETERMINISTIC
BEGIN
    DECLARE t varchar(64);
    SET t = REPLACE(REPLACE(REPLACE(TRIM(COALESCE(v, '')), ',', ''), '$', ''), ' ', '');
    IF t = '' OR t IN ('-', '#N/A', 'N/A', '#DIV/0!', '#VALUE!') THEN
        RETURN NULL;
    END IF;
    IF t LIKE '(%)' THEN                       -- 회계식 음수 표기 (12.50) → -12.50
        SET t = CONCAT('-', SUBSTRING(t, 2, CHAR_LENGTH(t) - 2));
    END IF;
    IF t NOT REGEXP '^-?[0-9]*\.?[0-9]+$' THEN
        RETURN NULL;
    END IF;
    RETURN CAST(t AS decimal(18,4));
END$$

-- 텍스트 차원값 정리: 앞뒤 공백 제거, 빈칸/#N/A 는 NULL
CREATE FUNCTION to_txt(v text) RETURNS varchar(260)
DETERMINISTIC
BEGIN
    DECLARE t varchar(260);
    SET t = TRIM(COALESCE(v, ''));
    IF t = '' OR t = '#N/A' THEN
        RETURN NULL;
    END IF;
    RETURN t;
END$$

DELIMITER ;
""".strip()


def gen_mysql_load(cols):
    L = ['-- staging → 팩트 변환 적재.',
         '--   1) TRUNCATE TABLE pnl_stg;',
         '--   2) 엑셀을 TSV 로 저장한 뒤 아래 중 하나로 적재',
         "--      LOAD DATA LOCAL INFILE 'pnl.tsv' INTO TABLE pnl_stg",
         "--          FIELDS TERMINATED BY '\\t' ESCAPED BY ''",
         "--          LINES TERMINATED BY '\\r\\n' IGNORE 1 LINES;",
         '--      (Workbench 는 Server > Options File > local_infile 을 켜야 한다.',
         '--       안 되면 테이블 우클릭 > Table Data Import Wizard 로 pnl_stg 에 넣어도 된다)',
         '--   3) 이 파일 실행',
         '--   4) TRUNCATE TABLE pnl_stg;',
         '',
         f'USE {MYSQL_DB};',
         '',
         'INSERT INTO pnl_fact (']
    L += [f"    {c['name']}{',' if i < len(cols) - 1 else ''}" for i, c in enumerate(cols)]
    L += [') SELECT']
    for i, c in enumerate(cols):
        expr = f"to_num({c['name']})" if c['numeric'] else f"to_txt({c['name']})"
        L.append(f"    {expr}{',' if i < len(cols) - 1 else ''}")
    L += ['FROM pnl_stg;', '']
    return '\n'.join(L)



def gen_mysql_infile(cols):
    """LOAD DATA LOCAL INFILE 용 명시적 컬럼 목록.

    파일 앞쪽에 테이블에 없는 컬럼이 몇 개 붙어 있으면, 그 개수만큼 목록 맨 앞을
    @skip1, @skip2 ... 로 바꾸면 된다. @변수로 받은 값은 그냥 버려진다.
    """
    L = ['-- 엑셀 TSV → pnl_stg 적재 (컬럼 목록 명시판).',
         '--',
         '-- 파일 맨 앞에 테이블에 없는 컬럼이 붙어 있으면(엑셀 인덱스 열, 예전 시트에만',
         '-- 있던 Account/Site/Ver/Flag/Month/PP1 등) 아래 목록 맨 앞의 컬럼명을 그 수만큼',
         '-- @skip1, @skip2 ... 로 바꾸면 된다. @변수로 받은 값은 테이블에 들어가지 않는다.',
         '--   예) 앞 3개 무시:   (@skip1, @skip2, @skip3, cus_group, record_type, ...)',
         '--',
         '-- 파일의 컬럼 순서가 테이블과 다를 때도 이 목록의 순서만 파일에 맞추면 된다.',
         '-- 헤더 줄은 IGNORE 1 LINES 로 건너뛴다. 엑셀에서 저장한 파일이면 보통',
         "-- LINES TERMINATED BY '\\r\\n' 이고, 리눅스/맥에서 만든 파일이면 '\\n' 이다.",
         '',
         f'USE {MYSQL_DB};',
         '',
         'TRUNCATE TABLE pnl_stg;',
         '',
         "LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/pnl.tsv'",
         '    INTO TABLE pnl_stg',
         "    FIELDS TERMINATED BY '\\t' ESCAPED BY ''",
         "    LINES TERMINATED BY '\\r\\n'",
         '    IGNORE 1 LINES',
         '(']
    for i, c in enumerate(cols):
        L.append(f"    {c['name']}{',' if i < len(cols) - 1 else ''}"
                 f"{'' if i else '                     -- ← 앞부터 버리려면 이 줄들을 @skip1, @skip2 ... 로'}")
    L += [');',
          '',
          'SELECT count(*) AS staged FROM pnl_stg;',
          '',
          '-- 이어서 04_load_from_staging.sql 실행 → 05_checks.sql 로 검산.',
          '']
    return '\n'.join(L)



def gen_mysql_direct(cols):
    """staging 없이 CSV/TSV → pnl_fact 직접 적재.

    각 필드를 @변수로 받아 SET 절에서 to_num()/to_txt() 로 변환해 넣는다.
    staging 테이블(text 251개)이 MySQL 8 의 행 크기 제한에 걸리는 걸 피할 수 있고
    단계도 하나 줄어든다. 03_staging.sql 의 함수 부분은 미리 실행돼 있어야 한다.
    """
    L = ['-- staging 없이 파일 → pnl_fact 직접 적재.',
         '-- 03_staging.sql 의 to_num()/to_txt() 함수가 먼저 만들어져 있어야 한다',
         '-- (그 파일에서 CREATE FUNCTION 두 개만 실행해도 된다).',
         '--',
         '-- 파일 형식에 맞춰 FIELDS/LINES 두 줄만 고치면 된다.',
         "--   콤마 CSV  : FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY ''",
         "--   탭 TSV    : FIELDS TERMINATED BY '\\t' ESCAPED BY ''",
         "--   윈도우 파일: LINES TERMINATED BY '\\r\\n'   / 그 외: '\\n'",
         '--',
         '-- 파일에 테이블로 안 옮길 컬럼이 섞여 있으면, 그 자리 @변수를 SET 절에서 빼기만',
         '-- 하면 된다. @변수는 SET 에서 안 쓰면 그냥 버려진다.',
         '--',
         '-- LOCAL 을 쓰면 자연키 중복이 에러가 아니라 경고(1062)로 처리되고 그 행은',
         '-- 조용히 건너뛴다. 두 번 돌려도 중복이 쌓이진 않지만, 몇 행이 들어갔는지는',
         '-- 아래 SHOW WARNINGS 와 행 수로 직접 확인할 것.',
         '',
         f'USE {MYSQL_DB};',
         '',
         "LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/salesDTC/rawdata/sales_2526.csv'",
         '    INTO TABLE pnl_fact',
         "    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY ''",
         "    LINES TERMINATED BY '\\r\\n'",
         '    IGNORE 1 LINES',
         '(']
    L += [f"    @{c['name']}{',' if i < len(cols) - 1 else ''}"
          for i, c in enumerate(cols)]
    L += [')', 'SET']
    for i, c in enumerate(cols):
        fn = 'to_num' if c['numeric'] else 'to_txt'
        L.append(f"    {c['name']} = {fn}(@{c['name']}){',' if i < len(cols) - 1 else ';'}")
    L += ['',
          'SELECT count(*) AS loaded FROM pnl_fact;',
          'SHOW WARNINGS;',
          '',
          '-- 이어서 05_checks.sql 로 검산 (아무 행도 안 나오면 정상).',
          '']
    return '\n'.join(L)



# ── 한 파일로 끝나는 MySQL 셋업 (DB 생성 → 테이블 → INFILE 적재) ──────
ONESHOT_DB = 'sales_2526'
ONESHOT_FILE = 'C:/work/sales_dashboard/salesDTC/rawdata/sales_2526.csv'


def gen_mysql_oneshot(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = [f'-- sales_2526 한 방 셋업: DB 생성 → 테이블 생성 → CSV 적재.',
         '-- MySQL Workbench 에서 이 파일을 열고 ⚡(Execute All) 한 번이면 끝난다.',
         '--',
         '-- 실행 전 확인 두 가지',
         '--   1) 아래 LOAD DATA 의 파일 경로. 슬래시는 / 로 쓸 것 (\\ 는 이스케이프로 먹힌다).',
         "--   2) Workbench 연결 설정 > Advanced > Others 에 OPT_LOCAL_INFILE=1 (없으면 3948).",
         '--',
         '-- 파일이 탭 구분(TSV)이면 FIELDS 줄을 이렇게 바꾼다:',
         "--     FIELDS TERMINATED BY '\\t' ESCAPED BY ''",
         '',
         'SET GLOBAL local_infile = 1;',
         '',
         f'CREATE DATABASE IF NOT EXISTS {ONESHOT_DB} '
         'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;',
         f'USE {ONESHOT_DB};',
         '',
         '-- ── 1. 엑셀 값 정리용 함수 두 개 ────────────────────────────',
         '--    "1,268.93" → 1268.93,  "" / "#N/A" → NULL,  "(12.50)" → -12.50',
         '',
         FUNCS,
         '',
         '-- ── 2. 테이블 ───────────────────────────────────────────────',
         '--    컬럼 순서는 엑셀 시트와 1:1. 주석은 원본 헤더다.',
         '',
         'DROP TABLE IF EXISTS pnl_fact;',
         'CREATE TABLE pnl_fact (',
         '    pnl_id           bigint NOT NULL AUTO_INCREMENT PRIMARY KEY,']
    for c in cols:
        if c['src'] in SECTIONS:
            L += ['', f"    -- ══ {SECTIONS[c['src']]} " + '═' * 8]
        typ = my_type(c) + (' NOT NULL' if c['not_null'] else '')
        cmt = c['src'].replace("'", "''")
        L.append(f"    {c['name']:<{w}}{typ:<22} COMMENT '{cmt}',")
    L += ['',
          f"    {'loaded_at':<{w}}datetime(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),",
          '',
          '    -- 같은 기간의 같은 고객 x 제품군 조합은 1행. 실수로 두 번 적재해도',
          '    -- 중복이 쌓이지 않는다 (LOCAL 적재에서는 에러 대신 경고 1062 로 건너뛴다).',
          '    UNIQUE KEY ux_pnl_fact_natural (',
          key_block(cols, indent='        '),
          '    ),',
          '    KEY ix_pnl_fact_period   (fiscal_year, period),',
          '    KEY ix_pnl_fact_customer (sold_to, fiscal_year, period),',
          '    KEY ix_pnl_fact_matgrp   (material_group, fiscal_year, period)',
          ') ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC;',
          '',
          '-- ── 3. CSV 적재 ────────────────────────────────────────────',
          '--    파일의 각 필드를 @변수로 받아 위 함수로 변환해 넣는다.',
          '',
          f"LOAD DATA LOCAL INFILE '{ONESHOT_FILE}'",
          '    INTO TABLE pnl_fact',
          "    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '\"' ESCAPED BY ''",
          "    LINES TERMINATED BY '\\r\\n'",
          '    IGNORE 1 LINES          -- 헤더 줄 건너뛰기',
          '(']
    L += [f"    @{c['name']}{',' if i < len(cols) - 1 else ''}" for i, c in enumerate(cols)]
    L += [')', 'SET']
    for i, c in enumerate(cols):
        fn = 'to_num' if c['numeric'] else 'to_txt'
        L.append(f"    {c['name']} = {fn}(@{c['name']}){',' if i < len(cols) - 1 else ';'}")
    L += ['',
          '-- ── 4. 확인 ────────────────────────────────────────────────',
          '',
          'SELECT count(*) AS loaded_rows FROM pnl_fact;',
          'SHOW WARNINGS;',
          '',
          '-- 값이 제자리에 들어갔는지 눈으로 확인',
          'SELECT sold_to, material_group, prod_group, period,',
          '       tot_net_sales, tot_cogs, tot_gross_margin, tot_operating_profit',
          'FROM   pnl_fact',
          'LIMIT  5;',
          '',
          '-- 검산: 아래 네 줄이 전부 0 이면 컬럼이 밀리지 않은 것이다.',
          'SELECT',
          '    sum(abs(tot_net_sales - (tot_s_gross_sales - tot_sales_deduction)) > 0.05) '
          'AS err_net_sales,',
          '    sum(abs(tot_gross_margin - (tot_net_sales - tot_cogs)) > 0.05) '
          'AS err_gross_margin,',
          '    sum(abs(tot_operating_expense - (tot_sales_expense + tot_r_and_d_expense '
          '+ tot_g_and_a_expense)) > 0.05) AS err_op_expense,',
          '    sum(abs(tot_operating_profit - (tot_gross_margin - tot_operating_expense)) > 0.05) '
          'AS err_op_profit',
          'FROM pnl_fact;',
          '']
    return '\n'.join(L)



def main():
    cols = load_columns()
    write('sql/postgres/01_pnl_fact.sql', gen_postgres(cols))
    write('sql/postgres/02_v_pnl_excel.sql', gen_view(cols))
    write('sql/postgres/03_staging.sql', gen_staging(cols))
    write('sql/postgres/04_load_from_staging.sql', gen_load(cols))
    write('sql/sqlserver/01_pnl_fact.sql', gen_sqlserver(cols))
    write('sql/mysql/01_pnl_fact.sql', gen_mysql(cols))
    write('sql/mysql/02_v_pnl_excel.sql', gen_mysql_view(cols))
    write('sql/mysql/03_staging.sql', gen_mysql_staging(cols))
    write('sql/mysql/04_load_from_staging.sql', gen_mysql_load(cols))
    write('sql/mysql/00_setup_sales_2526.sql', gen_mysql_oneshot(cols))
    write('sql/mysql/06_load_direct.sql', gen_mysql_direct(cols))
    write('sql/mysql/07_load_infile_columns.sql', gen_mysql_infile(cols))
    with open(os.path.join(ROOT, 'docs', 'column_map.csv'), 'w', newline='',
              encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['pos', 'excel_header', 'column_name', 'postgres_type', 'is_subtotal'])
        w.writerows([[c['pos'], c['src'], c['name'], c['type'], 'Y' if c['total'] else '']
                     for c in cols])
    print('wrote docs/column_map.csv')
    print(f'{len(cols)} columns, {sum(c["total"] for c in cols)} subtotal(*) lines')
    print('natural key:', ', '.join(natural_key(cols)))


if __name__ == '__main__':
    main()

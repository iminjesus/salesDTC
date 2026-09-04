#!/usr/bin/env python3
"""docs/excel_header.txt (엑셀 원본 헤더 1줄, tab 구분) 로부터 DDL 을 생성한다.

    python3 tools/generate_ddl.py

산출물
    sql/postgres/01_pnl_fact.sql          팩트 테이블 + 인덱스 + 컬럼 COMMENT
    sql/postgres/02_v_pnl_excel.sql       엑셀 원본 헤더로 되돌려주는 뷰
    sql/postgres/03_staging.sql           TSV 를 그대로 받는 text staging + 변환 함수
    sql/postgres/04_load_from_staging.sql staging → 팩트 변환 INSERT
    sql/sqlserver/01_pnl_fact.sql         SQL Server 판 팩트 테이블
    docs/column_map.csv                   엑셀 헤더 ↔ 컬럼명 ↔ 타입 매핑표

헤더가 바뀌면 excel_header.txt 만 갈아끼우고 다시 돌리면 된다.
"""
import csv
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEADER = os.path.join(ROOT, 'docs', 'excel_header.txt')

# ── 컬럼명 규칙 ────────────────────────────────────────────────────
# 위치(1-based)로 직접 지정하는 이름. 엑셀 헤더가 중복(Currency/Division)이거나
# 약어라서 자동 변환만으로는 구분이 안 되는 앞쪽 27개 컬럼에 쓴다.
POS = {
    1:  'cus_group',      2:  'account',        3:  'site',
    4:  'record_type',    5:  'report_currency',6:  'division2',
    7:  'division',       8:  'fiscal_year',    9:  'version',
    10: 'sold_to',        11: 'forex_rate',     12: 'sales_usd',
    13: 'op_profit_usd',  14: 'flag',           15: 'month_nm',
    16: 'pp1',            17: 'customer',       18: 'material_group',
    19: 'nielsen_id',     20: 'profit_center',  21: 'sap_division',
    22: 'distribution_channel',                 23: 'period',
    24: 'doc_currency',   25: 'qty_gross',      26: 'qty_return',
    27: 'qty_net',
}

# 원본 표기가 오타이거나 자동 변환 결과가 헷갈리는 항목만 손으로 지정.
# 원본 문자열은 COMMENT / 매핑표에 그대로 남는다.
NAME = {
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

# 엑셀 원본의 블록 경계 — DDL 에 섹션 주석으로 들어간다.
SECTIONS = {
    1:   '헤더/집계 키 (엑셀 좌측 블록)',
    17:  'SAP 원장 차원 (Dimension)',
    25:  '수량 (Quantity)',
    28:  '매출 (Sales)',
    53:  '매출원가 (Cost of Goods Sold)',
    136: '매출총이익 / 판관비 (Gross Margin & Operating Expense)',
    196: '연구개발비 (R&D Expense)',
    208: '일반관리비 (G&A Expense)',
    228: '영업이익 이하 (Operating Profit & below)',
}

# 엑셀 헤더가 중복이라 뷰에서 그대로 못 쓰는 것들 (SQL 은 동일 별칭 2개를 허용 안 함)
VIEW_ALIAS = {5: 'Currency (Report)', 7: 'Division (P&L)'}

# 앞쪽 27개 중 숫자형 컬럼
NUMERIC_HEAD = {8, 11, 12, 13, 25, 26, 27}

TYPES = {
    1: 'varchar(20)',  2: 'varchar(20)',  3: 'varchar(20)',  4: 'varchar(10)',
    5: 'varchar(10)',  6: 'varchar(20)',  7: 'varchar(20)',  8: 'smallint',
    9: 'varchar(20)',  10: 'varchar(20)', 11: 'numeric(18,9)', 12: 'numeric(18,2)',
    13: 'numeric(18,2)', 14: 'varchar(10)', 15: 'varchar(10)', 16: 'varchar(20)',
    17: 'varchar(20)', 18: 'varchar(20)', 19: 'varchar(20)', 20: 'varchar(20)',
    21: 'varchar(10)', 22: 'varchar(10)', 23: 'varchar(10)', 24: 'varchar(10)',
    25: 'numeric(18,3)', 26: 'numeric(18,3)', 27: 'numeric(18,3)',
}
MEASURE = 'numeric(18,2)'          # 28번 이후 손익 계정 전부
NOT_NULL = {8, 9, 23}              # Year / Ver / Period

NATURAL_KEY = ('fiscal_year, version, period, sold_to, material_group,\n'
               '    profit_center, sap_division, distribution_channel, doc_currency')


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
    cols, used = [], set()
    for pos, src in enumerate(headers, 1):
        name = POS.get(pos) or NAME.get(src) or normalize(src)
        if name in used:
            raise SystemExit(f'컬럼명 충돌: {name} (pos {pos}, {src!r}) — POS/NAME 에 지정할 것')
        used.add(name)
        cols.append({
            'pos': pos,
            'src': src,
            'name': name,
            'total': src.startswith('*'),
            'type': TYPES.get(pos, MEASURE),
            'numeric': pos > 27 or pos in NUMERIC_HEAD,
        })
    return cols


def write(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    print('wrote', rel)


def column_lines(cols, width, sqlserver=False):
    out = []
    for c in cols:
        if c['pos'] in SECTIONS:
            out += ['', f"    -- ══ {SECTIONS[c['pos']]} " + '═' * 8]
        typ = c['type'].replace('numeric', 'decimal') if sqlserver else c['type']
        typ += ' NOT NULL' if c['pos'] in NOT_NULL else ''
        out.append(f"    {c['name']:<{width}}{(typ + ','):<24}-- {c['src']}")
    return out


def gen_postgres(cols):
    w = max(len(c['name']) for c in cols) + 2
    L = ['-- 고객 x 제품군 단위 손익(P&L) 플랫 테이블 — 엑셀 원본 258 컬럼 그대로.',
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
          '-- 자연키: 같은 연도/버전/기간의 같은 고객 x 제품군 x 손익센터 조합은 1행.',
          '-- 재적재 시 중복을 막아준다. 키 컬럼에 NULL 이 섞이는 소스라면 이 인덱스는 빼고',
          '-- 적재 전 DELETE 로 해당 기간을 지우는 방식을 쓸 것.',
          'CREATE UNIQUE INDEX ux_pnl_fact_natural ON sales.pnl_fact (',
          f'    {NATURAL_KEY}',
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
          f'    {NATURAL_KEY}',
          ');',
          'CREATE INDEX ix_pnl_fact_period   ON sales.pnl_fact (fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_customer ON sales.pnl_fact (sold_to, fiscal_year, period);',
          'CREATE INDEX ix_pnl_fact_matgrp   ON sales.pnl_fact (material_group, fiscal_year, period);',
          'GO',
          '']
    return '\n'.join(L) + '\n'


def gen_view(cols):
    L = ['-- 엑셀 원본 헤더 그대로 내보내기용 뷰.',
         '--   \\copy (SELECT * FROM sales.v_pnl_excel) TO \'pnl.csv\' WITH (FORMAT csv, HEADER true)',
         '-- 원본은 Currency / Division 헤더가 두 번씩 나오는데 SQL 은 같은 별칭을 두 번 못 쓰므로',
         '-- 앞쪽(집계 헤더) 것에만 구분자를 붙였다.',
         'CREATE OR REPLACE VIEW sales.v_pnl_excel AS',
         'SELECT']
    for i, c in enumerate(cols):
        alias = VIEW_ALIAS.get(c['pos'], c['src'])
        L.append(f"    {c['name']:<30} AS \"{alias}\"{',' if i < len(cols) - 1 else ''}")
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
        cast = '::smallint' if c['pos'] == 8 else ''
        L.append(f"    {fn}({c['name']}){cast}{',' if i < len(cols) - 1 else ''}")
    L += ['FROM sales.pnl_stg;', '']
    return '\n'.join(L)


def gen_map(cols):
    rows = [['pos', 'excel_header', 'column_name', 'postgres_type', 'is_subtotal']]
    rows += [[c['pos'], c['src'], c['name'], c['type'], 'Y' if c['total'] else '']
             for c in cols]
    return rows


def main():
    cols = load_columns()
    write('sql/postgres/01_pnl_fact.sql', gen_postgres(cols))
    write('sql/postgres/02_v_pnl_excel.sql', gen_view(cols))
    write('sql/postgres/03_staging.sql', gen_staging(cols))
    write('sql/postgres/04_load_from_staging.sql', gen_load(cols))
    write('sql/sqlserver/01_pnl_fact.sql', gen_sqlserver(cols))
    with open(os.path.join(ROOT, 'docs', 'column_map.csv'), 'w', newline='',
              encoding='utf-8') as f:
        csv.writer(f).writerows(gen_map(cols))
    print('wrote docs/column_map.csv')
    print(f'{len(cols)} columns, {sum(c["total"] for c in cols)} subtotal(*) lines')


if __name__ == '__main__':
    main()

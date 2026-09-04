# salesDTC — 고객/제품군 단위 손익(P&L) 테이블

엑셀로 관리하던 251컬럼짜리 손익 시트를 그대로 담는 DB 스키마와, 그 시트를 적재하는
스크립트다. 컬럼 순서·의미는 원본 헤더와 1:1로 대응하며, 매핑표는 `docs/column_map.csv`에 있다.

## 테이블 구조

`sales.pnl_fact` — 1행 = **연도 x 기간 x 고객(sold_to) x 제품군(material_group) x
손익센터 x 사업부 x 유통채널 x 통화** 한 조합의 손익.

| 블록 | 컬럼 | 예 |
|---|---|---|
| 헤더/집계 키 | 1–9 | `cus_group`, `record_type`, `division2`, `prod_group`, `fiscal_year`, `sold_to`, `forex_rate`, `sales_usd`, `op_profit_usd` |
| SAP 원장 차원 | 10–17 | `customer`, `material_group`, `nielsen_id`, `profit_center`, `sap_division`, `distribution_channel`, `period`, `doc_currency` |
| 수량 | 18–20 | `qty_gross`, `qty_return`, `qty_net` |
| 손익 계정 | 21–251 | `s_*` 매출, `sc_*` 매출원가, `sa_*` 판매비, `rd_*` 연구개발비, `ga_*` 일반관리비, `op_*`/`oe_*` 영업외, `eg_*`/`el_*` 지분법, `fp_*`/`fe_*` 금융손익 |

명명 규칙 두 가지만 알면 된다.

- 원본에서 `*`가 붙은 **소계 라인 51개**는 `tot_` 접두사를 쓴다 (`*Net Sales` → `tot_net_sales`).
  하위 계정의 합계이므로 `sum(tot_*)`와 `sum(하위 계정)`을 같이 더하면 이중 집계가 된다.
- 계정 접두사 `S.` `SC.` `SA.` `RD.` `GA.` …는 그대로 소문자 접두사로 남는다
  (`SC.Mfg Repair&Maint` → `sc_mfg_repair_and_maint`).

헷갈리기 쉬운 세 컬럼은 이름을 풀어 뒀다. 셋 다 서로 다른 축이다.

| 원본 헤더 | 값 예 | 컬럼명 | 뜻 |
|---|---|---|---|
| Division 2 | `DA` | `division2` | 사업본부 |
| Prod_group | `REF`, `MWO` | `prod_group` | 제품군 |
| Division | `E2`, `E5` | `sap_division` | SAP 사업부 |
| Currency | `AUD` | `doc_currency` | 전표 통화 (`sales_usd`는 `forex_rate`로 환산한 USD) |

## 파일

| 파일 | 내용 |
|---|---|
| `sql/postgres/01_pnl_fact.sql` | 팩트 테이블 + 인덱스 + 컬럼 COMMENT(원본 헤더 보존) |
| `sql/postgres/02_v_pnl_excel.sql` | 원본 엑셀 헤더 그대로 되돌려주는 내보내기 뷰 |
| `sql/postgres/03_staging.sql` | TSV를 그대로 받는 text staging + 숫자/문자 정리 함수 |
| `sql/postgres/04_load_from_staging.sql` | staging → 팩트 변환 INSERT |
| `sql/postgres/05_checks.sql` | 적재 검산 (0행이면 정상) |
| `sql/mysql/01_pnl_fact.sql` ~ `05_checks.sql` | MySQL 판 한 벌 (Workbench 용) |
| `sql/mysql/06_load_direct.sql` | staging 없이 파일 → `pnl_fact` 직접 적재 (MySQL 권장 경로) |
| `sql/mysql/07_load_infile_columns.sql` | staging 적재용 컬럼 목록 명시판 — 버릴 컬럼·순서 불일치용 |
| `sql/sqlserver/01_pnl_fact.sql` | SQL Server 판 팩트 테이블 |
| `docs/column_map.csv` | 엑셀 헤더 ↔ 컬럼명 ↔ 타입 매핑표 258행 |
| `docs/excel_header.txt` | 원본 헤더 한 줄 (생성 입력) |
| `tools/generate_ddl.py` | 위 SQL 전부를 헤더에서 재생성 |

## 적재 — MySQL (Workbench)

```sql
-- Workbench 에서 순서대로 열어 실행
sql/mysql/01_pnl_fact.sql        -- DB(sales_pnl) + 테이블
sql/mysql/02_v_pnl_excel.sql     -- 엑셀 헤더 복원 뷰
sql/mysql/03_staging.sql         -- staging + to_num()/to_txt()
```

엑셀을 **탭 구분 TSV**로 저장한 뒤:

```sql
USE sales_pnl;
TRUNCATE TABLE pnl_stg;
LOAD DATA LOCAL INFILE 'C:/work/sales_dashboard/pnl.tsv' INTO TABLE pnl_stg
    FIELDS TERMINATED BY '\t' ESCAPED BY ''
    LINES TERMINATED BY '\r\n' IGNORE 1 LINES;
```

**staging 을 건너뛰는 쪽이 더 간단하다.** `03_staging.sql` 의 함수 두 개만 만들어 두고
`sql/mysql/06_load_direct.sql` 을 쓰면 파일에서 `pnl_fact` 로 바로 들어간다.
각 필드를 `@변수`로 받아 `SET` 절에서 `to_num()`/`to_txt()` 로 변환하는 방식이라,
천단위 콤마와 `#N/A` 를 그대로 처리하면서 단계가 하나 줄어든다.

파일에 컬럼이 더 있거나 순서가 다르면 그 자리 `@변수`를 `SET` 절에서 빼기만 하면 된다
(staging 경로라면 `07_load_infile_columns.sql` 에서 컬럼명을 `@skip1, @skip2 ...` 로 바꾼다).

`LOCAL` 을 쓰면 자연키 중복이 에러가 아니라 **경고 1062** 로 처리되고 그 행은 조용히
건너뛴다. 두 번 돌려도 중복이 쌓이진 않지만, 적재 후 `SHOW WARNINGS` 와 행 수는 꼭 확인할 것.

staging 테이블(text 251개)은 MySQL 8 의 InnoDB 행 크기 제한(8126 byte) 때문에 그냥
만들면 `Error 1118` 이 난다. `03_staging.sql` 은 생성 직전에 `innodb_strict_mode` 를
꺼서 이를 피한다 (값이 짧아 DYNAMIC 행 포맷이 알아서 밖으로 뺀다). MariaDB 는 이 제한에
걸리지 않는다.

`LOAD DATA LOCAL INFILE` 가 막히면(`local_infile` 비활성) Workbench 좌측 스키마 트리에서
`pnl_stg` 우클릭 → **Table Data Import Wizard** 로 넣어도 된다. 그 다음:

```sql
-- sql/mysql/04_load_from_staging.sql  실행 → 변환 적재
-- sql/mysql/05_checks.sql             실행 → 검산 (아무 행도 안 나오면 정상)
TRUNCATE TABLE pnl_stg;
```

MySQL 은 스키마와 DB 가 같은 개념이라 `sales` 스키마 대신 `sales_pnl` DB 를 쓴다.
다른 DB 에 넣으려면 각 파일 첫머리의 `CREATE DATABASE` / `USE` 두 줄만 바꾸면 된다.

## 적재 — PostgreSQL

```sh
psql -f sql/postgres/01_pnl_fact.sql
psql -f sql/postgres/02_v_pnl_excel.sql
psql -f sql/postgres/03_staging.sql
```

엑셀을 **탭 구분 TSV**로 저장한 뒤:

```sh
psql -c "TRUNCATE sales.pnl_stg;" \
     -c "\copy sales.pnl_stg FROM 'pnl.tsv' WITH (FORMAT csv, DELIMITER E'\t', HEADER true, QUOTE E'\b')" \
     -f sql/postgres/04_load_from_staging.sql \
     -f sql/postgres/05_checks.sql \
     -c "TRUNCATE sales.pnl_stg;"
```

staging을 한 단계 거치는 이유는 원본 값이 `1,268.93`(천단위 콤마), 빈칸, `#N/A`,
`(12.50)`(회계식 음수) 형태로 섞여 들어와 `numeric`으로 바로 COPY가 안 되기 때문이다.
`sales.to_num()` / `sales.to_txt()`가 이 네 가지를 처리한다.

## 재생성

헤더가 바뀌면 `docs/excel_header.txt`만 갈아끼우고 다시 돌린다.

```sh
python3 tools/generate_ddl.py
```

컬럼명 예외(오타 보정, 중복 헤더 구분)는 `tools/generate_ddl.py`의 `POS` / `NAME` 딕셔너리에 모아뒀다.

## 검증 상태

PostgreSQL 16, MySQL 8.0.46, MariaDB 10.11 에서 각각 실행해 254컬럼
(251 + `pnl_id` + `source_file` + `loaded_at`) 생성, 샘플 2행(REF/MWO)을 TSV로
staging 적재·변환, 자연키 중복 적재 차단, `v_pnl_excel`로 원본 헤더 복원,
`05_checks.sql`의 5개 검산식 통과까지 확인했다. MySQL 8 에서는 엑셀이 저장한
콤마 CSV(따옴표로 감싼 `"1,268.93"` 포함)로 staging 경로와 직접 적재 경로를 모두 확인했다.
SQL Server 판은 문법만 맞춰 생성했고 실행 검증은 하지 않았다.

## 남은 판단거리

- **자연키 유니크 인덱스** — `ux_pnl_fact_natural`은 `fiscal_year, period, sold_to,
  material_group, profit_center, sap_division, distribution_channel, doc_currency`
  8개 조합을 유일하게 본다. 이전 시트에 있던 `Ver`(버전)이 빠져서, 같은 기간을 버전만
  바꿔 두 번 넣으면 충돌한다. 버전을 나란히 두려면 `Ver` 컬럼을 시트에 되살리거나
  (그러면 생성기가 자동으로 키에 넣는다) 적재 전 해당 기간을 `DELETE` 하면 된다.
- **`*Profit Before Tax`의 구성식** — 영업외/지분법/금융손익의 부호 규약이 샘플만으로는
  확정되지 않아 `05_checks.sql`에 넣지 않았다. 규약이 정해지면 검산식을 추가하면 된다.
- 금액 정밀도는 `numeric(18,2)`, 수량은 `numeric(18,3)`, 환율은 `numeric(18,9)`로 잡았다.

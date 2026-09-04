# salesDTC — 고객/제품군 단위 손익(P&L) 테이블

엑셀로 관리하던 258컬럼짜리 손익 시트를 그대로 담는 DB 스키마와, 그 시트를 적재하는
스크립트다. 컬럼 순서·의미는 원본 헤더와 1:1로 대응하며, 매핑표는 `docs/column_map.csv`에 있다.

## 테이블 구조

`sales.pnl_fact` — 1행 = **연도 x 버전 x 기간 x 고객(sold_to) x 제품군(material_group) x
손익센터 x 사업부 x 유통채널 x 통화** 한 조합의 손익.

| 블록 | 컬럼 | 예 |
|---|---|---|
| 헤더/집계 키 | 1–16 | `cus_group`, `record_type`, `report_currency`, `division2`, `fiscal_year`, `version`, `sold_to`, `forex_rate`, `sales_usd`, `op_profit_usd` |
| SAP 원장 차원 | 17–24 | `customer`, `material_group`, `nielsen_id`, `profit_center`, `sap_division`, `distribution_channel`, `period`, `doc_currency` |
| 수량 | 25–27 | `qty_gross`, `qty_return`, `qty_net` |
| 손익 계정 | 28–258 | `s_*` 매출, `sc_*` 매출원가, `sa_*` 판매비, `rd_*` 연구개발비, `ga_*` 일반관리비, `op_*`/`oe_*` 영업외, `eg_*`/`el_*` 지분법, `fp_*`/`fe_*` 금융손익 |

명명 규칙 두 가지만 알면 된다.

- 원본에서 `*`가 붙은 **소계 라인 51개**는 `tot_` 접두사를 쓴다 (`*Net Sales` → `tot_net_sales`).
  하위 계정의 합계이므로 `sum(tot_*)`와 `sum(하위 계정)`을 같이 더하면 이중 집계가 된다.
- 계정 접두사 `S.` `SC.` `SA.` `RD.` `GA.` …는 그대로 소문자 접두사로 남는다
  (`SC.Mfg Repair&Maint` → `sc_mfg_repair_and_maint`).

원본 헤더에 **같은 이름이 두 번** 나오는 컬럼이 둘 있어 이렇게 갈랐다.

| 원본 헤더 | 위치 | 컬럼명 |
|---|---|---|
| Currency | 5 (집계 블록, 값 `(USD)`) | `report_currency` |
| Currency | 24 (원장, 값 `AUD`) | `doc_currency` |
| Division | 7 (집계 블록, 값 `REF`/`CTV`) | `division` |
| Division | 21 (SAP, 값 `E2`/`A1`) | `sap_division` |

## 파일

| 파일 | 내용 |
|---|---|
| `sql/postgres/01_pnl_fact.sql` | 팩트 테이블 + 인덱스 + 컬럼 COMMENT(원본 헤더 보존) |
| `sql/postgres/02_v_pnl_excel.sql` | 원본 엑셀 헤더 그대로 되돌려주는 내보내기 뷰 |
| `sql/postgres/03_staging.sql` | TSV를 그대로 받는 text staging + 숫자/문자 정리 함수 |
| `sql/postgres/04_load_from_staging.sql` | staging → 팩트 변환 INSERT |
| `sql/postgres/05_checks.sql` | 적재 검산 (0행이면 정상) |
| `sql/sqlserver/01_pnl_fact.sql` | SQL Server 판 팩트 테이블 |
| `docs/column_map.csv` | 엑셀 헤더 ↔ 컬럼명 ↔ 타입 매핑표 258행 |
| `docs/excel_header.txt` | 원본 헤더 한 줄 (생성 입력) |
| `tools/generate_ddl.py` | 위 SQL 전부를 헤더에서 재생성 |

## 적재

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

PostgreSQL 16에서 01–05를 실행해 261컬럼(258 + `pnl_id` + `source_file` + `loaded_at`) 생성,
콤마/빈칸/`#N/A`/회계식 음수가 섞인 TSV의 staging 적재·변환, 자연키 중복 적재 차단,
그리고 `05_checks.sql`의 5개 검산식이 샘플 행 값에서 모두 통과하는 것까지 확인했다.
SQL Server 판은 문법만 맞춰 생성했고 실행 검증은 하지 않았다.

## 남은 판단거리

- **자연키 유니크 인덱스** — `ux_pnl_fact_natural`은 위 9개 키 컬럼 조합을 유일하게 본다.
  실제 소스에서 이 조합이 한 행으로 유일한지 확인이 필요하다. 키 컬럼에 NULL이 섞이는
  소스라면 인덱스를 빼고, 적재 전에 해당 기간을 `DELETE`하는 방식이 안전하다.
- **`*Profit Before Tax`의 구성식** — 영업외/지분법/금융손익의 부호 규약이 샘플만으로는
  확정되지 않아 `05_checks.sql`에 넣지 않았다. 규약이 정해지면 검산식을 추가하면 된다.
- 금액 정밀도는 `numeric(18,2)`, 수량은 `numeric(18,3)`, 환율은 `numeric(18,9)`로 잡았다.

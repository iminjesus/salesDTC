-- 적재 검산. 붙여준 샘플 행에서 실제로 성립하는 관계식만 넣었다.
-- 각 쿼리는 "어긋난 행"을 돌려주므로, 0행이면 정상이다.
-- (엑셀 소계 * 라인을 그대로 담은 tot_* 컬럼끼리의 관계이므로,
--  ETL 이 컬럼을 밀려 넣었는지 잡아내는 용도로 쓰면 좋다.)

\set tol 0.05

-- 1) *Net Sales = *S.Gross Sales - *Sales Deduction
SELECT 'net_sales' AS check, pnl_id, sold_to, material_group,
       tot_net_sales, tot_s_gross_sales, tot_sales_deduction,
       tot_net_sales - (tot_s_gross_sales - tot_sales_deduction) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_net_sales - (tot_s_gross_sales - tot_sales_deduction)) > :tol;

-- 2) *Gross Margin = *Net Sales - *Cost of Goods Sold
SELECT 'gross_margin' AS check, pnl_id, sold_to, material_group,
       tot_gross_margin, tot_net_sales, tot_cogs,
       tot_gross_margin - (tot_net_sales - tot_cogs) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_gross_margin - (tot_net_sales - tot_cogs)) > :tol;

-- 3) *Operating Expense = *Sales Expense + *R&D Expense + *G&A Expense
SELECT 'operating_expense' AS check, pnl_id, sold_to, material_group,
       tot_operating_expense, tot_sales_expense, tot_r_and_d_expense, tot_g_and_a_expense,
       tot_operating_expense
         - (tot_sales_expense + tot_r_and_d_expense + tot_g_and_a_expense) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_operating_expense
           - (tot_sales_expense + tot_r_and_d_expense + tot_g_and_a_expense)) > :tol;

-- 4) *Operating Profit = *Gross Margin - *Operating Expense
SELECT 'operating_profit' AS check, pnl_id, sold_to, material_group,
       tot_operating_profit, tot_gross_margin, tot_operating_expense,
       tot_operating_profit - (tot_gross_margin - tot_operating_expense) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_operating_profit - (tot_gross_margin - tot_operating_expense)) > :tol;

-- 5) 환산 검산: Sales U$ ≈ *Net Sales x Forex  (엑셀 좌측 집계 블록 vs 원장)
--    반올림 차이가 있어 허용오차를 크게 잡는다.
SELECT 'sales_usd' AS check, pnl_id, sold_to, material_group,
       sales_usd, tot_net_sales, forex_rate,
       sales_usd - tot_net_sales * forex_rate AS diff
FROM   sales.pnl_fact
WHERE  forex_rate IS NOT NULL
  AND  abs(sales_usd - tot_net_sales * forex_rate) > 1.0;

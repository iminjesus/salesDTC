-- Load reconciliation. Only relationships that actually hold in the source rows.
-- Each query returns the rows that break the rule, so zero rows means it is fine.
-- These compare the sheet's * subtotal lines against each other, which is what
-- catches an ETL that shifted columns by one.

\set tol 0.05

-- 1) *Net Sales = *S.Gross Sales - *Sales Deduction
SELECT 'net_sales' AS check_name, pnl_id, sold_to, material_group,
       tot_net_sales, tot_s_gross_sales, tot_sales_deduction,
       tot_net_sales - (tot_s_gross_sales - tot_sales_deduction) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_net_sales - (tot_s_gross_sales - tot_sales_deduction)) > :tol;

-- 2) *Gross Margin = *Net Sales - *Cost of Goods Sold
SELECT 'gross_margin' AS check_name, pnl_id, sold_to, material_group,
       tot_gross_margin, tot_net_sales, tot_cogs,
       tot_gross_margin - (tot_net_sales - tot_cogs) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_gross_margin - (tot_net_sales - tot_cogs)) > :tol;

-- 3) *Operating Expense = *Sales Expense + *R&D Expense + *G&A Expense
SELECT 'operating_expense' AS check_name, pnl_id, sold_to, material_group,
       tot_operating_expense, tot_sales_expense, tot_r_and_d_expense, tot_g_and_a_expense,
       tot_operating_expense
         - (tot_sales_expense + tot_r_and_d_expense + tot_g_and_a_expense) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_operating_expense
           - (tot_sales_expense + tot_r_and_d_expense + tot_g_and_a_expense)) > :tol;

-- 4) *Operating Profit = *Gross Margin - *Operating Expense
SELECT 'operating_profit' AS check_name, pnl_id, sold_to, material_group,
       tot_operating_profit, tot_gross_margin, tot_operating_expense,
       tot_operating_profit - (tot_gross_margin - tot_operating_expense) AS diff
FROM   sales.pnl_fact
WHERE  abs(tot_operating_profit - (tot_gross_margin - tot_operating_expense)) > :tol;

-- 5) Currency translation: Sales U$ ~ *Net Sales x Forex (aggregation block vs ledger).
--    Rounding differences are expected, so the tolerance is wide.
SELECT 'sales_usd' AS check_name, pnl_id, sold_to, material_group,
       sales_usd, tot_net_sales, forex_rate,
       sales_usd - tot_net_sales * forex_rate AS diff
FROM   sales.pnl_fact
WHERE  forex_rate IS NOT NULL
  AND  abs(sales_usd - tot_net_sales * forex_rate) > 1.0;

-- SQL Server 판. Postgres 판(sql/postgres/01_pnl_fact.sql)과 컬럼 구성은 동일하다.
-- 주의: SQL Server 의 UNIQUE INDEX 는 NULL 끼리도 같은 값으로 보므로,
--       자연키에 NULL 이 들어오는 소스라면 인덱스를 빼거나 필터 인덱스로 바꿀 것.

IF SCHEMA_ID('sales') IS NULL EXEC('CREATE SCHEMA sales');
GO

IF OBJECT_ID('sales.pnl_fact','U') IS NOT NULL DROP TABLE sales.pnl_fact;
GO

CREATE TABLE sales.pnl_fact (
    pnl_id           bigint IDENTITY(1,1) NOT NULL PRIMARY KEY,

    -- ══ 헤더/집계 키 (엑셀 좌측 블록) ════════
    cus_group                         varchar(20),            -- Cus_group
    account                           varchar(20),            -- Account
    site                              varchar(20),            -- Site
    record_type                       varchar(10),            -- Type
    report_currency                   varchar(10),            -- Currency
    division2                         varchar(20),            -- Division 2
    division                          varchar(20),            -- Division
    fiscal_year                       smallint NOT NULL,      -- Year
    version                           varchar(20) NOT NULL,   -- Ver
    sold_to                           varchar(20),            -- sold To
    forex_rate                        decimal(18,9),          -- Forex
    sales_usd                         decimal(18,2),          -- Sales U$
    op_profit_usd                     decimal(18,2),          -- Op Profit U$
    flag                              varchar(10),            -- Flag
    month_nm                          varchar(10),            -- Month
    pp1                               varchar(20),            -- PP1

    -- ══ SAP 원장 차원 (Dimension) ════════
    customer                          varchar(20),            -- Customer
    material_group                    varchar(20),            -- Material Group
    nielsen_id                        varchar(20),            -- Nielsen ID
    profit_center                     varchar(20),            -- Profit Center
    sap_division                      varchar(10),            -- Division
    distribution_channel              varchar(10),            -- Distribution Channel
    period                            varchar(10) NOT NULL,   -- Period
    doc_currency                      varchar(10),            -- Currency

    -- ══ 수량 (Quantity) ════════
    qty_gross                         decimal(18,3),          -- Quantity(Gross)
    qty_return                        decimal(18,3),          -- Quantity(Return)
    qty_net                           decimal(18,3),          -- Quantity(Net)

    -- ══ 매출 (Sales) ════════
    tot_s_rrp                         decimal(18,2),          -- *S.RRP
    reference_price                   decimal(18,2),          -- Reference Price
    tot_dealer_discount               decimal(18,2),          -- *Delear Discount
    s_base_margin                     decimal(18,2),          -- S.Base Margin
    s_contract_margin                 decimal(18,2),          -- S.Contract Margin
    s_additional_margin               decimal(18,2),          -- S.Additional Margin
    s_special_margin                  decimal(18,2),          -- S.Special Margin
    tot_s_gross_sales                 decimal(18,2),          -- *S.Gross Sales
    s_gross_sales_amt                 decimal(18,2),          -- S.Gross Sales AMT
    s_other_sales                     decimal(18,2),          -- S.Other Sales
    s_oth_sales_tax_inc               decimal(18,2),          -- S.Oth Sales Tax Inc
    s_internal_sales_amt              decimal(18,2),          -- S.Internal Sales Amt
    tot_s_return_amt                  decimal(18,2),          -- *S.Return Amt
    s_return_amt                      decimal(18,2),          -- S.Return Amt
    tot_ref_sales                     decimal(18,2),          -- *Ref. Sales
    s_ifc                             decimal(18,2),          -- S.IFC
    s_fob_sales_amt                   decimal(18,2),          -- S.FOB Sales Amt
    tot_sales_deduction               decimal(18,2),          -- *Sales Deduction
    s_sales_allowance                 decimal(18,2),          -- S.Sales Allowance
    s_rebate                          decimal(18,2),          -- S.Rebate
    s_cash_discount                   decimal(18,2),          -- S.Cash Discount
    s_price_protection                decimal(18,2),          -- S.Price Protection
    s_co_op                           decimal(18,2),          -- S.CO-OP
    s_sale_deduction_tax              decimal(18,2),          -- S.Sale Deduction TAX
    tot_net_sales                     decimal(18,2),          -- *Net Sales

    -- ══ 매출원가 (Cost of Goods Sold) ════════
    tot_cogs                          decimal(18,2),          -- *Cost of Goods Sold
    tot_material_cost                 decimal(18,2),          -- *Material Cost
    sc_material_cost                  decimal(18,2),          -- SC.Material Cost
    sc_matl_cost_loss                 decimal(18,2),          -- SC.Matl Cost-Loss
    sc_cctr_matl_cost                 decimal(18,2),          -- SC.Cctr Matl Cost
    sc_cctr_matl_loss                 decimal(18,2),          -- SC.Cctr Matl-Loss
    sc_os_material_cost               decimal(18,2),          -- SC.OS Material Cost
    sc_other_matl_cost                decimal(18,2),          -- SC.Other Matl Cost
    tot_labor_cost                    decimal(18,2),          -- *Labor Cost
    sc_labor_cost                     decimal(18,2),          -- SC.Labor Cost
    sc_labor_salaries                 decimal(18,2),          -- SC.Labor-Salaries
    sc_labor_overtime                 decimal(18,2),          -- SC.Labor-Overtime
    sc_labor_cost_ps                  decimal(18,2),          -- SC.Labor Cost(PS)
    sc_labor_cost_rd                  decimal(18,2),          -- SC.Labor Cost(RD)
    tot_depreciation_exp              decimal(18,2),          -- *Depreciation Exp
    sc_depre_exp                      decimal(18,2),          -- SC.Depre Exp
    sc_depre_exp_on_bldg              decimal(18,2),          -- SC.Depre Exp on Bldg
    sc_depre_exp_on_m_and_e           decimal(18,2),          -- SC.Depre Exp on M&E
    tot_mold_exp                      decimal(18,2),          -- *Mold Exp
    sc_depre_exp_on_mold              decimal(18,2),          -- SC.Depre Exp on Mold
    sc_molds_cost                     decimal(18,2),          -- SC.Molds Cost
    sc_cnc_molds_cost                 decimal(18,2),          -- SC.CNC Molds Cost
    tot_manufac_supp_cost             decimal(18,2),          -- *Manufac.supp.Cost
    sc_mfg_supply_cost                decimal(18,2),          -- SC.Mfg Supply Cost
    sc_mfg_repair_and_maint           decimal(18,2),          -- SC.Mfg Repair&Maint
    sc_manufac_jig_cost               decimal(18,2),          -- SC.Manufac.JIG.Cost
    sc_equip_repair_cost              decimal(18,2),          -- SC.Equip Repair Cost
    sc_supplies_exp                   decimal(18,2),          -- SC.Supplies Exp
    tot_expense                       decimal(18,2),          -- *Expense
    sc_amort_on_dev_cost              decimal(18,2),          -- SC.Amort on Dev Cost
    sc_subcont_cost                   decimal(18,2),          -- SC.Subcont. Cost
    sc_part_time_svc_exp              decimal(18,2),          -- SC.Part Time SVC Exp
    sc_royalty_3rd_party              decimal(18,2),          -- SC.Royalty-3rd Party
    sc_royalty_hq                     decimal(18,2),          -- SC.Royalty-HQ
    sc_utility                        decimal(18,2),          -- SC.Utility
    sc_logistic_cost                  decimal(18,2),          -- SC.Logistic Cost
    sc_commission                     decimal(18,2),          -- SC.Commission
    sc_it_cost                        decimal(18,2),          -- SC.IT Cost
    sc_installation                   decimal(18,2),          -- SC.Installation
    sc_tax_and_dues                   decimal(18,2),          -- SC.Tax&Dues
    sc_telecom_exp                    decimal(18,2),          -- SC.Telecom Exp
    sc_travel_exp                     decimal(18,2),          -- SC.Travel Exp
    sc_rent_and_lease_exp             decimal(18,2),          -- SC.Rent&Lease Exp
    sc_sample_exp                     decimal(18,2),          -- SC.Sample Exp
    sc_packing_exp                    decimal(18,2),          -- SC.Packing Exp
    sc_insurance_premium              decimal(18,2),          -- SC.Insurance Premium
    sc_convention_exp                 decimal(18,2),          -- SC.Convention Exp
    sc_svc_exp                        decimal(18,2),          -- SC.SVC Exp
    sc_other_exps                     decimal(18,2),          -- SC.Other Exps
    sc_consumable_rd                  decimal(18,2),          -- SC.Consumable(RD)
    sc_ordinary_exp_matl              decimal(18,2),          -- SC.Ordinary Exp-Matl
    sc_outsourcing_svc                decimal(18,2),          -- SC.Outsourcing SVC
    sc_others_rd                      decimal(18,2),          -- SC.Othres(RD)
    tot_other_cgs                     decimal(18,2),          -- *Other CGS
    sc_other                          decimal(18,2),          -- SC.Other
    sc_svc_warranty                   decimal(18,2),          -- SC.SVC Warranty
    sc_svc_agent_fee                  decimal(18,2),          -- SC.SVC Agent Fee
    tot_return_cgs                    decimal(18,2),          -- *Return CGS
    sc_return_cgs                     decimal(18,2),          -- SC.Return CGS
    tot_other_expense                 decimal(18,2),          -- *Other Expense
    tot_other_exp_detail              decimal(18,2),          -- *Other Exp.
    sc_lcm                            decimal(18,2),          -- SC.LCM
    sc_e_and_o                        decimal(18,2),          -- SC.E&O
    sc_ramp_up_cost                   decimal(18,2),          -- SC.Ramp-up Cost
    sc_inv_loss_q                     decimal(18,2),          -- SC.INV Loss(Q)
    sc_inv_loss_p                     decimal(18,2),          -- SC.INV Loss(P)
    sc_subcontractor_adj              decimal(18,2),          -- SC.Subcontractor-Adj
    sc_customs_refund                 decimal(18,2),          -- SC.Customs Refund
    sc_matl_price_settle              decimal(18,2),          -- SC.Matl Price Settle
    sc_vat_china                      decimal(18,2),          -- SC.VAT (China)
    sc_cgs_others                     decimal(18,2),          -- SC.CGS Others
    tot_logistic_cost_c_type          decimal(18,2),          -- *Logistic Cost(C Type)
    sc_transport_inland               decimal(18,2),          -- SC.Transport-Inland
    sc_transport_marine               decimal(18,2),          -- SC.Transport-Marine
    sc_transport_air                  decimal(18,2),          -- SC.Transport-Air
    sc_transport_other                decimal(18,2),          -- SC.Transport-Other
    sc_insurance_logis                decimal(18,2),          -- SC.Insurance (Logis)
    tot_internal_cgs                  decimal(18,2),          -- *Internal CGS
    sc_internal_cgs                   decimal(18,2),          -- SC.Internal CGS
    tot_ref_cogs                      decimal(18,2),          -- *Ref. CoGS
    sc_stat_customs_fee               decimal(18,2),          -- SC.Stat.Customs Fee
    sc_stat_incidental                decimal(18,2),          -- SC.Stat Incidental
    sc_stat_sub_line_exp              decimal(18,2),          -- SC.Stat.Sub-Line Exp

    -- ══ 매출총이익 / 판관비 (Gross Margin & Operating Expense) ════════
    tot_gross_margin                  decimal(18,2),          -- *Gross Margin
    tot_operating_expense             decimal(18,2),          -- *Operating Expense
    tot_sales_expense                 decimal(18,2),          -- *Sales Expense
    tot_labor_cost_s                  decimal(18,2),          -- *Labor Cost(S)
    sa_labor_cost                     decimal(18,2),          -- SA.Labor Cost
    sa_labor_salaries                 decimal(18,2),          -- SA.Labor-Salaries
    tot_svc_expense                   decimal(18,2),          -- *SVC Expense
    sa_svc_warranty                   decimal(18,2),          -- SA.SVC Warranty
    sa_svc_qual_support               decimal(18,2),          -- SA.SVC Qual Support
    sa_svc_agency_fee                 decimal(18,2),          -- SA.SVC Agency Fee
    sa_svc_call_center                decimal(18,2),          -- SA.SVC Call Center
    sa_svc_claim                      decimal(18,2),          -- SA.SVC Claim
    sa_svc_freight                    decimal(18,2),          -- SA.SVC Freight
    sa_svc_circulation                decimal(18,2),          -- SA.SVC Circulation
    sa_svc_op_support                 decimal(18,2),          -- SA.SVC Op Support
    sa_svc_other_exp                  decimal(18,2),          -- SA.SVC Other Exp
    tot_logistics_cost                decimal(18,2),          -- *Logistics Cost
    sa_transport_inland               decimal(18,2),          -- SA.Transport-Inland
    sa_transport_marine               decimal(18,2),          -- SA.Transport-Marine
    sa_transport_air                  decimal(18,2),          -- SA.Transport-Air
    sa_transport_other                decimal(18,2),          -- SA.Transport-Other
    sa_warehouse_fee                  decimal(18,2),          -- SA.Warehouse Fee
    sa_insurance_logis                decimal(18,2),          -- SA.Insurance (Logis)
    sa_comm                           decimal(18,2),          -- SA.Comm
    tot_marketing_expense             decimal(18,2),          -- *Marketing Expense
    sa_advertising                    decimal(18,2),          -- SA.Advertising
    sa_co_op                          decimal(18,2),          -- SA.CO-OP
    sa_promotion                      decimal(18,2),          -- SA.Promotion
    sa_market_research                decimal(18,2),          -- SA.Market Research
    sa_sales_commission               decimal(18,2),          -- SA.Sales Commission
    sa_comm_and_svcchgc_card          decimal(18,2),          -- SA.Comm&SvcChgC.Card
    sa_hq_sales_comm                  decimal(18,2),          -- SA.HQ Sales Comm
    sa_corp_promotion                 decimal(18,2),          -- SA.Corp. Promotion
    tot_royalty                       decimal(18,2),          -- *Royalty
    sa_royalty_3rd_party              decimal(18,2),          -- SA.Royalty-3rd Party
    sa_royalty_hq                     decimal(18,2),          -- SA.Royalty-HQ
    sa_royalty_lump_sum               decimal(18,2),          -- SA.Royalty-Lump Sum
    tot_paid_commission               decimal(18,2),          -- *Paid Commission
    sa_comm_consult                   decimal(18,2),          -- SA.Comm-Consult
    sa_comm_litigation                decimal(18,2),          -- SA.Comm-Litigation
    sa_comm_audit                     decimal(18,2),          -- SA.Comm-Audit
    sa_comm_d_o                       decimal(18,2),          -- SA.Comm-D/O
    sa_paid_comm                      decimal(18,2),          -- SA.Paid Comm
    tot_other_expense_s               decimal(18,2),          -- *Other Expense(S)
    sa_depreciation                   decimal(18,2),          -- SA.Depreciation
    sa_insurance_premium              decimal(18,2),          -- SA.Insurance Premium
    sa_sample                         decimal(18,2),          -- SA.Sample
    sa_it_exp                         decimal(18,2),          -- SA.IT Exp
    sa_lease_and_rent                 decimal(18,2),          -- SA.Lease&Rent
    sa_bad_debt_exp                   decimal(18,2),          -- SA.Bad Debt Exp
    sa_travel_exp                     decimal(18,2),          -- SA.Travel Exp
    sa_telecom_exp                    decimal(18,2),          -- SA.Telecom Exp
    sa_event_exp                      decimal(18,2),          -- SA.Event Exp
    sa_survey_exp                     decimal(18,2),          -- SA.Survey Exp
    sa_social_exp                     decimal(18,2),          -- SA.Social Exp
    sa_convention_exp                 decimal(18,2),          -- SA.Convention Exp
    sa_copyright                      decimal(18,2),          -- SA.Copyright
    sa_weee                           decimal(18,2),          -- SA.WEEE
    sa_familynet                      decimal(18,2),          -- SA.Familynet
    sa_other_exp                      decimal(18,2),          -- SA.Other Exp

    -- ══ 연구개발비 (R&D Expense) ════════
    tot_r_and_d_expense               decimal(18,2),          -- *R&D Expense
    tot_internal_expense              decimal(18,2),          -- *Internal Expense
    rd_ordinary_exp_matl              decimal(18,2),          -- RD.Ordinary Exp-Matl
    rd_labor                          decimal(18,2),          -- RD Labor
    rd_depreciation                   decimal(18,2),          -- RD.Depreciation
    rd_consumable                     decimal(18,2),          -- RD.Consumable
    rd_others                         decimal(18,2),          -- RD.Others
    rd_er                             decimal(18,2),          -- RD.ER
    rd_mask                           decimal(18,2),          -- RD.Mask
    tot_external_expense              decimal(18,2),          -- *External Expense
    rd_royalty                        decimal(18,2),          -- RD.Royalty
    rd_outsourcing_svc                decimal(18,2),          -- RD.Outsourcing SVC

    -- ══ 일반관리비 (G&A Expense) ════════
    tot_g_and_a_expense               decimal(18,2),          -- *G&A Expense
    tot_labor_cost_sa                 decimal(18,2),          -- *Labor Cost(SA)
    ga_labor_cost                     decimal(18,2),          -- GA.Labor Cost
    ga_labor_salaries                 decimal(18,2),          -- GA.Labor-Salaries
    tot_paid_commission_sa            decimal(18,2),          -- *Paid Commission(SA)
    ga_comm_consult                   decimal(18,2),          -- GA.Comm-Consult
    ga_comm_litigation                decimal(18,2),          -- GA.Comm-Litigation
    ga_comm_audit                     decimal(18,2),          -- GA.Comm-Audit
    ga_comm_d_o                       decimal(18,2),          -- GA.Comm-D/O
    ga_comm                           decimal(18,2),          -- GA.Comm
    tot_expense_s                     decimal(18,2),          -- *Expense(S)
    ga_depreciation                   decimal(18,2),          -- GA.Depreciation
    ga_it_exp                         decimal(18,2),          -- GA.IT Exp
    ga_rent_exp                       decimal(18,2),          -- GA.Rent Exp
    ga_telecom_exp                    decimal(18,2),          -- GA.Telecom Exp
    ga_repairs_and_maint_exp          decimal(18,2),          -- GA.Repairs&Maint Exp
    ga_travel_exp                     decimal(18,2),          -- GA.Travel Exp
    ga_insurance_premium              decimal(18,2),          -- GA.Insurance Premium
    ga_convention_exp                 decimal(18,2),          -- GA.Convention Exp
    ga_other                          decimal(18,2),          -- GA.Other

    -- ══ 영업이익 이하 (Operating Profit & below) ════════
    tot_operating_profit              decimal(18,2),          -- *Operating Profit
    tot_non_op_income_and_expense     decimal(18,2),          -- *Non-Op. Incom. & Ex
    tot_non_op_income                 decimal(18,2),          -- *Non-Op. Income
    op_commission_3rd                 decimal(18,2),          -- OP.Commission 3rd
    op_service_claim                  decimal(18,2),          -- OP.Service Claim
    op_rental_income                  decimal(18,2),          -- OP.Rental Income
    op_extra_gain                     decimal(18,2),          -- OP.Extra Gain
    op_others                         decimal(18,2),          -- OP.Others
    tot_non_op_expense                decimal(18,2),          -- *Non-Op. Expense
    oe_loss_on_a_r_sale               decimal(18,2),          -- OE.Loss on A/R Sale
    oe_extra_loss                     decimal(18,2),          -- OE.Extra Loss
    oe_others                         decimal(18,2),          -- OE.Others
    tot_gain_loss_on_equity           decimal(18,2),          -- *Gain/Loss on Equity
    tot_gain_on_equity                decimal(18,2),          -- *Gain on Equity
    eg_gain_on_equity                 decimal(18,2),          -- EG.Gain on Equity
    tot_loss_on_equity                decimal(18,2),          -- *Loss on Equity
    el_loss_on_equity                 decimal(18,2),          -- EL.Loss on Equity
    tot_financial_income_and_expense  decimal(18,2),          -- *Financial  Incom. & Exp.
    tot_finance_profit                decimal(18,2),          -- *Finance Profit
    fp_gain_on_fx                     decimal(18,2),          -- FP.Gain on FX
    fp_interest_income                decimal(18,2),          -- FP.Interest Income
    fp_fin_profit_oths                decimal(18,2),          -- FP.Fin Profit-Oths
    tot_finance_loss                  decimal(18,2),          -- *Finance Loss
    fe_fo_ex_loss                     decimal(18,2),          -- FE.Fo.Ex.Loss
    fe_interest_exp_ext               decimal(18,2),          -- FE.Interest Exp-Ext
    fe_interest_exp_int               decimal(18,2),          -- FE.Interest Exp-Int
    fe_financial_exp_oth              decimal(18,2),          -- FE.Financial Exp-Oth
    tot_profit_before_tax             decimal(18,2),          -- *Profit Before Tax
    tot_corporate_tax                 decimal(18,2),          -- *Corporate Tax
    corp_tax                          decimal(18,2),          -- Corp. Tax
    tot_net_income                    decimal(18,2),          -- *Net Income

    -- ══ 적재 메타데이터 ════════
    source_file                       varchar(260),
    loaded_at                         datetime2(3) NOT NULL CONSTRAINT df_pnl_loaded_at DEFAULT sysutcdatetime()
);
GO

CREATE UNIQUE INDEX ux_pnl_fact_natural ON sales.pnl_fact (
    fiscal_year, version, period, sold_to, material_group,
    profit_center, sap_division, distribution_channel, doc_currency
);
CREATE INDEX ix_pnl_fact_period   ON sales.pnl_fact (fiscal_year, period);
CREATE INDEX ix_pnl_fact_customer ON sales.pnl_fact (sold_to, fiscal_year, period);
CREATE INDEX ix_pnl_fact_matgrp   ON sales.pnl_fact (material_group, fiscal_year, period);
GO


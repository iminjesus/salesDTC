-- 고객 x 제품군 단위 손익(P&L) 플랫 테이블 — 엑셀 원본 258 컬럼 그대로.
-- tot_* 는 원본에서 * 가 붙은 소계 라인이다 (하위 계정의 합계이므로 중복 집계 주의).

CREATE SCHEMA IF NOT EXISTS sales;

DROP TABLE IF EXISTS sales.pnl_fact CASCADE;

CREATE TABLE sales.pnl_fact (
    pnl_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

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
    forex_rate                        numeric(18,9),          -- Forex
    sales_usd                         numeric(18,2),          -- Sales U$
    op_profit_usd                     numeric(18,2),          -- Op Profit U$
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
    qty_gross                         numeric(18,3),          -- Quantity(Gross)
    qty_return                        numeric(18,3),          -- Quantity(Return)
    qty_net                           numeric(18,3),          -- Quantity(Net)

    -- ══ 매출 (Sales) ════════
    tot_s_rrp                         numeric(18,2),          -- *S.RRP
    reference_price                   numeric(18,2),          -- Reference Price
    tot_dealer_discount               numeric(18,2),          -- *Delear Discount
    s_base_margin                     numeric(18,2),          -- S.Base Margin
    s_contract_margin                 numeric(18,2),          -- S.Contract Margin
    s_additional_margin               numeric(18,2),          -- S.Additional Margin
    s_special_margin                  numeric(18,2),          -- S.Special Margin
    tot_s_gross_sales                 numeric(18,2),          -- *S.Gross Sales
    s_gross_sales_amt                 numeric(18,2),          -- S.Gross Sales AMT
    s_other_sales                     numeric(18,2),          -- S.Other Sales
    s_oth_sales_tax_inc               numeric(18,2),          -- S.Oth Sales Tax Inc
    s_internal_sales_amt              numeric(18,2),          -- S.Internal Sales Amt
    tot_s_return_amt                  numeric(18,2),          -- *S.Return Amt
    s_return_amt                      numeric(18,2),          -- S.Return Amt
    tot_ref_sales                     numeric(18,2),          -- *Ref. Sales
    s_ifc                             numeric(18,2),          -- S.IFC
    s_fob_sales_amt                   numeric(18,2),          -- S.FOB Sales Amt
    tot_sales_deduction               numeric(18,2),          -- *Sales Deduction
    s_sales_allowance                 numeric(18,2),          -- S.Sales Allowance
    s_rebate                          numeric(18,2),          -- S.Rebate
    s_cash_discount                   numeric(18,2),          -- S.Cash Discount
    s_price_protection                numeric(18,2),          -- S.Price Protection
    s_co_op                           numeric(18,2),          -- S.CO-OP
    s_sale_deduction_tax              numeric(18,2),          -- S.Sale Deduction TAX
    tot_net_sales                     numeric(18,2),          -- *Net Sales

    -- ══ 매출원가 (Cost of Goods Sold) ════════
    tot_cogs                          numeric(18,2),          -- *Cost of Goods Sold
    tot_material_cost                 numeric(18,2),          -- *Material Cost
    sc_material_cost                  numeric(18,2),          -- SC.Material Cost
    sc_matl_cost_loss                 numeric(18,2),          -- SC.Matl Cost-Loss
    sc_cctr_matl_cost                 numeric(18,2),          -- SC.Cctr Matl Cost
    sc_cctr_matl_loss                 numeric(18,2),          -- SC.Cctr Matl-Loss
    sc_os_material_cost               numeric(18,2),          -- SC.OS Material Cost
    sc_other_matl_cost                numeric(18,2),          -- SC.Other Matl Cost
    tot_labor_cost                    numeric(18,2),          -- *Labor Cost
    sc_labor_cost                     numeric(18,2),          -- SC.Labor Cost
    sc_labor_salaries                 numeric(18,2),          -- SC.Labor-Salaries
    sc_labor_overtime                 numeric(18,2),          -- SC.Labor-Overtime
    sc_labor_cost_ps                  numeric(18,2),          -- SC.Labor Cost(PS)
    sc_labor_cost_rd                  numeric(18,2),          -- SC.Labor Cost(RD)
    tot_depreciation_exp              numeric(18,2),          -- *Depreciation Exp
    sc_depre_exp                      numeric(18,2),          -- SC.Depre Exp
    sc_depre_exp_on_bldg              numeric(18,2),          -- SC.Depre Exp on Bldg
    sc_depre_exp_on_m_and_e           numeric(18,2),          -- SC.Depre Exp on M&E
    tot_mold_exp                      numeric(18,2),          -- *Mold Exp
    sc_depre_exp_on_mold              numeric(18,2),          -- SC.Depre Exp on Mold
    sc_molds_cost                     numeric(18,2),          -- SC.Molds Cost
    sc_cnc_molds_cost                 numeric(18,2),          -- SC.CNC Molds Cost
    tot_manufac_supp_cost             numeric(18,2),          -- *Manufac.supp.Cost
    sc_mfg_supply_cost                numeric(18,2),          -- SC.Mfg Supply Cost
    sc_mfg_repair_and_maint           numeric(18,2),          -- SC.Mfg Repair&Maint
    sc_manufac_jig_cost               numeric(18,2),          -- SC.Manufac.JIG.Cost
    sc_equip_repair_cost              numeric(18,2),          -- SC.Equip Repair Cost
    sc_supplies_exp                   numeric(18,2),          -- SC.Supplies Exp
    tot_expense                       numeric(18,2),          -- *Expense
    sc_amort_on_dev_cost              numeric(18,2),          -- SC.Amort on Dev Cost
    sc_subcont_cost                   numeric(18,2),          -- SC.Subcont. Cost
    sc_part_time_svc_exp              numeric(18,2),          -- SC.Part Time SVC Exp
    sc_royalty_3rd_party              numeric(18,2),          -- SC.Royalty-3rd Party
    sc_royalty_hq                     numeric(18,2),          -- SC.Royalty-HQ
    sc_utility                        numeric(18,2),          -- SC.Utility
    sc_logistic_cost                  numeric(18,2),          -- SC.Logistic Cost
    sc_commission                     numeric(18,2),          -- SC.Commission
    sc_it_cost                        numeric(18,2),          -- SC.IT Cost
    sc_installation                   numeric(18,2),          -- SC.Installation
    sc_tax_and_dues                   numeric(18,2),          -- SC.Tax&Dues
    sc_telecom_exp                    numeric(18,2),          -- SC.Telecom Exp
    sc_travel_exp                     numeric(18,2),          -- SC.Travel Exp
    sc_rent_and_lease_exp             numeric(18,2),          -- SC.Rent&Lease Exp
    sc_sample_exp                     numeric(18,2),          -- SC.Sample Exp
    sc_packing_exp                    numeric(18,2),          -- SC.Packing Exp
    sc_insurance_premium              numeric(18,2),          -- SC.Insurance Premium
    sc_convention_exp                 numeric(18,2),          -- SC.Convention Exp
    sc_svc_exp                        numeric(18,2),          -- SC.SVC Exp
    sc_other_exps                     numeric(18,2),          -- SC.Other Exps
    sc_consumable_rd                  numeric(18,2),          -- SC.Consumable(RD)
    sc_ordinary_exp_matl              numeric(18,2),          -- SC.Ordinary Exp-Matl
    sc_outsourcing_svc                numeric(18,2),          -- SC.Outsourcing SVC
    sc_others_rd                      numeric(18,2),          -- SC.Othres(RD)
    tot_other_cgs                     numeric(18,2),          -- *Other CGS
    sc_other                          numeric(18,2),          -- SC.Other
    sc_svc_warranty                   numeric(18,2),          -- SC.SVC Warranty
    sc_svc_agent_fee                  numeric(18,2),          -- SC.SVC Agent Fee
    tot_return_cgs                    numeric(18,2),          -- *Return CGS
    sc_return_cgs                     numeric(18,2),          -- SC.Return CGS
    tot_other_expense                 numeric(18,2),          -- *Other Expense
    tot_other_exp_detail              numeric(18,2),          -- *Other Exp.
    sc_lcm                            numeric(18,2),          -- SC.LCM
    sc_e_and_o                        numeric(18,2),          -- SC.E&O
    sc_ramp_up_cost                   numeric(18,2),          -- SC.Ramp-up Cost
    sc_inv_loss_q                     numeric(18,2),          -- SC.INV Loss(Q)
    sc_inv_loss_p                     numeric(18,2),          -- SC.INV Loss(P)
    sc_subcontractor_adj              numeric(18,2),          -- SC.Subcontractor-Adj
    sc_customs_refund                 numeric(18,2),          -- SC.Customs Refund
    sc_matl_price_settle              numeric(18,2),          -- SC.Matl Price Settle
    sc_vat_china                      numeric(18,2),          -- SC.VAT (China)
    sc_cgs_others                     numeric(18,2),          -- SC.CGS Others
    tot_logistic_cost_c_type          numeric(18,2),          -- *Logistic Cost(C Type)
    sc_transport_inland               numeric(18,2),          -- SC.Transport-Inland
    sc_transport_marine               numeric(18,2),          -- SC.Transport-Marine
    sc_transport_air                  numeric(18,2),          -- SC.Transport-Air
    sc_transport_other                numeric(18,2),          -- SC.Transport-Other
    sc_insurance_logis                numeric(18,2),          -- SC.Insurance (Logis)
    tot_internal_cgs                  numeric(18,2),          -- *Internal CGS
    sc_internal_cgs                   numeric(18,2),          -- SC.Internal CGS
    tot_ref_cogs                      numeric(18,2),          -- *Ref. CoGS
    sc_stat_customs_fee               numeric(18,2),          -- SC.Stat.Customs Fee
    sc_stat_incidental                numeric(18,2),          -- SC.Stat Incidental
    sc_stat_sub_line_exp              numeric(18,2),          -- SC.Stat.Sub-Line Exp

    -- ══ 매출총이익 / 판관비 (Gross Margin & Operating Expense) ════════
    tot_gross_margin                  numeric(18,2),          -- *Gross Margin
    tot_operating_expense             numeric(18,2),          -- *Operating Expense
    tot_sales_expense                 numeric(18,2),          -- *Sales Expense
    tot_labor_cost_s                  numeric(18,2),          -- *Labor Cost(S)
    sa_labor_cost                     numeric(18,2),          -- SA.Labor Cost
    sa_labor_salaries                 numeric(18,2),          -- SA.Labor-Salaries
    tot_svc_expense                   numeric(18,2),          -- *SVC Expense
    sa_svc_warranty                   numeric(18,2),          -- SA.SVC Warranty
    sa_svc_qual_support               numeric(18,2),          -- SA.SVC Qual Support
    sa_svc_agency_fee                 numeric(18,2),          -- SA.SVC Agency Fee
    sa_svc_call_center                numeric(18,2),          -- SA.SVC Call Center
    sa_svc_claim                      numeric(18,2),          -- SA.SVC Claim
    sa_svc_freight                    numeric(18,2),          -- SA.SVC Freight
    sa_svc_circulation                numeric(18,2),          -- SA.SVC Circulation
    sa_svc_op_support                 numeric(18,2),          -- SA.SVC Op Support
    sa_svc_other_exp                  numeric(18,2),          -- SA.SVC Other Exp
    tot_logistics_cost                numeric(18,2),          -- *Logistics Cost
    sa_transport_inland               numeric(18,2),          -- SA.Transport-Inland
    sa_transport_marine               numeric(18,2),          -- SA.Transport-Marine
    sa_transport_air                  numeric(18,2),          -- SA.Transport-Air
    sa_transport_other                numeric(18,2),          -- SA.Transport-Other
    sa_warehouse_fee                  numeric(18,2),          -- SA.Warehouse Fee
    sa_insurance_logis                numeric(18,2),          -- SA.Insurance (Logis)
    sa_comm                           numeric(18,2),          -- SA.Comm
    tot_marketing_expense             numeric(18,2),          -- *Marketing Expense
    sa_advertising                    numeric(18,2),          -- SA.Advertising
    sa_co_op                          numeric(18,2),          -- SA.CO-OP
    sa_promotion                      numeric(18,2),          -- SA.Promotion
    sa_market_research                numeric(18,2),          -- SA.Market Research
    sa_sales_commission               numeric(18,2),          -- SA.Sales Commission
    sa_comm_and_svcchgc_card          numeric(18,2),          -- SA.Comm&SvcChgC.Card
    sa_hq_sales_comm                  numeric(18,2),          -- SA.HQ Sales Comm
    sa_corp_promotion                 numeric(18,2),          -- SA.Corp. Promotion
    tot_royalty                       numeric(18,2),          -- *Royalty
    sa_royalty_3rd_party              numeric(18,2),          -- SA.Royalty-3rd Party
    sa_royalty_hq                     numeric(18,2),          -- SA.Royalty-HQ
    sa_royalty_lump_sum               numeric(18,2),          -- SA.Royalty-Lump Sum
    tot_paid_commission               numeric(18,2),          -- *Paid Commission
    sa_comm_consult                   numeric(18,2),          -- SA.Comm-Consult
    sa_comm_litigation                numeric(18,2),          -- SA.Comm-Litigation
    sa_comm_audit                     numeric(18,2),          -- SA.Comm-Audit
    sa_comm_d_o                       numeric(18,2),          -- SA.Comm-D/O
    sa_paid_comm                      numeric(18,2),          -- SA.Paid Comm
    tot_other_expense_s               numeric(18,2),          -- *Other Expense(S)
    sa_depreciation                   numeric(18,2),          -- SA.Depreciation
    sa_insurance_premium              numeric(18,2),          -- SA.Insurance Premium
    sa_sample                         numeric(18,2),          -- SA.Sample
    sa_it_exp                         numeric(18,2),          -- SA.IT Exp
    sa_lease_and_rent                 numeric(18,2),          -- SA.Lease&Rent
    sa_bad_debt_exp                   numeric(18,2),          -- SA.Bad Debt Exp
    sa_travel_exp                     numeric(18,2),          -- SA.Travel Exp
    sa_telecom_exp                    numeric(18,2),          -- SA.Telecom Exp
    sa_event_exp                      numeric(18,2),          -- SA.Event Exp
    sa_survey_exp                     numeric(18,2),          -- SA.Survey Exp
    sa_social_exp                     numeric(18,2),          -- SA.Social Exp
    sa_convention_exp                 numeric(18,2),          -- SA.Convention Exp
    sa_copyright                      numeric(18,2),          -- SA.Copyright
    sa_weee                           numeric(18,2),          -- SA.WEEE
    sa_familynet                      numeric(18,2),          -- SA.Familynet
    sa_other_exp                      numeric(18,2),          -- SA.Other Exp

    -- ══ 연구개발비 (R&D Expense) ════════
    tot_r_and_d_expense               numeric(18,2),          -- *R&D Expense
    tot_internal_expense              numeric(18,2),          -- *Internal Expense
    rd_ordinary_exp_matl              numeric(18,2),          -- RD.Ordinary Exp-Matl
    rd_labor                          numeric(18,2),          -- RD Labor
    rd_depreciation                   numeric(18,2),          -- RD.Depreciation
    rd_consumable                     numeric(18,2),          -- RD.Consumable
    rd_others                         numeric(18,2),          -- RD.Others
    rd_er                             numeric(18,2),          -- RD.ER
    rd_mask                           numeric(18,2),          -- RD.Mask
    tot_external_expense              numeric(18,2),          -- *External Expense
    rd_royalty                        numeric(18,2),          -- RD.Royalty
    rd_outsourcing_svc                numeric(18,2),          -- RD.Outsourcing SVC

    -- ══ 일반관리비 (G&A Expense) ════════
    tot_g_and_a_expense               numeric(18,2),          -- *G&A Expense
    tot_labor_cost_sa                 numeric(18,2),          -- *Labor Cost(SA)
    ga_labor_cost                     numeric(18,2),          -- GA.Labor Cost
    ga_labor_salaries                 numeric(18,2),          -- GA.Labor-Salaries
    tot_paid_commission_sa            numeric(18,2),          -- *Paid Commission(SA)
    ga_comm_consult                   numeric(18,2),          -- GA.Comm-Consult
    ga_comm_litigation                numeric(18,2),          -- GA.Comm-Litigation
    ga_comm_audit                     numeric(18,2),          -- GA.Comm-Audit
    ga_comm_d_o                       numeric(18,2),          -- GA.Comm-D/O
    ga_comm                           numeric(18,2),          -- GA.Comm
    tot_expense_s                     numeric(18,2),          -- *Expense(S)
    ga_depreciation                   numeric(18,2),          -- GA.Depreciation
    ga_it_exp                         numeric(18,2),          -- GA.IT Exp
    ga_rent_exp                       numeric(18,2),          -- GA.Rent Exp
    ga_telecom_exp                    numeric(18,2),          -- GA.Telecom Exp
    ga_repairs_and_maint_exp          numeric(18,2),          -- GA.Repairs&Maint Exp
    ga_travel_exp                     numeric(18,2),          -- GA.Travel Exp
    ga_insurance_premium              numeric(18,2),          -- GA.Insurance Premium
    ga_convention_exp                 numeric(18,2),          -- GA.Convention Exp
    ga_other                          numeric(18,2),          -- GA.Other

    -- ══ 영업이익 이하 (Operating Profit & below) ════════
    tot_operating_profit              numeric(18,2),          -- *Operating Profit
    tot_non_op_income_and_expense     numeric(18,2),          -- *Non-Op. Incom. & Ex
    tot_non_op_income                 numeric(18,2),          -- *Non-Op. Income
    op_commission_3rd                 numeric(18,2),          -- OP.Commission 3rd
    op_service_claim                  numeric(18,2),          -- OP.Service Claim
    op_rental_income                  numeric(18,2),          -- OP.Rental Income
    op_extra_gain                     numeric(18,2),          -- OP.Extra Gain
    op_others                         numeric(18,2),          -- OP.Others
    tot_non_op_expense                numeric(18,2),          -- *Non-Op. Expense
    oe_loss_on_a_r_sale               numeric(18,2),          -- OE.Loss on A/R Sale
    oe_extra_loss                     numeric(18,2),          -- OE.Extra Loss
    oe_others                         numeric(18,2),          -- OE.Others
    tot_gain_loss_on_equity           numeric(18,2),          -- *Gain/Loss on Equity
    tot_gain_on_equity                numeric(18,2),          -- *Gain on Equity
    eg_gain_on_equity                 numeric(18,2),          -- EG.Gain on Equity
    tot_loss_on_equity                numeric(18,2),          -- *Loss on Equity
    el_loss_on_equity                 numeric(18,2),          -- EL.Loss on Equity
    tot_financial_income_and_expense  numeric(18,2),          -- *Financial  Incom. & Exp.
    tot_finance_profit                numeric(18,2),          -- *Finance Profit
    fp_gain_on_fx                     numeric(18,2),          -- FP.Gain on FX
    fp_interest_income                numeric(18,2),          -- FP.Interest Income
    fp_fin_profit_oths                numeric(18,2),          -- FP.Fin Profit-Oths
    tot_finance_loss                  numeric(18,2),          -- *Finance Loss
    fe_fo_ex_loss                     numeric(18,2),          -- FE.Fo.Ex.Loss
    fe_interest_exp_ext               numeric(18,2),          -- FE.Interest Exp-Ext
    fe_interest_exp_int               numeric(18,2),          -- FE.Interest Exp-Int
    fe_financial_exp_oth              numeric(18,2),          -- FE.Financial Exp-Oth
    tot_profit_before_tax             numeric(18,2),          -- *Profit Before Tax
    tot_corporate_tax                 numeric(18,2),          -- *Corporate Tax
    corp_tax                          numeric(18,2),          -- Corp. Tax
    tot_net_income                    numeric(18,2),          -- *Net Income

    -- ══ 적재 메타데이터 ════════
    source_file                       varchar(260),
    loaded_at                         timestamptz NOT NULL DEFAULT now()
);

-- 자연키: 같은 연도/버전/기간의 같은 고객 x 제품군 x 손익센터 조합은 1행.
-- 재적재 시 중복을 막아준다. 키 컬럼에 NULL 이 섞이는 소스라면 이 인덱스는 빼고
-- 적재 전 DELETE 로 해당 기간을 지우는 방식을 쓸 것.
CREATE UNIQUE INDEX ux_pnl_fact_natural ON sales.pnl_fact (
    fiscal_year, version, period, sold_to, material_group,
    profit_center, sap_division, distribution_channel, doc_currency
);

CREATE INDEX ix_pnl_fact_period   ON sales.pnl_fact (fiscal_year, period);
CREATE INDEX ix_pnl_fact_customer ON sales.pnl_fact (sold_to, fiscal_year, period);
CREATE INDEX ix_pnl_fact_matgrp   ON sales.pnl_fact (material_group, fiscal_year, period);

COMMENT ON TABLE sales.pnl_fact IS '고객/제품군 단위 손익(P&L) 플랫 테이블. tot_* 컬럼은 엑셀 원본의 * 소계 라인.';

COMMENT ON COLUMN sales.pnl_fact.cus_group IS 'Cus_group';
COMMENT ON COLUMN sales.pnl_fact.account IS 'Account';
COMMENT ON COLUMN sales.pnl_fact.site IS 'Site';
COMMENT ON COLUMN sales.pnl_fact.record_type IS 'Type';
COMMENT ON COLUMN sales.pnl_fact.report_currency IS 'Currency';
COMMENT ON COLUMN sales.pnl_fact.division2 IS 'Division 2';
COMMENT ON COLUMN sales.pnl_fact.division IS 'Division';
COMMENT ON COLUMN sales.pnl_fact.fiscal_year IS 'Year';
COMMENT ON COLUMN sales.pnl_fact.version IS 'Ver';
COMMENT ON COLUMN sales.pnl_fact.sold_to IS 'sold To';
COMMENT ON COLUMN sales.pnl_fact.forex_rate IS 'Forex';
COMMENT ON COLUMN sales.pnl_fact.sales_usd IS 'Sales U$';
COMMENT ON COLUMN sales.pnl_fact.op_profit_usd IS 'Op Profit U$';
COMMENT ON COLUMN sales.pnl_fact.flag IS 'Flag';
COMMENT ON COLUMN sales.pnl_fact.month_nm IS 'Month';
COMMENT ON COLUMN sales.pnl_fact.pp1 IS 'PP1';
COMMENT ON COLUMN sales.pnl_fact.customer IS 'Customer';
COMMENT ON COLUMN sales.pnl_fact.material_group IS 'Material Group';
COMMENT ON COLUMN sales.pnl_fact.nielsen_id IS 'Nielsen ID';
COMMENT ON COLUMN sales.pnl_fact.profit_center IS 'Profit Center';
COMMENT ON COLUMN sales.pnl_fact.sap_division IS 'Division';
COMMENT ON COLUMN sales.pnl_fact.distribution_channel IS 'Distribution Channel';
COMMENT ON COLUMN sales.pnl_fact.period IS 'Period';
COMMENT ON COLUMN sales.pnl_fact.doc_currency IS 'Currency';
COMMENT ON COLUMN sales.pnl_fact.qty_gross IS 'Quantity(Gross)';
COMMENT ON COLUMN sales.pnl_fact.qty_return IS 'Quantity(Return)';
COMMENT ON COLUMN sales.pnl_fact.qty_net IS 'Quantity(Net)';
COMMENT ON COLUMN sales.pnl_fact.tot_s_rrp IS '*S.RRP';
COMMENT ON COLUMN sales.pnl_fact.reference_price IS 'Reference Price';
COMMENT ON COLUMN sales.pnl_fact.tot_dealer_discount IS '*Delear Discount';
COMMENT ON COLUMN sales.pnl_fact.s_base_margin IS 'S.Base Margin';
COMMENT ON COLUMN sales.pnl_fact.s_contract_margin IS 'S.Contract Margin';
COMMENT ON COLUMN sales.pnl_fact.s_additional_margin IS 'S.Additional Margin';
COMMENT ON COLUMN sales.pnl_fact.s_special_margin IS 'S.Special Margin';
COMMENT ON COLUMN sales.pnl_fact.tot_s_gross_sales IS '*S.Gross Sales';
COMMENT ON COLUMN sales.pnl_fact.s_gross_sales_amt IS 'S.Gross Sales AMT';
COMMENT ON COLUMN sales.pnl_fact.s_other_sales IS 'S.Other Sales';
COMMENT ON COLUMN sales.pnl_fact.s_oth_sales_tax_inc IS 'S.Oth Sales Tax Inc';
COMMENT ON COLUMN sales.pnl_fact.s_internal_sales_amt IS 'S.Internal Sales Amt';
COMMENT ON COLUMN sales.pnl_fact.tot_s_return_amt IS '*S.Return Amt';
COMMENT ON COLUMN sales.pnl_fact.s_return_amt IS 'S.Return Amt';
COMMENT ON COLUMN sales.pnl_fact.tot_ref_sales IS '*Ref. Sales';
COMMENT ON COLUMN sales.pnl_fact.s_ifc IS 'S.IFC';
COMMENT ON COLUMN sales.pnl_fact.s_fob_sales_amt IS 'S.FOB Sales Amt';
COMMENT ON COLUMN sales.pnl_fact.tot_sales_deduction IS '*Sales Deduction';
COMMENT ON COLUMN sales.pnl_fact.s_sales_allowance IS 'S.Sales Allowance';
COMMENT ON COLUMN sales.pnl_fact.s_rebate IS 'S.Rebate';
COMMENT ON COLUMN sales.pnl_fact.s_cash_discount IS 'S.Cash Discount';
COMMENT ON COLUMN sales.pnl_fact.s_price_protection IS 'S.Price Protection';
COMMENT ON COLUMN sales.pnl_fact.s_co_op IS 'S.CO-OP';
COMMENT ON COLUMN sales.pnl_fact.s_sale_deduction_tax IS 'S.Sale Deduction TAX';
COMMENT ON COLUMN sales.pnl_fact.tot_net_sales IS '*Net Sales';
COMMENT ON COLUMN sales.pnl_fact.tot_cogs IS '*Cost of Goods Sold';
COMMENT ON COLUMN sales.pnl_fact.tot_material_cost IS '*Material Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_material_cost IS 'SC.Material Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_matl_cost_loss IS 'SC.Matl Cost-Loss';
COMMENT ON COLUMN sales.pnl_fact.sc_cctr_matl_cost IS 'SC.Cctr Matl Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_cctr_matl_loss IS 'SC.Cctr Matl-Loss';
COMMENT ON COLUMN sales.pnl_fact.sc_os_material_cost IS 'SC.OS Material Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_other_matl_cost IS 'SC.Other Matl Cost';
COMMENT ON COLUMN sales.pnl_fact.tot_labor_cost IS '*Labor Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_labor_cost IS 'SC.Labor Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_labor_salaries IS 'SC.Labor-Salaries';
COMMENT ON COLUMN sales.pnl_fact.sc_labor_overtime IS 'SC.Labor-Overtime';
COMMENT ON COLUMN sales.pnl_fact.sc_labor_cost_ps IS 'SC.Labor Cost(PS)';
COMMENT ON COLUMN sales.pnl_fact.sc_labor_cost_rd IS 'SC.Labor Cost(RD)';
COMMENT ON COLUMN sales.pnl_fact.tot_depreciation_exp IS '*Depreciation Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_depre_exp IS 'SC.Depre Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_depre_exp_on_bldg IS 'SC.Depre Exp on Bldg';
COMMENT ON COLUMN sales.pnl_fact.sc_depre_exp_on_m_and_e IS 'SC.Depre Exp on M&E';
COMMENT ON COLUMN sales.pnl_fact.tot_mold_exp IS '*Mold Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_depre_exp_on_mold IS 'SC.Depre Exp on Mold';
COMMENT ON COLUMN sales.pnl_fact.sc_molds_cost IS 'SC.Molds Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_cnc_molds_cost IS 'SC.CNC Molds Cost';
COMMENT ON COLUMN sales.pnl_fact.tot_manufac_supp_cost IS '*Manufac.supp.Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_mfg_supply_cost IS 'SC.Mfg Supply Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_mfg_repair_and_maint IS 'SC.Mfg Repair&Maint';
COMMENT ON COLUMN sales.pnl_fact.sc_manufac_jig_cost IS 'SC.Manufac.JIG.Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_equip_repair_cost IS 'SC.Equip Repair Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_supplies_exp IS 'SC.Supplies Exp';
COMMENT ON COLUMN sales.pnl_fact.tot_expense IS '*Expense';
COMMENT ON COLUMN sales.pnl_fact.sc_amort_on_dev_cost IS 'SC.Amort on Dev Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_subcont_cost IS 'SC.Subcont. Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_part_time_svc_exp IS 'SC.Part Time SVC Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_royalty_3rd_party IS 'SC.Royalty-3rd Party';
COMMENT ON COLUMN sales.pnl_fact.sc_royalty_hq IS 'SC.Royalty-HQ';
COMMENT ON COLUMN sales.pnl_fact.sc_utility IS 'SC.Utility';
COMMENT ON COLUMN sales.pnl_fact.sc_logistic_cost IS 'SC.Logistic Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_commission IS 'SC.Commission';
COMMENT ON COLUMN sales.pnl_fact.sc_it_cost IS 'SC.IT Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_installation IS 'SC.Installation';
COMMENT ON COLUMN sales.pnl_fact.sc_tax_and_dues IS 'SC.Tax&Dues';
COMMENT ON COLUMN sales.pnl_fact.sc_telecom_exp IS 'SC.Telecom Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_travel_exp IS 'SC.Travel Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_rent_and_lease_exp IS 'SC.Rent&Lease Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_sample_exp IS 'SC.Sample Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_packing_exp IS 'SC.Packing Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_insurance_premium IS 'SC.Insurance Premium';
COMMENT ON COLUMN sales.pnl_fact.sc_convention_exp IS 'SC.Convention Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_svc_exp IS 'SC.SVC Exp';
COMMENT ON COLUMN sales.pnl_fact.sc_other_exps IS 'SC.Other Exps';
COMMENT ON COLUMN sales.pnl_fact.sc_consumable_rd IS 'SC.Consumable(RD)';
COMMENT ON COLUMN sales.pnl_fact.sc_ordinary_exp_matl IS 'SC.Ordinary Exp-Matl';
COMMENT ON COLUMN sales.pnl_fact.sc_outsourcing_svc IS 'SC.Outsourcing SVC';
COMMENT ON COLUMN sales.pnl_fact.sc_others_rd IS 'SC.Othres(RD)';
COMMENT ON COLUMN sales.pnl_fact.tot_other_cgs IS '*Other CGS';
COMMENT ON COLUMN sales.pnl_fact.sc_other IS 'SC.Other';
COMMENT ON COLUMN sales.pnl_fact.sc_svc_warranty IS 'SC.SVC Warranty';
COMMENT ON COLUMN sales.pnl_fact.sc_svc_agent_fee IS 'SC.SVC Agent Fee';
COMMENT ON COLUMN sales.pnl_fact.tot_return_cgs IS '*Return CGS';
COMMENT ON COLUMN sales.pnl_fact.sc_return_cgs IS 'SC.Return CGS';
COMMENT ON COLUMN sales.pnl_fact.tot_other_expense IS '*Other Expense';
COMMENT ON COLUMN sales.pnl_fact.tot_other_exp_detail IS '*Other Exp.';
COMMENT ON COLUMN sales.pnl_fact.sc_lcm IS 'SC.LCM';
COMMENT ON COLUMN sales.pnl_fact.sc_e_and_o IS 'SC.E&O';
COMMENT ON COLUMN sales.pnl_fact.sc_ramp_up_cost IS 'SC.Ramp-up Cost';
COMMENT ON COLUMN sales.pnl_fact.sc_inv_loss_q IS 'SC.INV Loss(Q)';
COMMENT ON COLUMN sales.pnl_fact.sc_inv_loss_p IS 'SC.INV Loss(P)';
COMMENT ON COLUMN sales.pnl_fact.sc_subcontractor_adj IS 'SC.Subcontractor-Adj';
COMMENT ON COLUMN sales.pnl_fact.sc_customs_refund IS 'SC.Customs Refund';
COMMENT ON COLUMN sales.pnl_fact.sc_matl_price_settle IS 'SC.Matl Price Settle';
COMMENT ON COLUMN sales.pnl_fact.sc_vat_china IS 'SC.VAT (China)';
COMMENT ON COLUMN sales.pnl_fact.sc_cgs_others IS 'SC.CGS Others';
COMMENT ON COLUMN sales.pnl_fact.tot_logistic_cost_c_type IS '*Logistic Cost(C Type)';
COMMENT ON COLUMN sales.pnl_fact.sc_transport_inland IS 'SC.Transport-Inland';
COMMENT ON COLUMN sales.pnl_fact.sc_transport_marine IS 'SC.Transport-Marine';
COMMENT ON COLUMN sales.pnl_fact.sc_transport_air IS 'SC.Transport-Air';
COMMENT ON COLUMN sales.pnl_fact.sc_transport_other IS 'SC.Transport-Other';
COMMENT ON COLUMN sales.pnl_fact.sc_insurance_logis IS 'SC.Insurance (Logis)';
COMMENT ON COLUMN sales.pnl_fact.tot_internal_cgs IS '*Internal CGS';
COMMENT ON COLUMN sales.pnl_fact.sc_internal_cgs IS 'SC.Internal CGS';
COMMENT ON COLUMN sales.pnl_fact.tot_ref_cogs IS '*Ref. CoGS';
COMMENT ON COLUMN sales.pnl_fact.sc_stat_customs_fee IS 'SC.Stat.Customs Fee';
COMMENT ON COLUMN sales.pnl_fact.sc_stat_incidental IS 'SC.Stat Incidental';
COMMENT ON COLUMN sales.pnl_fact.sc_stat_sub_line_exp IS 'SC.Stat.Sub-Line Exp';
COMMENT ON COLUMN sales.pnl_fact.tot_gross_margin IS '*Gross Margin';
COMMENT ON COLUMN sales.pnl_fact.tot_operating_expense IS '*Operating Expense';
COMMENT ON COLUMN sales.pnl_fact.tot_sales_expense IS '*Sales Expense';
COMMENT ON COLUMN sales.pnl_fact.tot_labor_cost_s IS '*Labor Cost(S)';
COMMENT ON COLUMN sales.pnl_fact.sa_labor_cost IS 'SA.Labor Cost';
COMMENT ON COLUMN sales.pnl_fact.sa_labor_salaries IS 'SA.Labor-Salaries';
COMMENT ON COLUMN sales.pnl_fact.tot_svc_expense IS '*SVC Expense';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_warranty IS 'SA.SVC Warranty';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_qual_support IS 'SA.SVC Qual Support';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_agency_fee IS 'SA.SVC Agency Fee';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_call_center IS 'SA.SVC Call Center';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_claim IS 'SA.SVC Claim';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_freight IS 'SA.SVC Freight';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_circulation IS 'SA.SVC Circulation';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_op_support IS 'SA.SVC Op Support';
COMMENT ON COLUMN sales.pnl_fact.sa_svc_other_exp IS 'SA.SVC Other Exp';
COMMENT ON COLUMN sales.pnl_fact.tot_logistics_cost IS '*Logistics Cost';
COMMENT ON COLUMN sales.pnl_fact.sa_transport_inland IS 'SA.Transport-Inland';
COMMENT ON COLUMN sales.pnl_fact.sa_transport_marine IS 'SA.Transport-Marine';
COMMENT ON COLUMN sales.pnl_fact.sa_transport_air IS 'SA.Transport-Air';
COMMENT ON COLUMN sales.pnl_fact.sa_transport_other IS 'SA.Transport-Other';
COMMENT ON COLUMN sales.pnl_fact.sa_warehouse_fee IS 'SA.Warehouse Fee';
COMMENT ON COLUMN sales.pnl_fact.sa_insurance_logis IS 'SA.Insurance (Logis)';
COMMENT ON COLUMN sales.pnl_fact.sa_comm IS 'SA.Comm';
COMMENT ON COLUMN sales.pnl_fact.tot_marketing_expense IS '*Marketing Expense';
COMMENT ON COLUMN sales.pnl_fact.sa_advertising IS 'SA.Advertising';
COMMENT ON COLUMN sales.pnl_fact.sa_co_op IS 'SA.CO-OP';
COMMENT ON COLUMN sales.pnl_fact.sa_promotion IS 'SA.Promotion';
COMMENT ON COLUMN sales.pnl_fact.sa_market_research IS 'SA.Market Research';
COMMENT ON COLUMN sales.pnl_fact.sa_sales_commission IS 'SA.Sales Commission';
COMMENT ON COLUMN sales.pnl_fact.sa_comm_and_svcchgc_card IS 'SA.Comm&SvcChgC.Card';
COMMENT ON COLUMN sales.pnl_fact.sa_hq_sales_comm IS 'SA.HQ Sales Comm';
COMMENT ON COLUMN sales.pnl_fact.sa_corp_promotion IS 'SA.Corp. Promotion';
COMMENT ON COLUMN sales.pnl_fact.tot_royalty IS '*Royalty';
COMMENT ON COLUMN sales.pnl_fact.sa_royalty_3rd_party IS 'SA.Royalty-3rd Party';
COMMENT ON COLUMN sales.pnl_fact.sa_royalty_hq IS 'SA.Royalty-HQ';
COMMENT ON COLUMN sales.pnl_fact.sa_royalty_lump_sum IS 'SA.Royalty-Lump Sum';
COMMENT ON COLUMN sales.pnl_fact.tot_paid_commission IS '*Paid Commission';
COMMENT ON COLUMN sales.pnl_fact.sa_comm_consult IS 'SA.Comm-Consult';
COMMENT ON COLUMN sales.pnl_fact.sa_comm_litigation IS 'SA.Comm-Litigation';
COMMENT ON COLUMN sales.pnl_fact.sa_comm_audit IS 'SA.Comm-Audit';
COMMENT ON COLUMN sales.pnl_fact.sa_comm_d_o IS 'SA.Comm-D/O';
COMMENT ON COLUMN sales.pnl_fact.sa_paid_comm IS 'SA.Paid Comm';
COMMENT ON COLUMN sales.pnl_fact.tot_other_expense_s IS '*Other Expense(S)';
COMMENT ON COLUMN sales.pnl_fact.sa_depreciation IS 'SA.Depreciation';
COMMENT ON COLUMN sales.pnl_fact.sa_insurance_premium IS 'SA.Insurance Premium';
COMMENT ON COLUMN sales.pnl_fact.sa_sample IS 'SA.Sample';
COMMENT ON COLUMN sales.pnl_fact.sa_it_exp IS 'SA.IT Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_lease_and_rent IS 'SA.Lease&Rent';
COMMENT ON COLUMN sales.pnl_fact.sa_bad_debt_exp IS 'SA.Bad Debt Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_travel_exp IS 'SA.Travel Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_telecom_exp IS 'SA.Telecom Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_event_exp IS 'SA.Event Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_survey_exp IS 'SA.Survey Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_social_exp IS 'SA.Social Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_convention_exp IS 'SA.Convention Exp';
COMMENT ON COLUMN sales.pnl_fact.sa_copyright IS 'SA.Copyright';
COMMENT ON COLUMN sales.pnl_fact.sa_weee IS 'SA.WEEE';
COMMENT ON COLUMN sales.pnl_fact.sa_familynet IS 'SA.Familynet';
COMMENT ON COLUMN sales.pnl_fact.sa_other_exp IS 'SA.Other Exp';
COMMENT ON COLUMN sales.pnl_fact.tot_r_and_d_expense IS '*R&D Expense';
COMMENT ON COLUMN sales.pnl_fact.tot_internal_expense IS '*Internal Expense';
COMMENT ON COLUMN sales.pnl_fact.rd_ordinary_exp_matl IS 'RD.Ordinary Exp-Matl';
COMMENT ON COLUMN sales.pnl_fact.rd_labor IS 'RD Labor';
COMMENT ON COLUMN sales.pnl_fact.rd_depreciation IS 'RD.Depreciation';
COMMENT ON COLUMN sales.pnl_fact.rd_consumable IS 'RD.Consumable';
COMMENT ON COLUMN sales.pnl_fact.rd_others IS 'RD.Others';
COMMENT ON COLUMN sales.pnl_fact.rd_er IS 'RD.ER';
COMMENT ON COLUMN sales.pnl_fact.rd_mask IS 'RD.Mask';
COMMENT ON COLUMN sales.pnl_fact.tot_external_expense IS '*External Expense';
COMMENT ON COLUMN sales.pnl_fact.rd_royalty IS 'RD.Royalty';
COMMENT ON COLUMN sales.pnl_fact.rd_outsourcing_svc IS 'RD.Outsourcing SVC';
COMMENT ON COLUMN sales.pnl_fact.tot_g_and_a_expense IS '*G&A Expense';
COMMENT ON COLUMN sales.pnl_fact.tot_labor_cost_sa IS '*Labor Cost(SA)';
COMMENT ON COLUMN sales.pnl_fact.ga_labor_cost IS 'GA.Labor Cost';
COMMENT ON COLUMN sales.pnl_fact.ga_labor_salaries IS 'GA.Labor-Salaries';
COMMENT ON COLUMN sales.pnl_fact.tot_paid_commission_sa IS '*Paid Commission(SA)';
COMMENT ON COLUMN sales.pnl_fact.ga_comm_consult IS 'GA.Comm-Consult';
COMMENT ON COLUMN sales.pnl_fact.ga_comm_litigation IS 'GA.Comm-Litigation';
COMMENT ON COLUMN sales.pnl_fact.ga_comm_audit IS 'GA.Comm-Audit';
COMMENT ON COLUMN sales.pnl_fact.ga_comm_d_o IS 'GA.Comm-D/O';
COMMENT ON COLUMN sales.pnl_fact.ga_comm IS 'GA.Comm';
COMMENT ON COLUMN sales.pnl_fact.tot_expense_s IS '*Expense(S)';
COMMENT ON COLUMN sales.pnl_fact.ga_depreciation IS 'GA.Depreciation';
COMMENT ON COLUMN sales.pnl_fact.ga_it_exp IS 'GA.IT Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_rent_exp IS 'GA.Rent Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_telecom_exp IS 'GA.Telecom Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_repairs_and_maint_exp IS 'GA.Repairs&Maint Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_travel_exp IS 'GA.Travel Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_insurance_premium IS 'GA.Insurance Premium';
COMMENT ON COLUMN sales.pnl_fact.ga_convention_exp IS 'GA.Convention Exp';
COMMENT ON COLUMN sales.pnl_fact.ga_other IS 'GA.Other';
COMMENT ON COLUMN sales.pnl_fact.tot_operating_profit IS '*Operating Profit';
COMMENT ON COLUMN sales.pnl_fact.tot_non_op_income_and_expense IS '*Non-Op. Incom. & Ex';
COMMENT ON COLUMN sales.pnl_fact.tot_non_op_income IS '*Non-Op. Income';
COMMENT ON COLUMN sales.pnl_fact.op_commission_3rd IS 'OP.Commission 3rd';
COMMENT ON COLUMN sales.pnl_fact.op_service_claim IS 'OP.Service Claim';
COMMENT ON COLUMN sales.pnl_fact.op_rental_income IS 'OP.Rental Income';
COMMENT ON COLUMN sales.pnl_fact.op_extra_gain IS 'OP.Extra Gain';
COMMENT ON COLUMN sales.pnl_fact.op_others IS 'OP.Others';
COMMENT ON COLUMN sales.pnl_fact.tot_non_op_expense IS '*Non-Op. Expense';
COMMENT ON COLUMN sales.pnl_fact.oe_loss_on_a_r_sale IS 'OE.Loss on A/R Sale';
COMMENT ON COLUMN sales.pnl_fact.oe_extra_loss IS 'OE.Extra Loss';
COMMENT ON COLUMN sales.pnl_fact.oe_others IS 'OE.Others';
COMMENT ON COLUMN sales.pnl_fact.tot_gain_loss_on_equity IS '*Gain/Loss on Equity';
COMMENT ON COLUMN sales.pnl_fact.tot_gain_on_equity IS '*Gain on Equity';
COMMENT ON COLUMN sales.pnl_fact.eg_gain_on_equity IS 'EG.Gain on Equity';
COMMENT ON COLUMN sales.pnl_fact.tot_loss_on_equity IS '*Loss on Equity';
COMMENT ON COLUMN sales.pnl_fact.el_loss_on_equity IS 'EL.Loss on Equity';
COMMENT ON COLUMN sales.pnl_fact.tot_financial_income_and_expense IS '*Financial  Incom. & Exp.';
COMMENT ON COLUMN sales.pnl_fact.tot_finance_profit IS '*Finance Profit';
COMMENT ON COLUMN sales.pnl_fact.fp_gain_on_fx IS 'FP.Gain on FX';
COMMENT ON COLUMN sales.pnl_fact.fp_interest_income IS 'FP.Interest Income';
COMMENT ON COLUMN sales.pnl_fact.fp_fin_profit_oths IS 'FP.Fin Profit-Oths';
COMMENT ON COLUMN sales.pnl_fact.tot_finance_loss IS '*Finance Loss';
COMMENT ON COLUMN sales.pnl_fact.fe_fo_ex_loss IS 'FE.Fo.Ex.Loss';
COMMENT ON COLUMN sales.pnl_fact.fe_interest_exp_ext IS 'FE.Interest Exp-Ext';
COMMENT ON COLUMN sales.pnl_fact.fe_interest_exp_int IS 'FE.Interest Exp-Int';
COMMENT ON COLUMN sales.pnl_fact.fe_financial_exp_oth IS 'FE.Financial Exp-Oth';
COMMENT ON COLUMN sales.pnl_fact.tot_profit_before_tax IS '*Profit Before Tax';
COMMENT ON COLUMN sales.pnl_fact.tot_corporate_tax IS '*Corporate Tax';
COMMENT ON COLUMN sales.pnl_fact.corp_tax IS 'Corp. Tax';
COMMENT ON COLUMN sales.pnl_fact.tot_net_income IS '*Net Income';

# August profit dashboard

A single self-contained HTML page: the profit chart from the Sales Dashboard
(`new-sales2`, branch `claude/crawl-product-pricing-Hafp4`) — Gross beside stacked
costs, Profit % on a line — driven by hierarchical buttons.

## Build

```powershell
py dashboard\build_dashboard.py            # writes dashboard\profit_2608.html
py dashboard\build_dashboard.py --open     # and opens it
```

It reads `rawdata\profit_2608_1`, `rawdata\customer_2608` and `rawdata\product_2608`
in whatever format they are (the readers from `tools/rawdata.py`), joins the two
masters onto the profit rows, and embeds the rolled-up numbers in the page. No
server, no database, and nothing leaves the machine.

Useful options: `--period 2026.008` keeps one month when the file holds several
(it warns if it does), `--dir` points somewhere other than `rawdata`, `--title`
sets the heading.

## Using it

| Control | What it does |
|---|---|
| **Customer / Product** | which hierarchy the bars break down by |
| **Level** | jump straight to a level — Type → Portal Group → Account, or Division → Category → Range → Product |
| **click a bar** | drill into that member and move to the next level |
| **Back / Reset** | undo one drill, or return to the top |
| **Top 10 / 20 / All** | trim to the biggest members by operating profit |
| **Table** | the same numbers as a table, with totals |

The KPI row above the chart always reflects the current slice, and the bars are
sorted by operating profit.

## Columns it looks for

Found by header name, not position, and the script prints what it matched:

| Measure | Headers accepted |
|---|---|
| Gross | `*S.Gross Sales`, `S.Gross Sales AMT`, `Gross Sales`, `Gross` |
| Sales Deduction | `*Sales Deduction`, `Sales Deduction` |
| COGS | `*Cost of Goods Sold`, `COGS` |
| Operating Expense | `*Operating Expense`, `Op Cost`, `OPEX` |
| Operating Profit | `*Operating Profit`, `Op Profit U$` — derived from the others if absent |

Joins are `sold To` → `customer_2608.Sold-To` and `SKU` → `product_2608.SKU`. The
build prints how many rows matched each; a zero there means the profit export does
not carry that key, and the hierarchy falls back to whatever the profit file itself
has (`Division 2`, `Prod_group`, `Material Group`).

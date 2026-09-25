# August profit dashboard

A single self-contained HTML page in the shape of the Sales Dashboard's profit chart
(`new-sales2`, branch `claude/crawl-product-pricing-Hafp4`): bars beside each other
with Profit % on a line, driven by hierarchical buttons.

## Build

```powershell
py dashboard\build_dashboard.py            # writes dashboard\profit_2608.html
py dashboard\build_dashboard.py --open     # and opens it
```

It reads `rawdata\profit_2608_1`, `rawdata\customer_2608` and `rawdata\product_2608`
in whatever format they are (the readers from `tools/rawdata.py`), joins the two
masters onto the profit rows, and embeds the rolled-up numbers in the page. No
server, no database, and nothing leaves the machine.

## Sending it to someone

The result is one file that opens by double-clicking, in any modern browser, with
nothing installed — Chart.js is embedded, so it works with no internet connection
too (about 240 KB). `--cdn` links jsDelivr instead: a 24 KB file, but then the
recipient needs a connection, and on a network that blocks CDNs the chart simply
does not draw.

Two things to keep in mind before sending it on:

- **The numbers travel with the file.** Every row behind the chart — account names,
  net sales, both profit columns — is embedded in the HTML and readable by anyone
  who opens it, or who opens it in a text editor. Treat sending the page as sending
  the underlying data.
- It is a snapshot. Re-run the build to refresh it; the file does not update itself.

Useful options: `--period 2026.008` keeps one month when the file holds several
(it warns if it does), `--dir` points somewhere other than `rawdata`, `--title`
sets the heading.

## Using it

| Control | What it does |
|---|---|
| **Customer / Product** | which hierarchy the bars break down by |
| **Profit: Subsidiary / Allocated** | which operating profit column drives the profit bar, the line and the sort |
| **Metric: Amount / Qty** | Net Sales and Op Profit, or Net Sales Qty on its own (a percentage of units means nothing, so the line and right axis come off) |
| **Level** | jump straight to a level — Account Name → Type → Portal Group → Account, or Division → Category → Range → Product |
| **click a bar** | drill into that member and move to the next level |
| **Back / Reset** | step out one level, or return to the view the page opens on |
| **Customer (all)** in the breadcrumb | jump to the very top — every account name side by side |
| **Top 10 / 20 / All** | trim to the biggest members by operating profit |
| **Table** | the same numbers as a table, with totals |

The KPI row above the chart always reflects the current slice, and the bars are
sorted by operating profit.

**The page opens on the online account name** (E-STORE), since that is the day-to-day
view. The offline rows are still in the file: `Back`, or the **Customer (all)** button
in the breadcrumb, shows E-STORE and OFF-LINE side by side for comparison, and `Reset`
returns to the online view. `--start-customer NAME` picks a different starting account,
and `--start-customer ""` opens at the top instead.

The offline rows carry no Type or Portal Group — those levels collapse to a single
`(blank)` bar there and the drill continues to the account underneath, which is
expected rather than a join failure.

## Columns it looks for

Found by header name, not position, and the script prints what it matched:

| Measure | Headers accepted |
|---|---|
| Qty | `Net Sales Qty`, `Qty`, `Quantity` |
| Net Sales | `Net Sales`, `*S.Gross Sales` (older P&L export) |
| Op Profit (Subsidiary) | `Subsidiary Op.Profit`, `*Operating Profit` (older export) |
| Op Profit (Allocated) | `Allocate Op.Prof`, `Allocate Op.Profit` |

Profit % is the selected operating profit over net sales.

Joins are `Payer` (or `sold To`) → `customer_2608.Sold-To` and `Material` (or `SKU`)
→ `product_2608.SKU`; the period column is `YYYYMM` or `Period`. The
build prints how many rows matched each; a zero there means the profit export does
not carry that key, and the hierarchy falls back to whatever the profit file itself
has (`Division 2`, `Prod_group`, `Material Group`).

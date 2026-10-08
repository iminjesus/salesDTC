# ASP - average selling price

## Two workbooks, for Excel

```powershell
py tools\asp_xlsx.py --months 2607 2608 2609
```

Writes exactly two files, keyed on **material code**:

| | |
|---|---|
| `Material.xlsx` | every material code, all channels |
| `Online ASP.xlsx` | every material code, the online channel only |

Each row carries five columns **per month**, then the same five over the span,
then the promotion each month ran under:

| per month | |
|---|---|
| `Jul 26 qty`, `Jul 26 net sales` | the profit export's own figures |
| `Jul 26 ASP` | `=IF(F2>0,G2/F2,"")` - what those two come to |
| `Jul 26 RRP` | the list price the plan had on it that month |
| `Jul 26 DC %` | how far under the RRP the price landed |
| `Jul 2026 - Sep 2026 qty`, `... net sales`, `ASP (...)` | the span, weighted |
| `RRP (...)`, `DC % (...)` | the months' own, weighted by the units each sold |
| `Jul 26 promotion` | what most of that month's units ran under |

The span and the computed columns are **formulas** - `=F2+K2+P2`, not a number
worked out here - so the sheet still adds up when a month's column is edited.
Each formula also carries the value it comes to, which is how Excel stores one
itself: the sheet recalculates on open, and anything reading the file without
opening it still sees the number rather than a blank.

### The totals are the profit export's

Units and net sales come from the profit exports and from nothing else. The plan
and the store's own orders are read only to **label** what the profit export
already counted - an RRP, a discount, a promotion name - and neither can add a
unit, move a dollar, or drop a material from the sheet. The run proves it rather
than claiming it:

```
against the profit exports: <units> net unit(s), <amount> net sales
  Material.xlsx: <units> and <amount> - they match
  Online ASP.xlsx: <units> and <amount>, the E-STORE share of it (<pct>% of net sales)
```

The console blocks quoted here show the **shape** of the output; the figures in
them are placeholders, not a reading of any month.

An export row with no material code cannot go in a workbook keyed on the
material, so it is named with its units and its value; anything left over after
that goes to stderr, because it would be a fault here and not in the export.

### RRP, and the GST underneath it

The plans are asked first - they are kept month by month and carry the windows,
so they know a price that changed in the middle of August - and the product
master answers where they have nothing. `--plan` defaults to **`MX_product
ce_product`**, one file per division read together, and a run with more than one
prints where their columns differ before using them (see `docs/PROMO.md`); a
stem that names no file is skipped. Which one answered is
counted, not blended:

```
RRP, for <n> material code(s):
      <n>  MX_product.csv, in month
      <n>  ce_product.csv, in month
      <n>  MX_product.csv, another month
      <n>  product master
      <n>  nothing says
```

Where several plan lines are live in the month, the commonest RRP wins, and the
highest among equals: a list price, not one of the offers sat under it.
Cancelled and unapproved plan lines never count.

**DC % = 1 - realised price ÷ (RRP ÷ 1.1).** A plan RRP is what a customer sees
on a shelf, so it includes GST; net sales does not, and comparing the two
straight overstates every discount by a flat ninth. The divisor is written into
the cell - `=IF(AND(I2>0,H2>0),1-H2/(I2/1.1),"")` - so the assumption is visible
to whoever opens the sheet and can be edited there instead of argued about. Run
with `--gst 1` if the RRP you load is already ex GST. The run prints the check
either way:

```
    median realised / RRP: <x> as the plan writes it, <y> with GST taken off at 1.1
    <n> (<pct>%) sold above the RRP as written
```

A large share selling *above* its own RRP means the RRP is already ex GST, and
the line says so.

### The months that have not happened yet

```powershell
py tools\asp_xlsx.py --months 2607 2608 2609 --forecast 2611 2612 2701
```

writes a third file, `ASP forecast.xlsx`, and leaves the other two exactly as
they were. What is known about a future month is what the plan says about it: an
RRP, a planned price, an offer type and an offer detail. What is **not** known is
how far the price actually realised will sit from the planned one - and that is
measurable, because the same two numbers sit side by side in every month that
has closed.

| | |
|---|---|
| `plan DC %` | `1 - the planned price / the RRP`, as the plan writes it |
| `DC %` | `1 - net sales over units / the RRP ex GST`, as it happened |
| `bias` | the second minus the first, weighted by the units behind each month |

```
forecast ASP  =  the month's RRP ex GST  x  (1 - (its plan DC % + bias))
```

A bias of +4pp says this material has been selling four points cheaper than
planned - EPP tiers taking more off than S.COM, a price sharpened mid-month, a
clearance nobody put in the plan. A bias of -6pp says the planned discount was
not what most buyers took. Either way it is this material's own recent history,
and a forecast that leaves it out is the plan repeated rather than a forecast.
Where the plan does not change, the forecast comes out at the realised ASP,
which is the property that makes the arithmetic worth trusting at all.

Every term is a column and the arithmetic is a formula, so **overwrite the bias
on a row and the forecast moves**. The run prints the median bias and counts the
materials beyond ±15pp - those are the rows to read before trusting - and says
when a forecast came out above the RRP or below nothing, which is a bias too big
for the material rather than a price.

Three further decisions, all visible in the sheet:

- `plan DC %` is the **median** over the plan lines live that month, from the
  first price each line carries of `S.COM_Price`, `T2`, `T3`, `EDU`, `T1`. A
  material with one clearance line and four ordinary ones is not on clearance,
  and the deepest offer is the one a forecast should be least sure of. Both
  sides of the bias use that same definition, which is what makes subtracting
  them mean anything.
- The **promotion** column is the same five bands the closed months carry, read
  from the same plan. There are no units yet to weight by, so the share is of
  the month's own days: a campaign live from the 1st to the 25th of November
  covered 83% of it, and the cell says so.
- A material the plan prices for November but which **has not sold** in the
  months read is still in the sheet, with its category's median bias and a last
  column that says so. A product launching in November has no row in any profit
  export and is exactly what a forecast is for. Its description and division
  come from the plan, which is the only file that has them.

A month the plan says nothing priced about is **blank, not carried over** from a
neighbouring month: an RRP printed beside a month the plan does not cover reads
as a plan for that month. And a longer `--months` gives a steadier bias at the
cost of a wider actuals sheet, because the same flag drives both.

### The promotion, and why it carries a share

The promotion comes from **the plan**, read the way the P&L page and the profit
split read it: the product code and the order's date against the plan's windows
and its campaign columns. Not from the price, which a trade-in or a stacked
voucher moves away from what the plan quotes, and not from the rule the store
engine applied, which is the engine's account of itself rather than the campaign
the order belongs to. The three tools now share one reading of the plan
(`PM.plan_state`), so the same August order cannot be `EPP welcome voucher` here
and `DTC + Nation-wide` on the page.

Five answers, the same five the page stacks:

| | |
|---|---|
| `DTC promotion` | a DTC campaign was live, and no nationwide one |
| `DTC + Nation-wide` | both were |
| `Nation-wide only` | a nationwide campaign, with no DTC campaign beside it |
| `No promotion` | a plan line was live and named no campaign |
| `Not in the plan` | no plan line covered that product on that date |

The last two are not the same answer and are not merged: one is the plan saying
there was no promotion, the other is the plan saying nothing.

A material-month rarely sits on one band - a campaign that ends on the 20th
leaves the rest of the month somewhere else - so the cell names the band most of
its **units** ran under, with the campaign inside it and the share:

```
DTC promotion: FF8 Pre-Order / Trade-in bonus (58% of units, 1 other)
DTC + Nation-wide: QLED Days
Not in the plan
```

A share below 100% means the rest ran under something else, not that the label
is uncertain. Campaign spellings that differ only by case or punctuation are
folded to the one the plan uses most, so `DTC boost week` and `DTC Boost Week`
are one campaign. Cancelled orders are left out.

`--promo-from rule` brings the old column back - the rule the store engine
applied, with `--detail` and `--precedence` working on it as they did. The store's orders are its own channel:
in `Material.xlsx` a material sold mainly elsewhere shows the promotion its
store units ran under and nothing about the rest, which the foot of the sheet
says.

### The three-month figure is weighted

ASP over a span is **the span's totals divided**, not the average of the three
months' own prices. A flat mean would let a month that sold forty units weigh as
much as one that sold four thousand. On a small test that is not a rounding
difference:

| material | weighted | flat mean | gap |
|---|---|---|---|
| RF9000 | 1,143.24 | 1,259.42 | **-116.18** |
| WW11 | 1,297.54 | 1,229.91 | +67.63 |
| SM-S926 | 809.66 | 842.88 | -33.22 |

A material whose returns outweigh its sales over the span has no price: the cell
is left **blank** and the count is reported, rather than dividing into a
negative. The note at the foot of each sheet says all of this where the reader
will see it.

### Written with the standard library

`tools/xlsx.py` writes the workbook from `zipfile` and strings - an .xlsx is a
zip of XML, and `rawdata.py` already reads one that way. Nothing to install,
which is the point: these tools run where installing things is not an option.


```powershell
py tools\asp.py                          # -> docs\asp_sku.csv, docs\asp_category.csv
py tools\asp.py --by Division Category Range
py tools\asp.py --split Channel Type     # and the same again, split by customer
```

## What it computes

**ASP = net sales ÷ net quantity**, taken as one weighted figure per group: the
totals divided, never the average of each row's own price. Averaging the rows
would let a single unit weigh as much as a pallet.

Where the export also carries a gross quantity and gross sales, a second
**ASP (gross)** column comes out beside it, on the same rule.

Every run writes one csv per grouping - `asp_sku.csv` always, plus one for each
level named in `--by` - and prints the biggest sellers of each to the console.
SKU is always included: a category ASP that looks wrong is usually one SKU
inside it, and the two files sit side by side.

The csvs are UTF-8 with a BOM, so Excel opens them without the import wizard.

## Grouping

`--by` takes any product level the master carries: `Division`, `Category`,
`Range`, `Series`. Each becomes its own file, e.g. `docs\asp_range.csv`.

`--split` adds customer dimensions to every grouping - `Channel`, `Type`,
`Portal Group`, `Type2` - so `--by Category --split Channel` gives one row per
category per channel. The levels are the ones in `tools\customer.py`, the same
ones the profit chart drills.

The product levels come from `product_2608` joined on the SKU, and the customer
levels from `customer_2608` joined on the payer. The build prints how many rows
matched; a zero there means the export's key column is not one this build
recognises, and it prints both sides so the mismatch is visible.

## Returns, and when there is no price

The export nets returns off both sides already, so a group whose returns
outweigh its sales can end up with a zero or a negative quantity. Those are
**reported and left blank**, not divided:

```
1 of them have no net quantity to divide by (returns cancelling sales, or a
sale booked with no units); their ASP is left blank
```

A price of minus four hundred is not a price, and an infinity in a spreadsheet
is worse. The quantity and the sales are still in the row, so the group can be
looked at on its own terms.

A negative net quantity with negative sales does divide to a positive ASP, and
that figure is real - it is the price the returns were credited at.

## Columns in the csv

| Column | |
|---|---|
| the level, and `Description` for SKU | what the row is |
| the `--split` columns | when asked for |
| `Rows` | export rows behind the figure |
| `Qty (net)`, `Net Sales`, `ASP` | the weighted price |
| `Qty (gross)`, `Gross Sales`, `ASP (gross)` | when the export carries them |

Rows are ordered by net sales, biggest first.

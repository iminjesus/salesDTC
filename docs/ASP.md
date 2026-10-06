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

Each row carries the quantity and net sales for **each month**, then the span's
totals and the ASP. The span columns are **formulas** - `=F2+H2+J2`, not a
number worked out here - so the sheet still adds up when a month's column is
edited. Each formula also carries the value it comes to, which is how Excel
stores one itself: the sheet recalculates on open, and anything reading the file
without opening it still sees the number rather than a blank.

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

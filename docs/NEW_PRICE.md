# The re-priced month, written into the GSCM sheet

```
py tools\new_price.py                          # rawdata, the month the sheet prices
py tools\new_price.py --month 2610 --back 6
py tools\new_price.py --blank-kept             # usually what a simulation wants
py tools\new_price.py --out rawdata\GSCM_Oct_new.xlsx
```

Writes `rawdata\GSCM_Oct_new_price.xlsx` - the sheet exactly as it was, with
one column added.

## What the column is

`New Price <Mon>` is the price the month could have been planned at: the
promotion plan's list price, discounted by what the same campaign has been
selling at over the months behind it. `docs/REPRICE.md` has the method.

It is the **same number the dashboard draws**, from the same call
`dashboard/build_pnl.py` makes - `tools/reprice.py` over `rawdata` - so the
column and the card cannot disagree. Change `--back` and both move together.

## One column, and why only one

Nothing about actuals is written. A `SUMIFS` against the order export does
that better than a pasted number can, and it keeps the sheet's own figures
the sheet's own. The predicted price is the one thing the sheet cannot work
out for itself, so it is the one thing added.

The column goes straight after `<Mon> Price(AUD)`, the price it is there to be
compared with. Every other column keeps its contents and its order, and the
run checks that nothing else moved.

The sheet is one row per material **per account** - E-STORE, E-STORE_B2B. The
price is the material's, so each of its rows carries the same number.

## Blanks, and the `kept` trap

| what happened | what the cell holds |
| --- | --- |
| re-priced off a list price and a campaign discount | the new price (`rrp`) |
| no list price in the plan, so the six-month ASP stood in | the new price (`asp`) |
| no list price **and** no history | the GSCM price, unchanged (`kept`) |
| the sheet prices it and the re-price never saw it | blank |

The third row is the one to watch. A `kept` material comes back carrying the
number the sheet already had - that is what the card shows, and on the card it
reads as a zero difference. In a bare Excel column it is indistinguishable
from a prediction that happens to agree. The run says how many there are, and
**`--blank-kept`** leaves them empty instead, which is usually what a
simulation wants: a blank cannot be mistaken for a forecast.

## Running it twice

Safe. The tool skips its own output when looking for the sheet, and a sheet
that already carries the column has it rewritten rather than given a second
one. Pointing `--gscm` at a `*_new_price.xlsx` on purpose reads that file and
refreshes its column in place.

## Formatting

With `openpyxl` installed the workbook keeps everything - fonts, widths,
colours, number formats - and only gains the column. Without it the sheet is
rewritten with the repo's own stdlib writer: every value is kept, the colours
are not. The run says which of the two happened, so a file that comes back
plain is explained rather than puzzling.

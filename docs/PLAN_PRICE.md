# The price the month was planned at

```
py tools\plan_price.py                    # what it reads and what it holds
py tools\plan_price.py --month 2610
py tools\plan_price.py --top 20           # the biggest lines of the plan
```

Put the GSCM sheet in `rawdata` with a name starting `gscm` - `GSCM_Oct.csv`
and `gscm_2610.csv` are both found - and `dashboard/build_pnl.py` picks it up
on the next build. Nothing else needs changing.

## What it is

The Blue File sets the month's target **by product group**: one number for
REF, one for TV, one for Smartphone. The GSCM sheet is the same month's plan
**by material**: how many of each code the month is meant to sell and at what
price, in AUD and in USD. Its amounts add up to the same target.

That extra level is the whole point of reading it. A target by product group
can say a division is 5% behind and cannot say whether that is units or
price - and those are two different conversations with two different people.
A price per material can.

## What it reads

A row is one material for one account (`E-STORE`, `E-STORE_B2B`). The sheet
holds three months side by side and names each column after its month, so
October is read out of the `Oct` columns and nothing else:

| what | column |
| --- | --- |
| material | `Item` (the order export calls the same string `Material`) |
| planned price | `Oct Price(AUD)`, `Oct Price(USD)` |
| planned units | `Oct Targer Qty` - the file's own spelling, and `Oct Target Qty` |
| planned amount | `OCT(AUD)`, `OCT(USD)` |
| where it sits | `Biz`, `DIV 1`, `DIV 2`, `Product Group` |

The price is the material's and is the same on every one of its rows; the
units and the amounts are the account's and are added together. Where the
sheet has no price column at all, the amount over the units is used instead
and the run says how many rows that was - an amount over a quantity is an
average, not a price list, and the difference should not be silent.

`--month` picks another month of the same sheet. Without it the first month
the sheet prices is read, and the run says which months were on offer.

## How the page uses it

Three tiles, a table and two Top 10 lists under the daily chart, in
`docs/PNL.md` under **Planned price vs actual**. All of it follows the page's
slice, its currency and its Order/Payment base.

The join is on the material code, upper-cased, and the build says how many of
the planned materials the order export actually holds. If that number is zero
the two files are not talking about the same codes, the tables are left off
and the run says so rather than drawing an empty card.

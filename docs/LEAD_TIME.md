# How long after an order it leaves

```powershell
py tools\lead_time.py --month 2609
py tools\lead_time.py --month 2609 --online
py tools\lead_time.py --month 2609 --by div3
```

A month's target is hit by what **leaves** in the month. An order placed near
the end of it leaves in the next one, so whether a division makes its number
depends on its lead time as much as on its demand - and the two are measured
in different places: demand is `Created On`, revenue is `Goods Issue Date`,
and the gap between them is this.

```
days from order to despatch, 202609 orders, by Div 1
  Div 1                        units   avg days   still open  of units
  DA                              20        5.0            0        0%
  VD                              10        1.0           10       50%
  --------------------------------------------------------------------
  all                             30        3.7           10       25%
```

The average is **weighted by units**, not by line: a line of forty and a line
of one are not the same order, and the question is how much revenue moves, not
how many rows.

## Three things that would make it read short

- **Only orders placed in the month** are read. What left in the month but was
  ordered before it belongs to an earlier month's demand, and counting it here
  would be measuring a lead time that started somewhere else.
- **The month's export is not enough.** A September order that left in October
  is on October's export, so every `orders_*` cut from the month onward is
  read. A line that appears twice - open in September, shipped in October - is
  collapsed to one, and the record that has left wins.
- **Lines that have not left are not averaged.** They are the slow end, so
  folding them in as nothing would be wrong and dropping them silently would
  be worse. They are counted beside the average, with their share of units,
  and the run says the real figure is longer than the one printed.

The run also names the newest order on the export: a line placed on that date
has had no time to leave at all, which is why the last days of a month drag
the average down rather than up.

`--online` narrows to the online business, which is what the Sokbo target is
set for. `--by` takes `biz`, `div1`, `div2`, `div3`, `range` or `sku`.

## What the master cannot place

```powershell
py tools\lead_time.py --blank --out docs\unplaced.csv   # every export
py tools\lead_time.py --month 2610 --blank               # one month
```

With no `--month` it sweeps **every** `orders_*` export in the folder, because
the master is a standing thing and the question it raises is not what one
month lost but what it has never known. Each code then carries the months it
was ordered in and the first and last order seen, so a code that arrived with
a launch reads differently from one that has been missing all year. `--out`
writes the lot as a csv - the list that goes to whoever maintains the master.

A product group's target stands whole whether or not the orders under it can
be placed, so a code the product master has never heard of takes its money off
the page and leaves the target behind - which reads as a division that missed.
`--blank` lists them, split by what is actually wrong, because the two have
different consequences:

```
202610: no row in the product master - the page drops these
  code                     units          value   what the master does have
  SM-X310                      6          5,400   -
  ---------------------------------------------
  2 code(s)                    9          9,000   dropped

202610: a row, but a level left empty - drawn under a placeholder
  SM-X210                      4          2,800   Biz=MX, Div 1=MX, Div 2=Mobile
```

- **No row at all**: every level is empty, so `--drop Biz=(blank)` takes it
  out. Its money is on no chart and in no achievement, and nothing on the page
  says it was there.
- **A row with a level left empty**: it keeps its Biz, so it stays on the page
  and lands under a placeholder further down - visible, but not where anyone
  is looking for it.

The right fix is the master, not the page: add the codes and both numbers land
where the target is.

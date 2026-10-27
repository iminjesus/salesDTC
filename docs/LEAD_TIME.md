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

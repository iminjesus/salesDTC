# What did each promotion earn?

```powershell
py tools\promo_profit.py                       # completed orders, online profit
py tools\promo_profit.py --status "COMPLETED,SHIPPED"
```

## What this can and cannot say

**The profit file carries no promotion.** It carries products, and the order
file says which promotion each product's units came in on. The product is the
only link between them, and nothing more direct exists in either file.

So each product's online profit is **allocated** across the promotions its
completed orders came in on, in proportion to the units they carry. A product
sold 70/30 between two promotions hands them 70/30 of its margin.

That is an allocation, not a measurement. It assumes every unit of a product
earns the same margin whichever promotion brought it in - which is exactly what
a discount does not do. Reading it as "this promotion cost us X margin" is the
one thing it cannot support.

What it is good for is **ranking**: which promotions carry the volume, and
which carry margin out of proportion to it. A promotion whose share of net
sales is far above or below its share of units is worth opening; one whose
margin sits away from the rest is worth opening too.

## Only completed orders

`--status` is `COMPLETED` by default, which is the narrowest honest choice: an
order that has not completed is not August revenue. The run says how many lines
that left out.

## How much of the channel it describes

Allocation needs a product to have completed orders. Where it does not, its
profit lands in a row of its own rather than being spread over promotions it
had nothing to do with:

```
profit: 6,834 of 30,275 row(s) are E-STORE, over 1,123 product code(s)
  946 of them have completed orders to allocate by, 81.4% of the net sales
```

Under half and the run says so: the tables then describe that half, not the
channel. `(sold with no completed order)` is the rest, kept visible.

## Reading it

```
by offer type  (profit allocated by unit share, not measured)
                                    units    net sales    op profit  margin  share  from
  Discount                          1,673      807,185      110,366   13.7%  26.1%  rule
  PWP                               1,489      722,595       96,033   13.3%  23.4%  rule
  GWP                               1,341      625,324       83,874   13.4%  20.2%  rule
  Bundle                              159       81,890       13,156   16.1%   2.6%  plan
```

**from** is how the promotion was identified - the store's own rule, a voucher,
or inferred from the plan - not a promotion of its own, so the offer types are
rolled up across it rather than listed once per source. A row whose `from` is
`plan` rests on inference; one whose `from` is `rule` does not.

Then the same by **offer detail**, which is the level the individual campaigns
sit at.

`docs\promo_profit.csv` carries every row with all six P&L figures - units, net
sales, COGS, gross margin, operating cost, operating profit - and the margin.

## The page

```powershell
py tools\promo_profit.py --html      # -> dashboard\promo_profit.html
```

Bars are net sales (or operating profit - there is a toggle) per offer,
**split by which source identified the promotion**, with a line for **operating
profit over net sales** on the right-hand scale. Gross margin is carried too,
in the KPI row and in the table, because "margin" on its own reads as either
and the file holds both.

A tall spike on a short bar is a small denominator, not a good promotion - the
bar heights say which spikes are worth anything. So the two questions sit on one chart: which promotions
carry the volume, and which carry margin away from the rest.

A bar that is mostly blue was answered by the store's own rule and rests on
nothing inferred. One that is mostly green or yellow rests on the plan match,
and its margin should be read with that in mind.

**Bars by** charts any level of the chain, and clicking a bar opens the next
one:

```
Channel -> Type -> Type2 -> Customer -> Offer type -> Offer detail
```

The customer half comes off the **payer on the profit row**, not the order
file - the order file has no payer on it - so it is the same Channel / Type /
Type2 the profit chart drills, down to the individual account. The promotion
split is still the product's, since that is the only thing the two files share,
but the profit being split knows whose it was.

The page opens on **Offer type**, with the customer levels above it to step up
into. The caveat above the chart is on the page itself,
not only in this file, because the number is easy to quote and the caveat is
not.

## The levers

The attribution is the same one `promo_match` makes, so `--stem`,
`--window-slack` and `--price-tolerance` work here too and mean the same
things. `docs\PROMO.md` covers what each loosening buys and what it costs.
`--online` and `--account` pick which side of the profit file is allocated,
the same as in `docs\RECONCILE.md`.

## The stack: how much of the month ran on a promotion

The page opens on **one bar, split into bands** - the shape this was asked for -
and clicking it opens that bar by the band itself, then by the offer inside it,
with the customer levels last. Every bar at every level is split the same way,
so a bar can be read against any other and the split holds all the way down.

| band | |
|---|---|
| **DTC promotion** | a plan line covering this product on this date names a DTC campaign |
| **DTC + Nation-wide** | it names both |
| **Nation-wide only** | it names the nationwide campaign and no DTC one |
| **promoted, but no campaign named** | something answered for the line - a rule, a voucher, a priced plan line - but no campaign is on it |
| **No promotion** | nothing covers it at all |

The fourth band exists because the alternative is filing those units under one
of the three they are not. The last two are different statements and are kept
apart.

**The band is read from the product code and the date, not from the price** -
the same test `promo_match --dtc-only` uses. Deciding it off the price-matched
plan line would make this page disagree with that one about the same order,
because the price rejects lines the plan does cover: a trade-in or a stacked
voucher moves what was collected away from what the plan quotes.

## Last month's promotion, this month's profit

A promotion that ran in July is in July's order export. An order it brought in
can complete in August, and then its profit is in August's profit file with no
promotion against it - so it lands in *No promotion*, which is the one answer it
certainly is not.

So **the month before is read too**, automatically, wherever its file is on
disk: `26 DTC Aug` pulls in `26 DTC Jul`, and January steps the year back to
`25 DTC Dec`. `--orders` takes several stems if the derived name is not the
right one, and `--no-previous` turns it off.

Neighbouring exports overlap - a cut taken part-way through a month turns up
again in the next file - so an order line seen twice is counted once, by order,
product, date, quantity and amount. Double counting would not move the totals,
which come off the profit file, but it would skew the share each promotion is
allocated. The run says how many it folded, and the page names every file it
read rather than the one stem that was asked for.

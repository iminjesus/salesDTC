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

## The levers

The attribution is the same one `promo_match` makes, so `--stem`,
`--window-slack` and `--price-tolerance` work here too and mean the same
things. `docs\PROMO.md` covers what each loosening buys and what it costs.
`--online` and `--account` pick which side of the profit file is allocated,
the same as in `docs\RECONCILE.md`.

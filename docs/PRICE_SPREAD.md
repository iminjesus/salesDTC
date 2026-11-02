# How consistently the month missed its price

```
py tools\price_spread.py                     # by Div 2, both bases
py tools\price_spread.py --by div1
py tools\price_spread.py --top 15            # what is making the spread
py tools\price_spread.py --out docs\spread_2610.csv
```

## What it answers

The dashboard's gap card says a division came in 253 under the price it was
planned at. That one number has two very different stories behind it:

| what happened | what to do about it |
| --- | --- |
| every model came in about 253 under | the plan's price for that division was wrong - correct the level |
| half came in 900 under, half 400 over | the level was close, the mix of prices was not - correct model by model |

A mean cannot tell those apart. A standard deviation can, so this reports the
two side by side, for each division, on both bases:

- **vs GSCM** - the price the sheet planned the month at
- **vs re-priced** - the price `tools/reprice.py` says it could have planned,
  from the RRP and the discount the same campaign had been selling at

Both are the same subtraction the dashboard makes - a material's realised
price less its planned one - read **over** the materials of a division rather
than added **up** over them.

## What the deviation is taken over

The **gap**, never the price:

```
gap(material)  =  what it actually sold at  -  what it was planned at

mean gap   =  the division's miss per unit            (x units = the card's impact)
sd of gap  =  how much that miss varies model to model inside the division
```

A deviation of the prices themselves would only say that a division sells a
fridge and a kettle, which nobody needed a number for. A deviation of the
**gaps** says whether the division missed its plan the same way everywhere or
in opposite directions, and those call for different fixes.

## How it is weighted

Every figure is weighted by the units that actually sold, so

- the **mean** is the division's real miss per unit, and `mean × units` is the
  price impact the dashboard's card shows, and
- the **spread** is over the units the month actually moved: a model that
  sold three units does not pull the division's deviation as far as one that
  sold three thousand.

The deviation is the population one over those weights. These are the units
the month sold, not a sample drawn from something larger, so there is no
`n-1` to make.

Both sides are the order export, `orders_26XX`, on its `Net Value (Item)` -
the same money the gap card is on, which is **not** the profit export's net
sales. The two are about 15% apart and a per-unit price off one is not a
per-unit price off the other.

## Reading it

```
                                  --- gap vs GSCM ---  - gap vs re-priced -
div2                n     units   mean gap  sd of gap   mean gap  sd of gap   reading
REF                24     3,104       -181        312        -42        266   offsetting - the mix, not the level
Mobile             31     4,136        +74         95        -22         88   level and mix both
```

REF there missed its plan by 181 a unit on average and by 312 either side of
that, so its models are not missing together - some came in far under their
planned price and some over it. Mobile missed by less and missed it more
consistently.

The last column is the ratio of the two said out loud:

| sd / |mean| | reading |
| --- | --- |
| under 0.5 | **systematic** - the level is wrong, and one number fixes the division |
| 0.5 to 1.5 | level and mix both |
| over 1.5 | **offsetting** - the mix, not the level; a division average here is hiding two opposite errors |

A division that nets near zero with a large spread is the one worth stopping
on. It will not appear on a card of price impact at all, and nothing about it
was priced right.

The second table is the same two readings **as a share of the price planned**,
because 253 off a 900 phone and 253 off a 4,000 fridge are not the same miss
and a column of dollars cannot say so.

## Is the deviation the group, or a few rows?

A deviation squares its distances, so a handful of lines can carry one on
their own - and that changes what to do about it. Two blocks answer it:

**Where the gap actually sits** gives `p10 / median / p90` beside the `sd`,
all on the same unit weights. A middle at least twice the deviation means the
units really are spread out; a middle narrower than the deviation means a few
rows are carrying it. Read as what it is, not as a verdict: a material holding
a third of a division's units is not an outlier by weight however far out it
sits.

**Materials at over 3x the planned price, or under a third of it** are then
listed with their units, and the run prints what the mean and deviation become
without them. Not every large gap is a price: a bundle booked under one
material, or a quantity in a different unit, lands here as a price several
times the planned one and moves a deviation more than any discount can. They
are listed and not dropped - whether they are wrong is not this tool's call to
make silently. `--odd X` moves the threshold.

A deviation that collapses once those come out was never about pricing.

## Grouping is part of the answer

A deviation is only as meaningful as the bucket it is taken over. If one Div 2
holds the whole of a business - phones, tablets, wearables and a $70 cable -
then a large deviation is arithmetically right and says nothing: it is the
range of the catalogue, not the inconsistency of the plan. `--by div3` cuts it
finer, and the per cent table is the one to read when a bucket spans price
points, because 253 off a 900 phone and 253 off a 4,000 fridge are not the
same miss.

`--top N` then names the materials furthest from their own division's mean,
weighted by the units behind them: a division's deviation is a property of its
models, and naming them is the difference between knowing the plan is
inconsistent and being able to do something about it.

## What it leaves out

- **Planned and not sold.** No realised price, so nothing to measure. The gap
  card counts these separately - it is a volume question, not a price one.
- **Sold with no line in the plan.** Nothing to measure against.
- **Materials the sheet prices at nought**, and returns, credits and rejected
  lines: a return has no price to read, and averaging one in would put a
  number in the ASP column that nobody sold at.

Materials with no re-priced price count on the GSCM side only, and the run
says how many that was.

## The month's shape

`plan_price` reads a sheet and takes `YYMM`; `reprice` walks real dates and
takes `YYYYMM`. `--month` accepts either and the conversion is made inside.
Passing the short form straight through to `reprice` reads no history at all
and leaves every price exactly as the sheet had it, which looks like a result
rather than a mistake - which is why the run prints how many prices it
actually moved.

## The CSV

`--out` writes one row per material - chain, units, order value, ASP, both
planned prices, both differences in money and in per cent - ordered by price
impact, worst first. It holds real prices material by material, so
`/docs/spread_*.csv` is gitignored like the rest of them.

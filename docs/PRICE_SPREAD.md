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

## How it is weighted

Every figure is weighted by the units that actually sold, so

- the **mean** is the division's real miss per unit, and `mean × units` is the
  price impact the dashboard's card shows, and
- the **spread** is the spread of the money, not of the catalogue: a model
  that sold three units does not move it as far as one that sold three
  thousand.

The deviation is the population one over those weights. These are the units
the month sold, not a sample drawn from something larger, so there is no
`n-1` to make.

Both sides are the order export, `orders_26XX`, on its `Net Value (Item)` -
the same money the gap card is on, which is **not** the profit export's net
sales. The two are about 15% apart and a per-unit price off one is not a
per-unit price off the other.

## Reading it

```
div2                n     units       mean         sd       mean         sd   reading
REF                24     3,104       -181        312       -42        266   offsetting - the mix, not the level
Mobile             31     4,136        +74         95       -22         88   level and mix both
```

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

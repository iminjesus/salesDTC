# Re-pricing the month from what it has been selling at

```
py tools\reprice.py                  # -> docs\reprice_2610.csv
py dashboard\build_reprice.py        # -> dashboard\REPRICE_OCT.html
```

The P&L page measures October against the price the GSCM sheet planned it at,
and the gap is large. Most of that gap is not a discount anyone gave: it is a
plan written before the month was traded. This answers the counterfactual -
what would the gap have been if the plan had been built from what these
products were already selling for?

## The price

```
price = RRP x (1 - discount),  one day at a time, averaged over the month
```

| | from |
| --- | --- |
| the list price | the promotion plan's `RRP` column |
| the discount | what came off that list price the last time the product sold **under the same campaign** |
| which campaign | October's own plan, read day by day |

A campaign comes round - SECRET SALE, BOOST WEEK, Samsung Week - so the
discount is read **per campaign**: what a product went out at during Boost
Week in August is the best guess at what it will go out at during Boost Week
in October. A day with no campaign on it takes the product's own
off-promotion discount, which is rarely nought; a list price is not a street
price.

The month is walked a day at a time because a campaign covers days, not
months. A product on Boost Week for nine days of October is not priced like
one on it for all thirty-one.

**Where a product has too little history of its own** (under five units) the
discount is borrowed, in this order: the same campaign at Div 3, then Div 1,
then across the book. Each row of the output says which was used.

**Where the plan quotes no RRP** - and it has one for about seven materials in
ten - the six-month ASP stands in. **Where there is no history either**, the
GSCM price is left exactly as it was. The run counts all three.

Two deliberate limits:

- A discount never goes below nought. A price over its own list price is a
  bundle, a freight line or a mistyped RRP, and re-pricing a product *above*
  its list because of one is not a forecast anyone would stand behind.
- The day average weights every day alike. The folder has no daily volume
  forecast, and inventing one would bury a price estimate inside a demand
  estimate.

## The page

`REPRICE_<MONTH>.html` puts the two prices on the month that actually
happened:

```
as planned   actual amount - GSCM price x units sold
re-priced    actual amount - re-priced  x units sold
```

Same units, same materials, same months. The only thing that moves is the
price the month is measured against, so the difference between the two is
what a better forecast would have been worth.

Three tiles - the negative price impact as planned, the same re-priced, and
the difference - then the division tree and the materials where the re-price
is worth the most. A division's price is its materials' prices over the units
**actually sold**, so both impacts are on the same mix and differ only by the
price.

Actuals are the **order base**: every line placed in the month, rejections
out, returns and credits out. Nothing here changes what was sold - it is a
measurement of the plan, not of the month.

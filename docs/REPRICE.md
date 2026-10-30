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

## Where it shows

On the P&L page's **Actual vs plan price** card, as a third column group
beside the plan's own. Every figure already on that card stays exactly as it
was - the actuals, the GSCM plan, the diff and the price impact - and the
re-price is added next to them:

| column | what it is |
| --- | --- |
| Price | the re-priced price over the units actually sold |
| Price impact | actual amount less re-priced price x units |
| Better by | what the re-price would have taken off the gap |

A fourth tile carries the same pair: the negative price impact under the
re-price, and how it compares with the plan's.

**Nothing here assumes the re-price is the better number.** It is another
logic run over the same month, and whether it lands closer is the point of
running it. The comparison column is green where the gap closes and red where
it widens, and if this logic reads worse than the GSCM plan then that is the
answer and the plan keeps its number.

Same units, same materials, same month, same Order/Payment base, same
currency. The only thing that moves is the price the month is measured
against, so the difference between the two impacts is exactly what a better
forecast would have been worth - and the card's own numbers never move.

It rides on the existing card rather than a page of its own on purpose. A
second page would have had to pick its own basis for the actuals, and two
pages quoting two different totals for the same question is worse than no
second page at all.

`--no-reprice` leaves it off; it reads six months of order exports, which is
most of what it costs. `--reprice-back N` changes how far back it looks.

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

## The ladder

One product, one month, in this order:

| | what is used | written as |
| --- | --- | --- |
| 1 | this SKU's own discount off RRP **the last time this same promotion ran** | `rrp` |
| 2 | no such promotion in its history: this SKU's **own six-month** discount | `rrp` |
| 3 | no list price to discount: this SKU's **own six-month ASP** | `asp` |
| 4 | nothing of its own at all - a **new SKU** | `new` |
| 5 | not even a neighbour to lean on | `kept` |

Steps 1 and 2 are walked a day at a time, because October's plan puts
different promotions on different days: a product on Boost Week for nine days
is not the same price as one on it for all thirty-one.

Step 2 is the one worth naming. A product's own behaviour under a different
promotion is a better guide to its price than another product's behaviour
under this one, so the fallback goes sideways to the same SKU and not
outward to its neighbours. `--scope` puts the outward rungs back.

### New SKUs

A code the window has never seen has no discount and no ASP of its own.
Rather than quietly keep the number the sheet already had, it is marked
`new`, the nearest product is **named on the row**, and the price comes off
that: the neighbour's own discount applied to this product's list price,
or the neighbour's ASP where there is no list price.

Nearest means the same product group first and the same division after - a
kettle is no guide to a fridge - and among those, the product whose code runs
alongside it longest and whose list price is nearest. Codes carry their own
family: `SM-S948BZKAATS` and `SM-S948BZVAATS` are one phone in two colours,
priced alike because they are the same thing, and the shared prefix finds
that where a division cannot.

A new SKU priced off a neighbour is a judgement. It is on the row so it can
be overruled one line at a time rather than buried in a log.

## The knobs

They exist because the first real simulation improved most of the book -
deviation 288 to 225 - and made two parts of it worse, in two different ways.
One of them has since been answered and is now the default; the other is a
flag that stays off until there is a measurement for it.

### `--scope {sku,div3,div1,all}` - borrowing from a group

**Default `sku`: no borrowing at all.** A product that has never run this
promotion uses its own six-month discount rather than another product's
behaviour under a promotion it did run. `div3`, `div1` and `all` put the
group rungs back, between step 1 and step 2 of the ladder above.

Borrowing was doing measurable harm. REF came back scattered where the GSCM
sheet had been tight - deviations of 39, 67 and 38 going to 78, 125 and 111 -
and TMF's collapsed to 0.06, which is not a model fitting but every product
in a group sharing one borrowed number. `all` was the worst of it: a fridge's
own list price times what televisions and phones came off theirs.

Which rung a given miss sat on is in `docs/spread_<month>.csv` under
`Borrowed from`.

That rung is a likely source of **scatter inside a category that the plan had
priced tightly**. The symptom is a deviation that gets *worse* where the GSCM
number was consistent, and its fingerprint is a group whose deviation
collapses to near nought - every model in it sharing one borrowed discount is
not a model fitting well, it is a model with no per-product information in it
at all.

Capping the ladder does not invent a replacement. Past the cap a product falls
to its own six-month ASP, and failing that keeps the price the sheet already
had. Both say less than a borrowed discount, and neither makes anything up.

### `--decay MONTHS` - how much the recent months count for

**Default 0**, every month in the window counting alike. This one is off
until there is a measurement behind it: the reasoning below is sound and the
category it is aimed at has not yet been confirmed to miss for that reason
rather than another.

At nought every month in the window counts alike. Set, a line `MONTHS` old
counts half as much as one from last month, and one twice that age a quarter.

A flat window is wrong for anything that **discounts deeper as it ages** -
tablets and handsets do. The early, shallow months pull the average discount
up, the predicted price with it, and the month then sells below a price that
was never going to hold. The symptom is a systematic over-prediction: the sum
of the differences moving further from nought in one direction, not scattering.

The weighting moves what is averaged, never what is counted. The `MIN_UNITS`
gate stays on the raw quantity, so a thin history cannot be made to look
sufficient by weighting it.

```
same product, same campaign, 100 units at 10% off in April
                             100 units at 30% off in September

  --decay 0     20.0% off     a flat average of the two
  --decay 5     23.3%
  --decay 2     27.0%
  --decay 1     29.4% off     near enough September alone
```

### Finding out which is biting

`docs/spread_<month>.csv` carries `How` and `Borrowed from` per material
beside the error, so the miss can be cut by the rung that priced it. A
category whose error sits on one rung is a category one flag can fix. See
`docs/PRICE_SPREAD.md`.

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

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

## Where the history comes from

The **DTC export** where the folder has one (`26 DTC Sep.csv` and the like),
and `orders_26XX` otherwise. `--source {auto,dtc,orders}` forces it either
way.

The DTC export carries the list price on the line itself - 99 lines in 100,
against the seven products in ten the promotion plan quotes an RRP for - and
a discount is what came off a list price, so that coverage is the whole input
to this. It is read across every portal group, because the GSCM plan carries
one price between its `E-STORE` and `E-STORE_B2B` rows and the all-portal
reading lands within 1.4% of it while either half alone is 8-9% out.

The campaign is still read off the plan by date, on both sides. The export's
own `promotion_rule` is the better account of what applied, but October has
not happened yet and has only the plan to be described by; keying one side on
each would join on nothing. `docs/DTC.md` has the rest, including what
changes when the source changes.

## The simple model (the default)

**The promotion first, then the quiet days, then the rest.** One estimate
per product, out of its own record.

```
1  what it fetched UNDER a promotion   x  the share of the month's units
                                          expected on one
2  what it fetched WITHOUT one         x  the rest

   each of the two already mixed to the plan's B2B share, B2B against B2C

3  nudged by  (deals lately - deals over the window)  x  what an
               unplanned deal costs its group
4  nudged by B2B, only where 1 and 2 could not carry it per product
```

### `--quiet-list`, and why it is not the default

The unpromoted part of a month could be priced off **the month's list
price** times the group's ordinary markdown, instead of off what the
product itself fetched on quiet days. It sounds right - a Fold8 fetched
about 2,100 on its quiet days because its quiet days were launch days too,
where October's S.COM price for it is 3,271.82 - and it does not work,
because there is no group whose markdown fits a product like that:

```
  read at its range  (Fold8 Online Exclusive)   45% B2B / 39% B2C off list
  read at its division (Mobile)                 47% B2B / 44% B2C off list
  what October actually took off it on B2C                      9%
```

Its own range **is** its launch, so reading the markdown there reads the
launch again. Widening to the division brings in every older and cheaper
phone, which discounts harder than a flagship does. A group average
markdown is not a premium product's markdown at any level, and the right
tool for a launch is to leave the launch out of the window, which is what
`SPECIAL` does.

So it stays behind `--quiet-list` to compare against. It reads no narrower
than a division when it is used, for the reason above.

### What the quiet side is

What a product fetched on days no campaign covered and what it will fetch
in a month with no campaign are the same thing **only for a product whose
window was ordinary trading**. A Fold8 fetched about 2,300 on its quiet
days because its quiet days were launch days too, and October's S.COM
price for it is 3,271.82.

So the unpromoted part of a month is `the month's list price x (1 - the
**group's** ordinary markdown off list)`, by channel where both channels
answer and re-mixed at the plan's B2B share. The markdown is deliberately
a group figure: a group's ordinary trading discount is steady and is
nobody's launch, while the same number read per product reads that
product's launch again under another name. The list price is October's, so
nothing stale comes forward with it.

The cost is that a product which always sells below its group is now
priced at its group's markdown. `--quiet-asp` restores the old behaviour -
the product's own quiet days - to compare against.

### Why the promotion goes first

A blended ASP is one number for two different trades. A Fold8 sold its
whole window under a pre-order at 47% off and sells October at 9% off; its
blended ASP carries the pre-order forward and comes out 20% light. The
quiet side of the same window says what it fetches when nothing is running,
which is what October is.

So the month being priced is answered in its own terms: the days it is
promoted out of what the product fetched promoted, and the days it is not
out of what it fetched quiet. Where it runs no promotion at all, the quiet
side is the whole of the answer and the launch never enters.

Days become units before they weight anything - a promoted day shifts two
to three times a quiet one, so nine days of promotion is nearer a fifth of
a month's units than a third. The factor is units per promoted day over
units per quiet day, the product's own where it has the days and its
group's where it does not, clamped to 0.8-3.0.

### B2B is inside it, not after it

Each of the two sides is asked **by channel** where both channels answer,
and re-mixed at the share of the month's units the plan puts through B2B.

This is the only place a channel shift can be caught per product. The B2B
half of a window is EPP-priced - a standing welcome voucher, an e-promoter
code, an EPP campaign - and the consumer half is not. The same Fold8 sold
at 3,271.82 flat on S.COM and at 2,280-2,617 through EDU and the partner
portals, and the promotion rules on its S.COM lines are PWP text that move
the price not at all. Its price is set by its channel, and no campaign term
can see that.

Where one channel is too thin to answer, that side falls back to its
combined figure and the group-level B2B nudge does what it can afterwards,
as before.

### When neither side is its own

A product without MIN_UNITS on a side in MIN_MONTHS of months cannot be
split. It falls back to the blended ASP with the group's campaign rate
correcting it - (the month's promotion days - its **own** past days, both
as unit shares) x what a campaign is worth to its group - which is what
every product used before.

`--explain` says how many took which path: `own base` is the share priced
off its own promoted and quiet days, `by chan` the share of those mixed
B2B against B2C.

### One month is one vote

**A product sells most when it is cheapest.** An ASP pooled over a window -
all its revenue over all its units - is therefore weighted towards its own
cheap months, while the thing being predicted is not a unit but a *month*.
So the window over-states the discount, and it over-states it the same way
every time: the backtest puts a flat pooled window **4.2 points deep per
product**, never the other way.

The months say it plainly. The big months are big because they discount:

```
  Feb 58k units 46.3% off     Jan 15k units 38.8% off
  Mar 67k units 46.1%         Sep 21k units 38.3%
  Aug 43k units 44.1%         Oct 19k units 39.8%
```

So every month-level figure the window gives up - a product's ASP, and the
rate at which its group ran vouchers and trade-ins - is the **average of
the monthly figures**, one month one vote, not the pooled total.

This is also why `--decay` looks like the fix and is not. The bias is
selection, not age. Shortening the window drops whichever heavy months
happen to sit at the back, which works for a quiet month like October -
the fit puts the best half-life near 0.25 - and reverses for a loud one
like November, so the half-life would have to be re-fitted every month.
That is a parameter, not a model. One month one vote needs no fitting and
holds whichever month is being priced. `--pooled-asp` restores the old
behaviour for comparison.

A month under `MIN_UNITS` gets no vote - averaging a month of three units
beside a month of three hundred trades a bias for a variance - and a
product without **three** such months keeps the pooled figure. Two numbers
are not an average: at a two-month bar, MX's level came in hard (HHP's gap
to actual fell from +4,827 to +1,881) while its scatter went the other way
(155 to 197), which is a colour variant selling eight a month clearing the
bar twice in six and the mean of those two carrying more noise than the
bias it removed.

### Reading a run against another one

`--blank-kept` leaves a `kept` row empty rather than carrying the sheet's
own price. That is right for a simulation, where a blank cannot be mistaken
for a forecast, and **wrong for a pivot that subtracts**: `Actual - New`
with `New` blank is the whole of `Actual`, so a dozen blank rows read as a
dozen enormous misses. On one run twelve blank tablets alone carried a
39,473 gap and a 648 deviation, and took the book's from 127 to 248.

So score with it off, and compare only runs that had it set the same way.

### Vouchers, trade-ins and e-promoter codes

They are the biggest single thing between MX's list price and what was
paid:

```
  MX, October       units   off list
  clean             5,409      31.7%
  voucher           5,336      40.0%
  trade-in            264      43.7%
  both                610      49.4%
```

54% of MX's units carried a voucher - SECRETGALAXY, GALAXYBOOST, EARLYBF.
No plan carries any of them; they are standing offers.

**None of it leaks.** All of it is already inside `AUD Revenue excl. GST`,
so the window ASP carries it at whatever rate that window ran, and the
re-price carries it forward. What does not carry is the **rate**, which
swings hard month to month. That is what the deals nudge is: the newest
month's penetration against the window's, times what a deal costs. On
October it is the largest term on MX - Mobile -1.4pp, Accessories -1.7pp,
Tablet -2.4pp, each of them raising the price.

### Why the campaign rate stays on the plan's terms

The export carries `promotion_rule` - the rule that actually applied - and
it is a far better classifier than the plan. The plan assigns a campaign to
a product for whole stretches at a time, so a product rarely has both
states inside a month and the rate can almost never be measured on the
product itself. Measured within each product on October, the plan gives a
comparison for **one** TV, **nought** washers and **one** fridge; the rule
gives 45, 6 and 11. The plan's rate therefore always comes from a group,
where it picks up the group's product mix: pooled, REF's plan rate reads
24.4pp where the same products measured individually read 1.0pp.

It is still not used, and not because of leakage - the rate would be read
off the window, not off the month being priced. It is because **the
coverage it multiplies comes from the plan**. A month that has not happened
has only its plan, so October's coverage is the plan's days; pairing that
with a rate defined by what rules actually fired pairs two different
definitions, which is the same mistake as days against units, the sheet's
B2B against the export's, or a unit against a month. Where the plan drives
one side it has to define both.

What that costs is known and small. TV's coverage runs 16 points above its
history and the honest within-product rate is about 5.5pp, which is a 1.4%
move where TV needs 5.9%. TV's gap is not a coverage story: October was its
deepest month in seven - 44.1% against 39.4-41.3% for May to September -
and nothing in the window foretells a Black Friday ramp.

### A campaign the month is not running comes out of the window

Some campaigns are not ordinary trading, and `--campaigns` on the real
window shows them as the deep ones:

```
  Accessories   APS Clearance            56.9%   against 33.3% nationwide
                Accessories Clearance    50.6%
  TV            Clearance                51.0%   against 40.6% nationwide
  REF           Early EOFY               46.5%   against 38.2% Samsung Week
  Wearable      SECRET SALE              54.8%
```

A window that averages one of those in carries it forward into a month that
is not running it - which is most of REF's gap, because REF's May and June
sold 1,237 and 1,172 units under Early EOFY at 46.5% and 46.9% and October
has no EOFY at all.

So **where the month being priced is not running one, a product's past
ones come out of the window**, from its ASP and from the campaign rate
both.

A launch belongs with them and one product showed why. A Fold8's whole
window is its pre-order: Jul 2,053, Aug 2,032 and Sep 2,331 on 149, 120 and
26 units, against 2,756 in October. Splitting that window by promotion
could not reach it - its promoted side came out at 2,048 against 2,114
quiet, three per cent apart and both of them launch prices - because the
pre-order bonuses were on the quiet days too, and its B2C side sold at
about 2,300 where October's S.COM price is 3,271.82. A launch happens once.

They are matched **by kind** - `clearance`, `secret`, `eofy`, `launch`,
`pre-order` - so a month running a Secret Sale keeps a product's past
Secret Sales and still drops its past EOFY, and a product on Tab S12 Launch
in October keeps its own launch months. October runs a Secret Sale for 19 of its 678 materials and
nothing else of the three, so every product's EOFY and clearance comes out
and 659 of them lose their secret sales too.

The days go with the sales. A day whose sales were dropped is not a day the
product traded, or its coverage would count a stretch the discount tally
never saw - the same pairing the rest of the model keeps.

`secret` is a judgement rather than a certainty; a Secret Sale is not only
old stock. But its discounts sit with the clearances and not with the
trading weeks, and `SPECIAL` is one list in one place to change.
`--keep-clearance` leaves all three in, as before.

### `--campaigns` - telling a clearance from a sale

```
py tools\reprice.py --campaigns
py tools\reprice.py --campaigns div1
```

The model reduces a campaign to **on or off**, which is all a forecast can
use: the month being priced is a calendar and not a sale. The window knows
more than that, and where a group is on promotion every day of every month
the flag says nothing at all.

So this breaks the window open by campaign **name**, with two numbers each:
what came off the list, and **what share of the campaign's units were
products in their last two live months**.

```
    group      units  off list  run-out  campaign
    TV         1,204     52.1%      61%  <a campaign>
               3,880     44.0%       3%  <another>
```

A campaign that is deep **and** full of products on their way out is a
run-out. A campaign that is deep and full of products still selling is a
trading promotion. The on-or-off flag reads the two the same, and the pair
of numbers separates them - which is what makes it possible to say which
of a group's campaigns were clearing stock and roughly what that cost.

`py tools\dtc.py --aging` answers the same question from the other side,
without the plan: it takes the products that stopped selling and compares
their last two months against their own months before.

### REF, and what the plan cannot say

REF reads low in every run - about 4 to 6% under what it sold for - while
everything else reads a little high. The cause is not in the model.

```
  the plan's campaign coverage, by month
            Apr   May   Jun   Jul   Aug   Sep   Oct
  REF       61%  100%  100%   64%  100%  100%  100%
  TV        73%   97%   90%   35%   61%   97%  100%

  what the month actually discounted
  REF     41.3% 46.2% 46.6% 40.7% 37.2% 39.1% 39.5%
  TV      47.0% 39.4% 40.9% 40.0% 39.5% 41.3% 44.1%
```

A fridge is under a campaign **every day of almost every month**, so its
coverage is saturated and carries no signal - and underneath that flat
100% its discount still swings 9.4 points, from 37.2% to 46.6%. October's
coverage is 100% and its past is 100%, so the campaign term is nought and
every penny of the price comes from the ASP, which is averaging a May and
a June that ran four to five points deeper than October did. That is
2.35pp over the window, and over the room about 4% - which is REF's gap.

So the model cannot see what made May and June deep. Whatever it was - an
end-of-financial-year run-out on big-ticket appliances is the obvious
candidate - the plan does not distinguish it from any other day REF spends
on promotion, because REF spends every day on promotion. TV, whose
coverage runs from 35% to 100%, has a term that can at least try.

Closing it needs an input the files do not carry, not a different
calculation.

### B2B is measured plan against plan

What the B2B side costs comes from the history, which is the only place a
realised discount lives. What it is measured **against** comes from the
plan, because the sheet's B2B share is an *allocation* and the export's is a
*realisation*, and subtracting one from the other reads a shift where there
is none.

Over the whole book the two agree - October planned 39% B2B and sold 40%.
By division they do not:

```
  category        plan B2B   actual B2B    gap
  REF                  41%          29%   +13pp
  Air Purifier         18%           6%   +12pp
  WM                   40%          31%    +9pp
  TV                   45%          38%    +7pp
  Tablet               40%          54%   -14pp
  whole book           39%          40%    -1pp
```

So the nudge was charging REF for a twelve-point swing to a deeper-discounted
channel that never happened. Against its own plan-side group the same rows
read nearly flat: REF's B2B term falls from +2.4pp to +0.4pp and its price
rises 2.8%. Most divisions collapse to about nought, which is the honest
answer - the plan's B2B split carries no reliable per-division signal, only
a within-group one, and that is now all it is asked for.

### `--why` - one material, every step

```
py tools\reprice.py --why SM-F971BZGHATS
py tools\reprice.py --why RF71DB9956QDSA LS49DG950SEXXY
```

A pivot says a product came out wrong. It cannot say which of four numbers
did it, and the row's own `Why` text is a sentence rather than a sum. This
prints the lot:

```
  SM-F971BZGHATS
        month   units        ASP   vote
       202607      13      2,149   yes
       202608      13      2,204   yes
       202609      13      2,783   yes
                           2,379   <- the average of 3 month(s), one vote each
    promotion   0% of the month's days = 0% of its units at 1.36x
                against 22% over its past, at 4.5pp a campaign  ->  -0.99pp
    deals       31% of units lately against 31%                 ->  +0.00pp
    B2B         43% planned against 40% planned for its group   ->  +0.40pp
                                                                 ---------
                                                                   -0.59pp
    price       2,379 x (1 - -0.59 / 66.1) = 2,400
    the sheet says 3,221; 7 unit(s) planned
```

The months come first because that is usually where a bad price is made -
a product with two voting months and a third that swung, or a month that
missed its vote for want of units.

**The sheet is one row per material per account**, so a pivot summing
E-STORE and E-STORE_B2B shows twice the figures this prints.

### `--explain` - which term did it

```
py tools\reprice.py --explain
```

A month that comes out wrong by a **level** for a whole division is one term
firing too hard, and a price is the sum of four things with no reading them
back out of the total. So the terms are kept apart on the way through and
averaged per division, in points of discount, beside the price move they
come to. It is how both of the errors above were found, and it is the first
thing to run when a division looks wrong.

### The other two

Each is a difference too, so **neither fires where the two sides agree**.
Being group-level they move a whole group together and add no per-product
scatter.

The deals ratio is for the discounts no plan will ever carry: a voucher, a
trade-in, an e-promoter code. They are standing offers, not campaigns, so
nothing forecasts them; what can be done is to notice that a group has been
running them harder lately than its window average and move the price by
the difference.

### Days become units

A promotion is not worth its share of the calendar; it is worth what it
sells, and a promoted day shifts two to three times a quiet one. So nine
days of promotion in a month is nearer a fifth of its units than a third,
and it is the unit share the discount has to be applied to.

The factor is units per promoted day over units per quiet day, measured for
the product itself where it has the days and its group's where it does not,
clamped to 0.8-3.0. **Both sides of the nudge pass through the same
factor**, which is what keeps the term at nought where the month's calendar
matches its past - whatever the factor is, and whether or not it had to be
clamped. Where it cannot be measured at all the factor is one and the nudge
is back to counting days, which is the honest fallback.

`--explain` prints the conversion: `plan days` is the month's calendar,
`as units` is the same after selling strength, and `its past` is the
window on the same footing.

The nudge counts **days on both sides** before that conversion. October has not happened,
so its calendar is all there is to count; and a campaign sells about two
and a half times an ordinary day, so its share of a window's units runs far
above its share of the days. Comparing the one against the other reads a
difference where there is none - on one run, October's 40% of days against
the window's 57% of units, a spurious 17 points that lifted every price
about 1.4%.

A change in discount becomes a change in price only after dividing by what
was left of the list price to begin with - two points off a product already
half off is twice the move it is on one at list.

A product with no six-month ASP of its own is left at the GSCM price and
counted as `kept`. The run says how many, and the row carries its own
arithmetic:

```
61% of days on promotion is 83% of the units at 3.0x (SM-F776BLGEATS):
1,110 on it, 1,270 off it; 40% B2B planned against 36%: +0.3pp; unplanned
deals on 74% of units lately against 74%: +0.0pp
```

A product that could not be split names the group whose coverage gap stood
in for it instead:

```
100% of days on promotion against 61% (TV): +9.8pp; 46% B2B planned
against 79%: -1.0pp; unplanned deals on 31% of units lately against 27%
```

`--model campaign` is the older per-product per-campaign discount off RRP,
with the borrowing ladder below. It is kept because it is what every
measurement so far was taken against.

## The ladder (the `campaign` model)

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

**A day is weighted by how hard it sells, not by being a day.** A three-day
promotion is not three thirty-firsts of a month - people wait for the sale.
How much harder each campaign sells is measured from the history, as units
per product-day under the campaign over units per product-day with no
campaign on:

```
    8,218 units  18,699 product-days   1.00x  (no campaign)
    4,019 units   4,033 product-days   2.27x  Samsung Week
    1,361 units     477 product-days   5.00x  Samsung Boost Week | October
      722 units     334 product-days   4.92x  Tab S12 Launch
```

A day that sells twice as hard carries twice as much of the month's price.
The ratio is read at the narrowest scope with at least three product-days on
both sides - the material, its group, its division, the whole book - and is
clamped to between 0.2x and 5x, because a campaign that ran over one freak
weekend should move a month's price and not define it.

It only changes a price where the discount actually differs between those
days. Where a product has one discount across the whole month, re-weighting
the days leaves it exactly where it was.

`--flat-days` goes back to counting every day alike. The calendar average
prices a month as though nobody waited for the sale: on October, promotion
days were 51.1% of the calendar and carried 56.6% of the units.

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

## The B2B mix

The sheet plans each material **twice** - once for `E-STORE`, once for
`E-STORE_B2B` - at one shared price, and the split of the units between them
is the only place the plan says how much of the month is expected to go out
at the deeper B2B discount. On October that is 38.2% of the planned units
overall, and anywhere from 0% to 50% on a given material.

B2B really is cheaper. Measured on the DTC export's own `Distribution`
column:

```
  div           B2C off  B2B off     gap  B2B share
  MX              36.2%    40.9%   +4.7%      41.4%
  TV & SD         42.1%    46.7%   +4.6%      31.4%
  DA              39.4%    41.4%   +2.0%      25.4%
  Monitor         36.9%    42.7%   +5.9%      27.6%
  ALL             38.1%    42.4%   +4.3%      36.5%
```

**It stays one price.** The sheet quotes one price per material across both
accounts and so does this. What moves is how much of the B2B discount is
carried in that one price.

The adjustment is a **difference, not a bonus**, and that is the part worth
being clear about. The blended discount the history gives already contains
B2B at whatever share the history happened to have. Adding the B2B gap on
top of it would count that side twice. So what is applied is

```
shift = (the plan's B2B share  -  the history's B2B share) x the gap
```

read at the narrowest scope with enough units on both sides - the material,
then its group, its division, the whole book - and the row says so:
`-1.3pp for a 40% B2B plan`.

Which means it cuts both ways, and on the real data it mostly cuts down. A
tablet sells heavily into education and government, so its own history can be
70% B2B while the plan expects 40%; correcting it to the plan's mix takes
discount **off**. On one month's run 168 materials gained discount and 222
lost it, the net being -0.47 points. Where a material's plan and history
agree on the mix, nothing moves at all.

It reaches every price built on a discount - the `rrp` rows and the `new`
ones, whose neighbour's discount is at the neighbour's own mix and needs the
same correction. `asp` and `kept` rows are not built on a discount and are
left alone. `--no-mix` turns it off.

## The knobs

They exist because the first real simulation improved most of the book -
deviation 288 to 225 - and made two parts of it worse, in two different ways.
One of them has since been answered and is now the default; the other is a
flag that stays off until there is a measurement for it.

### `--scope {sku,range,div3,div1,all}` - borrowing from a group

**Default `range`: the model family.** One phone's colours and capacities,
named by the DTC export's own `Product Range`. `sku` refuses to borrow at
all; `div3` and wider are too coarse.

The range exists because **a thin product's own record is a noisy estimate
of its own price**, and Mobile is where that bites. On October, 42% of MX's
products sold fewer than five units - the highest of any division - and how
far a product sits from its own family depends on how much it sold:

```
  units sold    products   sd of the gap to its range
  1-4                249                       9.6pp
  5-19               194                       5.4pp
  20-99              120                       4.8pp
  100+                26                       2.3pp
```

A product that sold a hundred sits within two points of its family, so the
family is a good answer for one that sold three. Before this, such a product
fell past `sku` to a **single nearest neighbour** - one product's record
standing in for another's - or to a division. Turning `range` on moved 99
products from that guess to a family average, and 95 of them were MX.

`--min-units` is the other half of the same question: how noisy an estimate
is allowed to be before the family answers instead.

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

### `--new-cap PCT` - what a launch may inherit

**Default 0, no cap.** The product a new SKU most resembles is usually the
one it replaces, and that product is at the end of its life and at its
deepest discount. `SM-S947BZKAATS` priced off `SMS947BZKEATS` at 42% off
list is a new phone priced as a run-out.

`--new-cap 25` holds an inherited discount to a quarter off, and the row says
so: `nearest X at 42.0% off list, capped to 25.0%`. It is off by default
because how much of this is real is a measurement rather than a guess -
`price_spread` breaks the error out by `how`, and the `new` row is where a
launch inheriting a run-out would show as a large one-sided figure.

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

### The plan under-describes what actually ran

Worth knowing before reading any of this. Comparing the plan's
campaign-by-date against the rule each October DTC line actually carried:

```
  8,018  44.5%  plan: campaign     line: rule
  5,145  28.6%  plan: none         line: rule
  2,464  13.7%  plan: none         line: no rule
  1,845  10.2%  plan: campaign     line: no rule
```

Four lines in ten are keyed differently from what happened, and the 28.6% is
the interesting part: those were discounted under a rule the plan's DTC
campaign columns do not carry - EPP vouchers and the like - so they file
under "no campaign". The bucket that is supposed to mean *off promotion* is
mostly not:

```
MX    plan: campaign                4,990 units   40.1% off list
MX    plan: none, line HAS rule     4,543 units   37.9%
MX    plan: none, line NO rule      1,389 units   25.7%
CE    plan: none, line HAS rule     1,288 units   41.5%
CE    plan: none, line NO rule      1,363 units   22.1%
```

This is self-consistent as long as the month being priced is mixed the same
way as the history - the same bucket is read and applied - so it is not on
its own a bias. It stops being self-consistent as soon as the two months
differ in how much unplanned promotion they carry, and it means the figure
is not what its name says.

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

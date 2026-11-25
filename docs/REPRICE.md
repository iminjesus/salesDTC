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
| the list price | the promotion plan's `RRP` column, **over the same six months as everything else** |
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

### Which month, and which sheet prices it

The folder holds a GSCM sheet a month - `GSCM_Oct` beside `GSCM_Nov` - and a
promotion plan per division that is **cumulative**: `MX_promo_2611` carries
every line since 2025, not just November's.

| | how it is chosen |
| --- | --- |
| the promotion plan | the newest cut per division, one file each - `MX_promo_2611` over `MX_promo_2610`. Cumulative, so the newest is the whole history |
| the GSCM sheet | **the one that prices the month asked for**, found by walking the series |
| the month, with no `--month` | the **newest** month any of those sheets carries |

```
py tools\reprice.py                 # November, off GSCM_Nov
py tools\reprice.py --month 2610    # October, off GSCM_Oct, same plan files
```

Both months read the same cumulative plan, so re-running October after a new
plan arrives needs nothing but `--month 2610`.

> Two things here were wrong while the folder held one sheet of one month,
> and only showed up once it held two. The sheet was whichever the name
> turned up first, and the run died on its missing column rather than
> looking at the next one. The month was `have[0]`, the **lowest** month
> number in it - October on a sheet of Oct, Nov and Dec, which is the month
> least likely to be the one wanted. It is the newest now.

Because the plan is cumulative, the six-month window on the list price below
is doing much more work than it was: a 2025 line is in the file and its
price was in force a year ago.

### The list price is a six-month figure too

A product is planned many times over, so the list price is the **commonest**
value among its plan lines rather than the first one found - one mistyped
cell should not become the price. That vote used to run over **every line
the plan files hold**, whatever year it was written in, while everything
else in the model was read over the last six months (`--back`).

On a product that has had one price change, that is the wrong answer by
construction: three old lines outvote two current ones and the discount is
measured off a price that is no longer in force.

```
lines:  Nov 2,599   Jan 2,599   Mar 2,599   Aug 2,499   Oct 2,499
vote over every line        ->  2,599     (not in force since March)
vote over the last 6 months ->  2,499
```

The vote is now held to the lines whose window reaches into the history
window. **An undated line is kept either way** - undated is not old, it is
unsaid, and plans that carry no window at all would otherwise lose every
price. Where the window leaves a product nothing, the whole file answers
rather than the product losing its list price.

The run says how many materials this moves:

```
  the list price is read over May onwards, like the rest: 214 of 3,908
  material(s) take a different one from the vote over every line the plan
  files hold
```

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

## Scoring a run

**`price_spread.py --compare` is the way to do it.** It scores several
models over one month and prints one table - a line a group, a pair of
columns a model:

```
py tools\price_spread.py --month 2610 --by div1 --compare rrp simple
```

```
                                   GSCM             rrp          simple
div1              units    mean      sd    mean      sd    mean      sd
TABLET            7,918     -90     115     -14      97    +108     146
VD                7,674     -55     130      +3     103     +40     149
HHP               7,042     -45     171     -10      87     +63     156
HA                6,188     -16     139     -36     105     +93     134
-----------------------------------------------------------------------
all              28,822     -54     142     -13      99     +76     149
```

**Read the sd.** A model whose mean is nearer nought has the level right; a
model whose sd is lower has the *shape* right, and a level can be moved
afterwards while a shape cannot.

The month is read once and re-priced once per model, so comparing three
models costs three re-prices and one read of the order export, not three of
each.

Every figure in that table is a **group** aggregate - a division, a Div 2,
never a material and never a customer - so it carries none of the month's
data and can be pasted into a mail or a chat as it stands. Where the
rawdata cannot leave the machine it was built on, this table is the whole
of what has to travel.

### Doing it in a pivot instead

Two things wreck a pivot before the model is in question.

**A material that sold nothing.** The sheet plans and prices materials that
October never sold, and `Actual - New` for one of those is the whole of
`New`: one tablet at nought against 2,506, a monitor at nought against
2,967. Thirty-odd of them carry most of a book's apparent error and
dominate its deviation. **Filter the pivot to `Actual > 0`**, or the number
is about the sheet's coverage and not about any price.

**`--blank-kept`.** It leaves a `kept` row empty rather than carrying the
sheet's own price, which is right for a simulation and wrong for a pivot
that subtracts, for the same reason. Compare only runs that had it set the
same way.

## The simple model (the default)

**The promotion first, the quiet days second.** One estimate per product,
out of its own record.

```
1  what it fetched UNDER a promotion   x  the share of the month's units
                                          expected on one
2  what it fetched WITHOUT one         x  the rest

   each of the two already mixed to the plan's B2B share, B2B against B2C

3  nudged by  (deals lately - deals over the window)  x  what an
               unplanned deal costs its group
4  nudged by B2B, only where 1 and 2 could not carry it per product
```

A month being priced is a calendar of promoted and unpromoted days, and
the product's own record holds both. So each part is answered out of the
part of its past that matches, rather than taking one blended ASP and
nudging it towards the month.

**It is the costlier of the two on October**: 191 against 177 for the
blended ASP with a nudge, over the same rows. `--asp-first` is that older
arrangement, kept to compare against. A product that cannot be split
either way falls back to it regardless.

```
1  what it fetched UNDER a promotion   x  the share of the month's units
                                          expected on one
2  what it fetched WITHOUT one         x  the rest

   each of the two already mixed to the plan's B2B share, B2B against B2C

3  nudged by  (deals lately - deals over the window)  x  what an
               unplanned deal costs its group
4  nudged by B2B, only where 1 and 2 could not carry it per product
```

### `--quiet-list` - the sheet's own price for the quiet days

With `--promo-first`, the unpromoted part of a month can be priced off
**the sheet's own October price** instead of off what the product fetched
on quiet days.

It is there for the product too new to have a past worth averaging. A
Fold8's quiet days were its launch days, so its quiet ASP is 2,114 where
October's S.COM price for it is 3,271.82 and the sheet says 3,221.

**No markdown is read off anybody.** An earlier version took the group's
ordinary markdown off list, and that is wrong in a way worth writing down:
a group's markdown comes from the products that have been selling longest,
so dragging a new model down to it reads their age as its discount. Read
at its own range it came to 45% B2B and 39% B2C off list, which is the
Fold8's own pre-order again; widened to Mobile it came to 47% and 44%,
which is every older and cheaper phone. October took 9% off it.

The sheet needs none of that. It already carries one price per material
across E-STORE and E-STORE_B2B, and over October it landed within 1.4% of
what the portals actually realised - so no channel mix either.

What it costs is the obvious thing: where the month plans no promotion, the
price is the plan's, and the model has nothing to add. That is honest for a
new product and wasteful for an old one, which is why it is a flag.

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

**The bar interacts with the special-campaign filter, and `--min-months`
is there to re-measure it.** Three was better than two when every month of
a window was in it (MX's deviation 145 against 197). Leaving a product's
clearances, EOFY and launches out takes months away, so a product that had
four can be left with two and fall to the pooled figure - which weights
its heaviest month hardest, and a heavy month is heavy because it was
discounting. That is the bias the vote exists to remove. One product
showed it plainly:

```
  202608   91 units   2,052   yes
  202609   26 units   2,331   yes
           2,091  <- under 3 months with a vote, so pooled over units
```

One month one vote would have said 2,192; October sold at 2,756.

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

## The ladder (the `rrp` model, the default)

`price = RRP x (1 - discount)`, a day at a time. One product, one month, in
this order:

| | what is used | the day is priced | written as |
| --- | --- | --- | --- |
| 1 | this SKU's own discount off RRP **the last time this same promotion ran** | list less that | `rrp` |
| 2 | never run it: the **same promotion** at its model family, then Div 3, then Div 1 (`--scope`) | list less that | `rrp` |
| 3 | no group answer either: this SKU's **own six-month ASP** | **at the ASP** | `rrp` |
| 4 | nothing of its own: **the plan's own quoted price for that day** | at that quote | `plan` |
| 5 | a quiet day and no record at all: its group's **ordinary markdown off list** | list less that | `rrp` |
| 6 | no list price in the plan at all | the six-month ASP, whole | `asp` |
| 7 | **no record, no quote, no group** | the GSCM price, left alone | `kept` |

(`--new-from asp` or `rate` puts a nearest-neighbour rung between 4 and 5,
written `new`. Both are off by default; see below.)

**Rung 3 is a price, not a discount**, and that is the difference between it
and what used to be there. The old rung took the product's own six-month
*discount* and applied it to the current list price, so a list price that
had moved since carried straight into the forecast:

```
SIB: six-month ASP 1,650, six-month discount 17.5% off a list of 2,000
     the list price has since moved to 2,400

October runs a campaign nobody has run
  old   2,400 x (1 - 17.5%)  =  1,980     the list rise, inherited
  now   the six-month ASP    =  1,650
```

The promotion rungs stay on the list price, because that is what a promotion
is quoted against; the rung under them is just what the product has been
fetching, and it has no business being re-based on a list price it never
sold at.

### A new product takes the same rungs, in the same order

**The promotion rule is tried first for a launch exactly as for anything
else.** The promotion table carries a new product's list price before it has
sold a thing, and a launch is usually on a campaign its family has run, so
rung 2 answers most of its days. Only a day no promotion rule covers falls
to rung 4.

```
the model it replaces: ASP 1,300, 35% off its 2,000 list
the launch lists at 2,400

October runs Boost Week, which the family has run
  rung 2   2,400 x (1 - 40% the family's Boost Week)  =  1,440   how=rrp
October runs Black Friday, which nobody has run
  rung 4   the nearest product's ASP                  =  1,300   how=new
```

### `--why CODE` on the rrp model

```
py tools\reprice.py --month 2611 --why SM-F971BZWGATS
```

```
  SM-F971BZWGATS
    list price 2,999.00, over the window's plan lines
    0% of the month's days carry a campaign

    the month a day at a time. Every day of it is priced on its own and the
    month is their average, weighted by how hard each sells:
      what was on   what the plan had live that day
      days          how many days of the month that was
      pull          how hard such a day sells against an ordinary one
      priced off    which rung answered. "days like these" means days with the
                    same campaign on, or with nothing on

    what was on              days  pull  priced off                     the day
    nothing on                 30  1.00  this product, days like these  1,650.00   (45.0% off)

    the month is those days averaged by pull -> 1,650.00
    GSCM 1,734.00 -> 1,650.00  (-4.8%)
```

A rung that gives a discount shows the day's price and the discount in
brackets; one that gives a price shows the price alone, and the months
behind it are printed under the table.

The same sentences go in the CSV's `Why`, one per group of days:

```
25 day(s) under Early Black Friday, priced off this product, days like these
5 day(s) with nothing on, priced off this product, days like these
```

> It used to read `Early Black Friday x26 (this product, same promotion)`,
> which needed three things explaining: that `x26` was days, that the
> bracket was where the number came from, and what "same promotion" meant
> on a day with no promotion on it. It meant *days like these*, which is
> what it says now.

> `--why`, `--explain` and `--campaigns` hung off the `simple` branch, so
> they quietly did nothing on the model that is now the default. All three
> run on whichever model was asked for now.

**The reading above is the launch trap, and it is not the rungs' fault.**
November puts no campaign on this Fold8, so rung 1 answers with the
product's own **no-campaign** discount - and every no-campaign day in its
window was a day inside its launch, when the launch price applied whether a
campaign was named or not. 45% off is what it has always sold at, because
it has only ever sold at launch. A product whose whole history is its launch
has no ordinary price to find, on any rung.

### `--offers` - the plan says what the offer was, in words

The plan carries `Offer_Detail` beside the campaign that ran it, and the
re-price has never read it. The model asks the plan only **which campaign**
covered a day and measures the depth from the sales, which works while a
campaign's name is the whole of what it did - and fails on a launch, where
what the product sold at *is* the launch and there is no ordinary price
behind it to average.

The offer in words is the one place the two are written apart: a pre-order
bonus named as such, beside the tier discount that would have applied
anyway.

```
py tools\reprice.py --offers                    the vocabulary
py tools\reprice.py --offers SM-F971BZWGATS      one product's own lines
```

```
  offer                                           lines   SKUs   quoted   a campaign it runs under
  Pre-order bonus: $500 credit + double storage        2      2    16.0%   FF8 Pre-order
  EPP T2 tier - 10% off                                2      2    10.0%   -
  $200 instant discount                                1      1     6.7%   Samsung Week

          from          to   quoted  campaign        offer
    2026-08-01  2026-08-20    16.7%  FF8 Pre-order   Pre-order bonus: $500 credit + double storage
    2026-08-01  2026-10-31    10.0%  -               EPP T2 tier - 10% off
    2026-09-10  2026-09-24     6.7%  Samsung Week    $200 instant discount
```

`quoted` is the plan's own depth - its store price against its list price -
on the lines that carry both. It reads the plan and nothing else: no
history, no pricing, so it is quick.

**What it is for.** If a launch month's lines carry a pre-order offer *and*
a tier offer with separate depths, then the launch part can be added back
to recover an ordinary price, and the window does not have to be thrown
away. If every line of the product's window is the one offer, there is no
ordinary price to recover and `--drop-launch-months` or `kept` is the
honest answer.

The plan's **campaign flag** cannot size it either way: book-wide, a day
the plan calls a campaign is only **1.1 points** deeper than a day it does
not, because the quiet days are under the channel's standing rules at the
same depth.

### `--drop-launch-months` - a launch does not end where the plan stops naming it

A product in its pre-order sells at the pre-order price on the days the plan
calls quiet as well, because the offer covered them. The campaign column says
what was **named**; the launch price was simply the price.

The window already drops a clearance, a secret sale, an EOFY or a launch the
priced month is not running - but only on the days the plan names one, which
leaves the quiet days behind as though the product were trading normally. On
a product whose whole window is its launch, those quiet days are the only
history there is, and they become its ordinary price:

```
SM-F971BZWGATS, November, nothing on, list 2,999

    what was on     days  priced off                     the day
    nothing on        30  this product, days like these  1,650.00   (45.0% off)
```

With the flag, a window month that carried a launch or a pre-order for that
product comes out **whole** - quiet days and all - unless the month being
priced is launching it too, in which case the launch is the thing being
forecast. A product that launched five months ago and has traded normally
since keeps its ordinary months and loses only the launch ones. A product
whose window is nothing but its launch has nothing left, and comes back
`kept` - which is the honest answer, because it has never sold at an
ordinary price.

**Off by default.** Measure it before turning it on:

```
py tools\price_spread.py --month 2611 --by div1 --compare rrp
py tools\price_spread.py --month 2611 --by div1 --compare rrp --drop-launch-months
```

> Two routes to this through the export's own `promotion_rule` were tried
> and both failed, which is why the fix is on the plan side. See
> `docs/DTC.md`: the rule names are identifiers, not a vocabulary - a new
> one is minted per window **and per product code** - so neither the months
> a name appears in nor the window it declares separates a standing offer
> from a campaign. The depths say what the names cannot: EPP's standing
> pricing came back as 54.3, 55.1, 55.2, 55.3, 55.6, 55.8, 56.5 and 57.0
> per cent off across hundreds of separate names.

### `--keep NAME` - where the sheet already wins

**The model earns its place where the sheet is stale, and not everywhere.**
November, by Div 1, unit-weighted deviation of the gap:

```
div1       units   GSCM mean  sd      rrp mean  sd
MX        19,652          -7  78           -61  97
DA         2,539        +272  253          -27  108
VD         5,424        +162  450          -83  435
```

MX's November sheet is set so carefully - a mean of **-7** and a deviation
of 78 over 19,652 units - that there is nothing left in it to find, and
every model tried came out worse. DA's was out by 272 and the model more
than halved its deviation. October said the same thing: MX was the one
division the model made worse, at every level down to Div 3.

`--keep MX` leaves that group's GSCM price alone, written `kept`, and the
rest of the book is re-priced as usual. The name is matched against Biz,
Div 1, Div 2, Div 3 and Range alike, so `--keep REF` works the same way.

**Measure before naming one.** Which groups these are is a reading of
`price_spread --compare`, not a guess, and it is a reading that can change:
a sheet that is good this month is good because somebody set it well, not
because of anything structural.

### `--model quote` - measured and rejected

The idea was that a day whose campaign nobody has a record of should take
the plan's own quote ahead of the product's ordinary-month ASP, Black
Friday being the case: the deepest discounting month of the year, named in
the cumulative plan from 2025, with no sales under it in a six-month window
and no `25 DTC Nov` in the folder to put there.

**It was worse everywhere.** November, deviation of the gap:

```
            rrp    quote
MX           97      107
DA          108      196
VD          435      567
all         212      280
```

So the plan's quoted price is **dearer than what is realised**, by enough
to matter: a voucher, a trade-in and a stacked offer do the work that the
quote does not show, and on Black Friday they do most of it. The rung is
still there below the ASP, where it answers for a product that has no ASP
at all; what is rejected is putting it above one.

`--model quote` is kept so the reading can be repeated on another month.


The two rungs below the realised ones answer the same day two ways, and
**which should go first is a real question that October and November answer
differently**:

| | |
| --- | --- |
| rung 3, the product's **own six-month ASP** | realised, but from ordinary months |
| rung 4, the **plan's own quote** for that campaign | that campaign exactly, but quoted rather than collected |

`--model rrp` puts the ASP first, on the ground that a realised price beats
a quoted one. `--model quote` puts the quote first. Everything else is the
same model.

**November is why.** Black Friday is the deepest discounting month of the
year. The cumulative plan names it from 2025, so the chart knows the
campaign is on - but a six-month window holds no sales under it and the
folder has no `25 DTC Nov` to put there, so rungs 1 and 2 are silent and
the day falls to an **ordinary month's ASP**. The year's cheapest month gets
priced as an average one.

```
the product: ASP 1,800 over six ordinary months, list 2,000
November: Black Friday, quoted at 1,400, no sales history under it

--model rrp     1,800.00   this product, six-month ASP
--model quote   1,400.00   the plan's own price for the day
```

The symptom to look for is a **sign that flips between months**, which is
not a level error and cannot be calibrated away:

```
October   model < actual < sheet      the model came out cheap
November  sheet < actual < model      the model came out dear
```

The actual sits between the two either way. A model built on the six months
before a month is one step behind: it prices a dear month cheap and a cheap
month dear, and the flip is the tell.

### Rung 4: a launch campaign has no past, so the plan answers

**A launch campaign has never run before.** Tab S12 Launch, Galaxy Watch9
Launch, Buds4 Launch - the name is new because the product is, so neither
the product nor its family has a record of it and rungs 1 to 3 are all
silent. That is not a thin history; it is a campaign that cannot have one.

The plan line for that campaign carries **its own price**, in the same row
as the RRP: `S.COM_Price`, `T1_Price`, `T2_Price`, `T3_Price`, `EDU_Price`,
`RRP`. For this product under this campaign that is the best evidence there
is, and the store's own column is the channel being priced. Two live lines
on a day, and the cheaper quote wins - that is the offer a customer would
take.

```
the launch lists at 2,399 and the plan quotes it at 2,159 for the launch
the model it replaces: ASP 1,300, 35% off its own 2,000 list

rung 4  the plan's own quote                       =  2,159   how=plan
rung 5  the neighbour's ASP                        =  1,300
        inheriting the neighbour's 35% off 2,399   =  1,559
```

It is what was **quoted**, not what was collected - a voucher, a trade-in or
a stacked offer moves the two apart - which is why it sits below every rung
that has a realised price and above the two that borrow from another
product. A product with a record of its own never reaches it.

### Rung 7: a product with nothing keeps the sheet's price

**Three ways of leaning on a neighbour were tried and all three lost to
leaving the price alone.** On October's 22 such materials:

| what priced them | sd of the gap |
| --- | --- |
| **the GSCM sheet, untouched** | **244** |
| the neighbour's ASP, flat | 293 |
| the neighbour's ASP at its rate off the sheet | 543 |
| the neighbour's discount off list | worse again |

So the default is `kept`: a product with no record, no quote and no group
answer is one somebody priced deliberately for its launch, and nothing the
history can be made to say beats that. `--new-from asp` and `--new-from
rate` turn the other two back on to be measured again.

Each of them looks sound until it is measured, and the reason each fails is
worth keeping, because the neighbour is nearly always the model being
replaced:

| | and so |
| --- | --- |
| its **discount** | the deeper that model was cut on its way out, the cheaper the launch |
| its **ASP** flat | that model lists lower, so the launch comes out cheap by the whole gap |
| its **rate off the sheet** | the numerator is a six-month ASP and the denominator is an October sheet price. For a model being run out those are two different periods of its life, the ratio runs over 1, and the launch is priced **above** its own sheet |

```
predecessor: six-month ASP 1,400, but October's sheet prices it at 900
this product: sheet 2,100

--new-from sheet    2,100.00   kept
--new-from asp      1,400.00   the whole list-price gap, inherited
--new-from rate     3,266.67   1,400 / 900 = 156%, which is the run-out
```

Scaling the ASP by the **list** price is not a fourth option - it is
algebraically the first one:

```
neighbour ASP x (my list / its list)
  = its list x (1 - d) x my list / its list
  = my list x (1 - d)                         the discount form exactly
```

A period-matched version of the rate - the neighbour's ASP over what the
**window's** sheets planned it at - would avoid the trap, and cannot be
built: the folder keeps one GSCM sheet, for the month being priced.

A month that leans on a neighbour for any of its days is written `new`,
whatever the promotion rungs covered - a launch hidden inside `rrp` is the
one row that most needs to be seen on its own.

Rung 5 is the backstop under rung 2 for a product with no neighbour either:
with `--by-members` a family needs three products that each sold enough to
vote, and a family of two cannot, while its pooled quiet markdown still can.

The B2B shift applies on either shape. It is measured in points off the list
price, so a price rung takes `rrp x shift` off in money - the same money the
discount rungs take off - and the two stay comparable.

`--model simple` is the other model, below. `campaign` is the old name for
`rrp` and still works.

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

**Default `div1`: the model family, then Div 3, then Div 1 - never the whole
book.** The family is one phone's colours and capacities, named by the DTC
export's own `Product Range`, and it is tried first. `sku` refuses to borrow
at all; `all` lets the book answer.

> This flag's help said `div1` and the code did `range`, so only the family
> was ever asked and a product whose family could not answer dropped straight
> past Div 3 and Div 1 to its own ASP. It does what it says now. On a
> **new** product that matters most: the family of a launch is often the
> launch itself.

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

### The CSV, and what the month actually did

```
py tools\reprice.py --month 2610 --out docs\reprice_2610.csv
```

One row a material: the forecast, how it was reached, and **what the month
sold at**, so the pivot can be built without joining two files by hand.

| column | |
| --- | --- |
| `Planned qty`, `GSCM price`, `Re-priced`, `Change %` | the forecast and the sheet it replaces |
| `RRP`, `Promo days`, `From`, `Nearest SKU` | how it was reached, and off which rung |
| `Actual qty`, `Actual amount`, `Actual price` | what the month did, **to date** |
| `Actual - Re-priced`, `Diff %` | the miss the pivot is built on |
| `Actual - GSCM` | the same miss against the sheet, to read the two side by side |
| `Impact` | the miss times the units it was made on |

```
Material  GSCM price  Re-priced   Actual qty  Actual amount  Actual price  Actual-Re-priced  Diff %  Actual-GSCM   Impact
SM-A         1999.00    1750.00          430         779349       1812.44            +62.44    +3.6     -186.56  +26,849
SM-B         3499.00    3120.00
SM-C          899.00     899.00           11           9295        845.00            -54.00    -6.0      -54.00     -594
```

The amount is the export's own money and the price is that over the units,
so a pivot can weight by either without re-deriving one from the other and
rounding twice. **`Impact` is the figure a pivot sums**: a 62 miss on four
hundred units and on four is not the same money, and a column of per-unit
misses added up says nothing about either.

**A material the month never sold has those columns empty, not nought.**
`SM-B` above was planned and not sold, and a nought in `Actual - Re-priced`
for it is `-3,120` - one row carrying the whole of a forecast as if it were
an error. Thirty of those dominate a deviation, which is the single thing
that wrecks a pivot before the model is in question.

The realised price is the month **to date**: the order export stops where it
stops, so a material still selling is a part month read against a whole
month's forecast. It comes from the DTC export where the folder has one and
the order export otherwise - `--source` picks - and the run says which
answered and how many materials carried a price.

`--no-actual` leaves it out. It is another read of the order export, which
is the slow part of a run that only wants the forecast; `dashboard/build_pnl.py`
does not ask for it, so the page build is unchanged.

The file is gitignored (`/docs/reprice_*.csv`) and now carries realised
prices as well, so it stays that way.

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

# The DTC export

```
py tools\dtc.py                      # what the folder has
py tools\dtc.py --month 2610 --top 20
```

Files are found by name - anything with `dtc` in it, so `26 DTC Sep.csv` and
`26_DTC_Sep.csv` are both picked up - and the month is read from each row's
own `Year` and `Month` columns rather than from the file name.

## Why it is preferred

It is the same sale the order export carries, with two things on the line
that the re-price otherwise has to go looking for:

| | |
| --- | --- |
| `AUD RRP` | the list price, on **99%** of lines. The promotion plan quotes one for about seven products in ten, and a discount is what came off a list price - a line without one cannot enter the discount tally at all. |
| `promotion_rule` | the rule that actually applied, rather than the one the plan says covered that day. |

Coverage is the whole input to a re-price, so this is not a convenience.

## What it costs

**No delivery date.** Anything about despatch, lead time, or a month's orders
landing in the next one cannot be answered from it. That is why it does not
simply replace the order export everywhere - the P&L page still reads
`orders_26XX` and the profit exports, which also carry the customer, the
rejection reason and the P&L columns this does not have.

Where it is used: `tools/reprice.py` for the discount history, and
`tools/price_spread.py` for the month as it sold. Both take
`--source {auto,dtc,orders}`; `auto` prefers it where the folder has one.

## What it changes

The two exports do not reconcile, and the difference is not small. Measured
on October against the GSCM plan's own prices, unit-weighted over the 613
materials both sides carry:

```
actual ASP / GSCM price         skus    units   weighted   median
every portal                     613   15,631      0.986    0.980
S.COM only                       558    6,725      1.078    1.050
B2B only                         520    6,204      0.908    0.908
```

Two things follow.

**The plan is a blended price.** The sheet has a row per account - `E-STORE`
and `E-STORE_B2B` - carrying one price between them, and the all-portal
reading lands within 1.4% of it while either half alone is 8-9% out. So the
history is read across every portal group and not narrowed to S.COM, even
though the discount differs by group (S.COM 36.2% off list, the EPP groups
42-43%, Internal 47.2%).

**The month's headline moves.** On the order export's `Net Value (Item)` the
month read about 5.7% *above* the planned price; on this export's `AUD
Revenue excl. GST` it reads about 1.4% *below* it. Same month, same
materials. This export's revenue is the product's - install and delivery are
on their own columns and are not in it - and it is explicitly ex-GST, which
is the basis the GSCM sheet appears to be on. That is the argument for it,
and it is worth knowing before a number from one is read beside a number
from the other.

## `--drift` - does the discount hold still?

```
py tools\dtc.py --drift          # by product category
py tools\dtc.py --drift div
```

The re-price averages a window of months and applies it to the month after.
That is only right where the discount holds still. Where it drifts, a flat
average is wrong in **one direction for a product early in its life and the
other for one late in it** - which reads as two categories failing for two
reasons when it is one reason twice.

The report is the discount off list, month by month, with the widest
month-to-month gap beside it. A category that swings more than a few points
is one a flat six-month average will price wrong in whichever direction it
has drifted, and is the case `--decay` exists for.

```
  div                 Sep      Oct    swing    units
  MX                31.0%    38.3%     7.4%   23,188
  TV & SD           37.5%    44.2%     6.7%    7,188
```

It needs no product master: the export names its own division, category and
range.

## `--fit` - which weighting would have been right

```
py tools\dtc.py --fit
py tools\dtc.py --fit --back 6 --drift div
```

`--drift` shows that the discount moves. `--fit` answers the only question
that settles what to do about it: **which weighting would have got the month
that already happened right.** It takes the newest month in the folder, 
predicts it from the months before it under a flat average and under a range
of half-lives, and reports the error of each.

Measured on October from April to September:

```
  half-life     mean |err| pp   listed-wtd   bias pp
  flat                   3.29         3.15     +2.37
  1 month                2.64         3.33     +2.30
  0.5 month              2.27         2.39     +1.25
  0.35 month             2.16         1.78     +0.64
```

A positive bias means the window predicts more discount than the month gave,
which prices it too cheap. The flat average is biased that way across most of
the book, by over two points of a roughly forty-point discount.

**Read the three columns together, and do not take the last line as the
answer.** The listed-weighted error follows the big groups and keeps falling
as the half-life shortens; the unweighted one turns back up once a half-life
begins over-correcting the small ones. On October the unweighted error
bottoms at 0.5 and the bias crosses nought between 0.5 and 0.35 - past that,
groups that were already predicted a little shallow (Air Purifier, DW,
Tablet) are driven several points the other way. The bias crossing nought is
the better guide, and the sharp bottom of the weighted curve is over-fitting
to one month.

A group selling above its own list price has no discount to read - gift
cards come through at -36% and -82% - and its error dwarfs every real one.
Those are left out of the fit and named, rather than silently dropped.

Pass the half-life to `reprice` as `--decay`.

### Per product, one vote each

The same backtest run over products rather than groups, which is how a sheet
reads it. On October it says something the group table cannot:

```
  half-life     mean |err| pp   median   bias pp  within 3pp
  flat                   7.69     2.98     +4.22         32%
  0.5 month              6.41     1.28     +2.59         39%
  0.25 month             6.03     0.34     +1.56         38%
```

**The median is already solved and the mean is not.** Half the products land
within a third of a point at a short half-life, while the mean sits near six
- so a minority is wrong by a lot, and no half-life fixes a minority. The
share landing within three points stops improving at 39% whatever the
window, which is the same thing said plainly.

So the window is not the lever past about 0.5, and `--tail` breaks down
where the error actually sits: the quartiles, how many products are out by
more than ten points and how many units they carry, which divisions and
which volumes they are, and the worst of them by name.

## `--deals` - what else came off the price

```
py tools\dtc.py --deals
py tools\dtc.py --deals --drift cat
```

A campaign is not the only thing between the list price and what was paid. A
trade-in and a voucher both come off too, and on October they are worth more
than most campaigns:

```
  MX                units   off list
  clean             5,388      31.7%
  voucher           5,332      40.0%
  trade-in            264      43.7%
  both                610      49.4%
```

**None of this leaks.** All of it is already inside `AUD Revenue excl. GST`,
so a discount measured off a month carries it, and the re-price carries it
forward.

What does not carry is the **penetration**. A month read for its discount
carries these at that month's share - on MX nearly half the units had a
voucher - and applying it to a month with a different share is wrong by the
difference, with no campaign having changed at all. The report shows that
share by month, which is the thing to watch.

Affiliates (`rewardsgateway`, `UNIDAYS`, `blc`) move it much less: 35% to 42%
off list on MX against 37.8% for no affiliate at all.

## `--asp` - the scatter the simple model is left with

```
py tools\dtc.py --asp
py tools\dtc.py --asp --back 9
```

The simple model prices a product from its own window ASP and then nudges it
by ratios read for its **group**. A group nudge moves every member alike, so
**it cannot change the scatter inside a group** - whatever deviation is left
within a division is entirely how far each product's newest month sits from
its own past.

This measures that, per division, at several half-lives:

```
  division     products      flat        3m        1m      0.5m     0.25m
  MX                343      4.7%      4.7%      5.2%      6.4%      7.9%
  TV & SD           125      0.7%      0.7%      0.8%      0.9%      1.1%
```

Read which way the row moves, because the two cases want opposite things:

| the row | what it means | what to do |
| --- | --- | --- |
| falls as the half-life shortens | prices **drifted** inside the window, and a flat average is a blend of two prices no month had | shorten `--decay` |
| rises as the half-life shortens | prices are **noisy but steady**, and averaging is what takes the noise out | leave `--decay` at nought, and `--back` further if anything |

Both are fixed with a flag and neither needs the model touched.

## What it drops, and says so

A cancelled line is not a sale, and a line that nets to nothing or less has
no price to read. Both are dropped and both are counted in the run - on
October, 285 cancelled and 1,233 nil out of 19,519, leaving 18,001.

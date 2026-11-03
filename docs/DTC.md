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

It is one month of backtest over a dozen groups, so the sharp bottom of the
curve is not to be trusted to a decimal - the shape is. Pass the half-life to
`reprice` as `--decay`.

## What it drops, and says so

A cancelled line is not a sale, and a line that nets to nothing or less has
no price to read. Both are dropped and both are counted in the run - on
October, 285 cancelled and 1,233 nil out of 19,519, leaving 18,001.

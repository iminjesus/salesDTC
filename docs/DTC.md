# The DTC export

```
py tools\dtc.py                      # what the folder has
py tools\dtc.py --month 2610 --top 20
```

Files are found by name - anything with `dtc` in it, so `26 DTC Sep.csv` and
`26_DTC_Sep.csv` are both picked up - and the month is read from each row's
own `Year` and `Month` columns rather than from the file name.


## `--sku CODE --rules` - one product's own offers

```
py tools\dtc.py --sku SM-F971BZWGATS --rules
```

```
  SM-F971BZWGATS: 5 line(s), 480 unit(s), 46.9% off list over the window
      month    units  off list   rule
     202608      220     50.0%   AU_B2C_WEB_MX_01AUG26_20AUG26_PREORDER_FF8-500OFF
     202608       90     43.3%   AU_EPP_WEB_MX_01AUG26_14AUG26_DISCOUNT_FF8R-50
     202609       70     42.6%   AU_EPP_WEB_MX_01SEP26_14SEP26_DISCOUNT_FF8R-50
     202609       60     49.3%   AU_B2C_WEB_MX_21AUG26_10SEP26_PREORDER_FF8-500OFF
     202610       40     42.1%   AU_EPP_WEB_MX_01OCT26_14OCT26_DISCOUNT_FF8R-50
```

**Classifying the whole file failed three ways**, and `--rules` below records
how. One product at a time is a different question and a much easier one:
what did this material actually sell under, and how deep was each offer?

That is what decides whether a launch discount can be **told apart from the
channel's ordinary one and added back** to recover an ordinary price - which
is the alternative to dropping the launch months from the window
(`reprice --drop-launch-months`). It needs the pre-order lines and the
ordinary lines to come out at visibly different depths. If they do not -
if everything the product ever sold is one depth - there is no ordinary
price to recover and no add-back to size.

The plan's campaign flag cannot size it. Book-wide, a day the plan calls a
campaign is **1.1 points** deeper than a day it does not, because the quiet
days are under the channel's standing rules at the same depth. Whatever
separates a launch offer from an ordinary one is in the rule, not in the
flag.

## `--rules` - standing pricing against a campaign

```
py tools\dtc.py --rules
```

The re-price keys its history on the **plan's** campaign for a date, because
the month being priced has not happened and has only a plan to be described
by. The export knows better: `promotion_rule` is the rule that actually
applied to each line.

A Fold8 whose plan says *no campaign* on half its days still sold those days
under its **pre-order** rule, because the rule covered them. Carried forward
that becomes the product's ordinary price, and the next month is priced at a
launch discount it is not running - which is how `SM-F971BZWGATS` came out at
45% off a 2,999 list in a November with nothing on.

### The name is not the offer

There are eighteen thousand distinct rule names, and almost none of them is
a distinct offer. **The channel re-issues its standing pricing as a new
dated rule every fortnight**:

```
AU_EPP_WEB_MX_26FEB26_24MAR26_PROMOTEXT_50P   26 days   55.8% off
AU_EPP_WEB_MX_26FEB26_10MAR26_PWP_50PCT-MAI   12 days   55.6% off
AU_EPP_WEB_MX_26FEB26_10MAR26_DISCOUNT_THY-   12 days   55.1% off
AU_EPP_WEB_MX_26FEB26_10MAR26_PWP_ACC-50PCT   12 days   57.0% off
```

Same channel, same division, same depth, a new name each time. Two ways of
classifying that both failed on it:

| | and |
| --- | --- |
| how many **months a name** appears in | a new name per window, so 38% of the file read as "one month only" - that measured the naming |
| the **window the name declares** | each instance really is 12 to 36 days, so 74% of the file read as a campaign - the same mistake from the other end |

So the dates come out of the name first, and what is left is the **family**:

```
AU_EPP_WEB_MX_26FEB26_24MAR26_PROMOTEXT_50P  ->  AU_EPP_WEB_MX_PROMOTEXT_50P
AU_B2C_CRP_CE_231103_000000_ALL_CS           ->  AU_B2C_CRP_CE_ALL_CS
25_06_06_BIN_message_cbayello                ->  BIN_message_cbayello
```

A family live in **two thirds of the window or more** is how the channel is
priced, be it one rule or thirty re-issues of one. A family live in a month
or two is a promotion with a start and a finish.

```
  16 rule name(s), 5 once their dates are stripped

  what kind of rule                rules     units  share  off list
  standing                            13    17,401  92.3%     48.2%
  campaign                             3     1,450   7.7%     37.2%

  campaign rules, by mechanic      rules     units  share  off list
  DISCOUNT                             1       900   4.8%     30.0%
  PREORDER                             2       550   2.9%     45.0%

  the biggest campaign families   months     units  off list
  AU_B2C_WEB_ALL_DISCOUNT_EBF           1       900      30.0%
  AU_B2C_WEB_MX_PREORDER_FF8            2       550      45.0%
```

That campaign share is the size of the problem: the lines a six-month
average carries forward as the ordinary price, into a month running none of
them.

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

## `--aging` - what a run-out costs

```
py tools\dtc.py --aging
py tools\dtc.py --aging div
```

A clearance is a product **reaching the end of its life** and being emptied
out before the next model lands. It is not a date in the calendar: an EOFY
sale is a week of the year and every product alive that June is in it, so a
campaign name cannot tell the two apart.

What marks a run-out is that the product **stops**. So this takes the
products that sold through part of the file and then went quiet, and
compares what they fetched in their **last two live months** against what
the same product fetched before that. Same product both sides, so nothing
about the mix leaks in.

A product still selling in the newest month is left out: its last month is
where the file ends, not where the product ended. A month needs 3 units to
count and a product needs four such months, so a run-out has something to
be measured against.

The answer is per product group, as a mean and a median, because one
product cleared at eighty points off would carry a mean on its own.

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

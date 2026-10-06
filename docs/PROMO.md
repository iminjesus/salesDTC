# Which promotion did an order come in on?

```powershell
py tools\promo.py --division MX        # what the promotions look like, in three levels
py tools\promo_match.py --profile      # describe both files, change nothing
py tools\promo_match.py                # attribute, and cross-check the two
```

## Three levels, widest first

The store's codes are unreadable in bulk - hundreds of them, few shared between
months. `tools/promo.py` pulls each one apart into three levels and reports how
far each gathers:

| | |
|---|---|
| **offer type** | the mechanic: PWP, GWP, Discount, Cashback, Bundle, Trade-Up |
| **family** | what the offer *does*: EPP welcome voucher, % off RRP, $ off, Accessories, First 72 hours, Bundle / PWP |
| **offer** | what it was on, with the mechanic taken out - `S25-LAUNCH-10PCT` |
| **rule** | the code itself, dates and all |

**family** exists because **offer** does not gather. On MX it came back with
10,560 distinct values whose eight biggest covered 22% - the same offer is
written several ways (`50PCT`, `50PCTOFF`, `50OFF`, `50 PCT`) and a wave code
is glued on each time it runs (`26F`, `B4F`, `FF8F`, `26R`), which is what turns
one offer into ten thousand. The families are read off `--tokens`, not invented,
and they live in an editable table at the top of `tools/promo.py`. First match
wins, so the order is the precedence.

A cell holding two rules keeps both, and **every level is sorted**: a line
carrying PWP and a discount lands in one bucket however the two were ordered in
the cell. Unsorted, one promotion was counted as two - August's largest,
`QBH8-50-PCT-RRP-FF8F`, came out as 1,997 lines under one ordering and 1,862
under the other when it is a single offer of 3,859 lines and $4.7M, bigger than
any other row in the summary.
Unsorted, `PWP + Discount` and `Discount + PWP` were two answers to one
question, splitting 30% of MX across two rows of the same table.

The code is split on **every non-alphanumeric**, not on whitespace. A code with
no dates - `AU_EPP_T2-T3_all_welcome-voucher_-_percentage-discount` - comes back
from the parser as one unbroken string, so splitting on spaces saw a single word
that is in no vocabulary. That alone put a fifth of MX's promoted units in
"mechanic not in the code"; read properly it is `Discount + Voucher`.

`PROMOTEXT` and the like are dropped, and the parts are deduplicated case-blind,
so `PROMOTEXT X, X` is one offer rather than `PROMOTEXT X + X`.

The run prints, per level, how many distinct values there are and **what the
eight biggest would cover** if a chart stacked by it - a level that gathers
badly is one a chart cannot say much with.

## One promotion, named once

The rule and the plan were shown to be two descriptions of the same offer - 92%
of the lines both answered for - so keying the summary on **which of them
answered** printed that offer twice, once under its rule code and once under its
plan label, as if they were two promotions. They are not.

`promo_summary.csv` is now one row per promotion: the **campaign** it ran in and
the **family** it was, with which source could name it as a column beside it.

```
                                                  Lines     Qty       Amount  named by
  Black Friday    % off                               4      10       29,536  rule 4
  EOFY            EPP surplus                         1       1        4,999  plan 1
```

The family is what makes that possible: both vocabularies land on one table, so
a rule code and a plan line describing the same offer land on the same row. That
table has therefore moved into `tools/promo_match.py`, beside `MECHANIC` and
`EXECUTED_AS` - they are one vocabulary layer, and the cross-check needs it as
much as `promo.py` does.

## A cell's rules are the order's, not the line's

```
AU_B2C_WEB_SP_14AUG26_09SEP26_PWP_FF8-ACCESSORIES-30PCT ,
AU_B2C_WEB_SP_14AUG26_09SEP26_DISCOUNT_H8Q8-ECO-VOUCHER-120OFF
```

Both lines of a Fold8 bought with a case carry **that same pair**, because the
cell holds every rule the order qualified for and an order is more than one
line. But the phone lost $120 and the case lost 30%:

| | RRP | paid | off | which rule |
|---|---|---|---|---|
| `SM-F971BLVDATS` Fold8 | 2,699.00 | 2,579.00 | 120.00 = **4.45%** | the eco voucher |
| `EF-CF976CTEGWW` case | 89.00 | 62.30 | 26.70 = **30.0%** | the accessories PWP |

Read together, the phone was filed under **Accessories offer** - which is not
what happened to it.

The line's own numbers settle it. A rule's text says what it claims to take off
- `30PCT` is a rate, `120OFF` is an amount - and a claim either fits the line or
it does not. Rules claiming nothing cannot miss and are kept; a line with one
rule, or with no numbers to test against, is unchanged; and where **every** rule
misses, nothing is dropped, because turning a line into "no promotion" is worse
than the over-wide reading it would replace.

The run says how many lines were narrowed this way.

## Did the customer pay the price their own channel is quoted?

The plan prices a promotion five times over - `S.COM_Price`, `T1`, `T2`, `T3`,
`EDU` - and the order says which portal it came through. Matching an order to
the **nearest** of those five says only that the price is somewhere in the plan;
it does not say the customer paid the price they were entitled to. So the two
sides are put against each other:

```
the price paid against the channel it came through - 25 line(s) that landed on a named price
  channel                  lines    S.COM      EDU       T2   as quoted
  S.COM/Retail                22       22        0        0        100%
  EPP/Partnership              2        1        0        1         50%
  EPP/EDU                      1        0        1        0        100%
```

An EPP order settling on `S.COM_Price` is either a tier that was not applied or
a portal group mapped wrongly, and both are worth seeing. A dash means the
customer master would not settle that channel, which is **not** a mismatch and
is counted apart from one. Lines that landed on the `RRP` are counted too: a
promotion was live and the list price was paid.

## Does the price belong to the promotion the rule names?

The nearest-price match answers a weaker question than it looks like it answers.
It finds whichever plan line the price fits best, and the rule plays no part in
choosing it - so a line can "match the plan" at a price belonging to a different
offer entirely. The rule says Secret Sale, the customer paid the Stunt Promotion
price, and both are discounts, so the cross-check calls it a match.

Both sides land on one family now, so the stronger question can be asked: of the
plan lines live for this product, is there one of the family the **rule** names,
and is what was paid **its** price?

```
does the price belong to the promotion the rule names? 18 line(s) with both
         3   16.7%  the plan has a line of that family and the price is its price
         0    0.0%  it has one, but what was paid is not within 3% of any of its prices
        15   83.3%  it has no line of that family live for this product at all
```

The middle row is the one to read: the promotion was planned, and the customer
did not pay its price. The bottom row comes with the pairs - what the rule ran
against what the plan priced - which is where a missing plan line or a family
the table still splits in two shows up.

## One campaign, out of three columns

The plan writes a campaign in three places - `Nationwide_Campaign`,
`DTC_Campaign1`, `DTC_Campaign2` - and keeping them as three levels made two
thirds of CE's plan lines look campaign-less when most of them are not: they are
in Samsung Week or Clearance or Tech Fest, which the nationwide column never
holds. The three are read as **one**: nationwide first because it is the widest,
then the DTC columns, with the rest kept on an `Also in` level so a line naming
two can be seen to.

Spellings that differ only by case or punctuation are folded, with the plan's own
commonest spelling as the canonical one - read off the plan rather than from a
table here, so a spelling that becomes the commoner one later is followed without
an edit:

```
  3 campaign name(s) are spelled more than one way and are read as one:
    Boxing Day <- BOXING DAY
    Father's Day <- Father's day
    Mother's Day <- Mother's day
```

Letter typos are left alone. `Samsung Weel` is not `Samsung Week` by any rule
that would not also merge two real campaigns, and `Samsung Boost` is not
`Samsung Boost Week` - those are a decision for whoever owns the plan, and the
run shows them side by side so the decision can be made.

## Did the orders arrive on what was planned?

The question a chart of the orders alone cannot answer, because a campaign that
took no orders leaves no row to chart. So both sides go in one table - the plan
side is what was live in the month and on how many product codes, the order side
is what actually arrived:

```
what the plan said would run in this month, and how it was applied
  campaign                    named by      SKUs  lines    units      revenue     late  plan DC  paid DC
  Father's Day                nationwide     109    543    1,348    2,985,788       0%      22%       6%
  Tech Fest                   DTC1+DTC2      180    339      662    2,201,045       0%      20%       7%
  Samsung Week                DTC1            70     91      198      299,171       0%      19%      12%
  Samsung Boost Week          DTC1           122    196       65      175,212       0%      32%      27%
  Clearance                   DTC1             1      1       10       33,627       0%      25%       0%
  Samsung AI Week             DTC1            39     43        0            0        -      23%        -
  outside every campaign      -                -      -    1,299    3,045,978       0%        -      13%
  no plan line fits the order -                -      -    1,395    2,653,835       0%        -        -
  3 campaign(s) were planned and nothing arrived on them: Samsung AI Week, ...
```

| column | |
|---|---|
| `named by` | which of the plan's three columns carries this campaign - so the DTC's own campaigns can be read apart from the nationwide ones |
| `SKUs`, `lines` | what was planned: how many product codes, over how many plan lines |
| `units`, `revenue` | what arrived |
| `late` | the share of its units whose **own rule** names a window the order date sits outside - the engine still applying a promotion that had ended, or applying one early. It needs no plan to spot, because the rule carries its own dates |
| `plan DC` | what the plan meant to take off the RRP - the median over its live lines, from the first of `S.COM_Price`, `T2`, `T3`, `EDU`, `T1` each one carries |
| `paid DC` | what actually came off. Both are consumer prices, so the two compare as written, and a paid DC far under the plan DC is a campaign whose discount mostly did not reach the customer |

A campaign with plan lines and no orders was planned and did not happen. A
campaign with orders and no plan lines is the other way round. The two bottom
rows stay apart, because *outside every campaign* - a plan line was found and it
names none - is a different thing from *no plan line fits the order* at all.

## Campaign and mechanic are two axes, not two words for one thing

A promotion's **mechanic** comes off the store's rule: the engine applied it, and
an order can carry several at once. A promotion's **campaign** comes off the
plan, and the plan puts a product in one nationwide campaign at a time. One of
those can divide revenue and the other cannot, and they answer different
questions - *why did this sell* and *what was done to the price*. So the
campaign is read from the plan for **every** line, whichever source won the
attribution, and `promo_orders.csv` carries all three campaign columns beside
the rule.

Every `promo_match` run now reports the stack that would make, in the order the
decisions have to be taken:

```
campaign, from the plan - the one level that can divide revenue
  6 of 42 unit(s) (14.3%) sit on an order whose fitting plan lines give more than one answer for the
  nationwide campaign - counting "none" as an answer - so that much of the split below is
  a precedence rather than a reading

  by nationwide campaign  (units, share, amount)
    (no nationwide campaign)                              24  57.1%        16,778
    Black Friday                                          12  28.6%        35,444
    EOFY                                                   6  14.3%        29,995

  inside (no nationwide campaign) - 24 unit(s), 57% of everything:
  by DTC_Campaign1 ... by DTC_Campaign2 ... by what was done to the price
```

1. **Is it one campaign per order?** Measured, not assumed: the units whose
   fitting plan lines give more than one answer, with *none* counted as an
   answer - one line saying Black Friday and another saying nothing is as much
   of a choice as two naming different campaigns. The run also says how many
   units sit in the residual only because the line that best fits the **price**
   names no campaign while another that fits does: those are a tie-break away
   from being attributed.
2. **The stack**, with its two residuals kept apart. An order in no nationwide
   campaign is not the same as an order no plan line fits, and merging them
   would hide which problem you have.
3. **What the biggest residual is made of** - its DTC campaigns, then the
   mechanics underneath. Those two cannot be stacked, because an order can be in
   several at once, but they say what the band is a *mixture* of, which is what
   a legend entry called "none" owes the reader.
4. **Whether a profit row can carry a campaign**, on the same measure the other
   levels get: the share of rows whose units sit on one, and what the biggest
   holds on average.

The shape of the answer, then: stack by nationwide campaign, which is a real
partition; put DTC_Campaign1 and the mechanic underneath as a **composition**
of whichever band is selected, not as bands of their own.

## Can the profit page stack by promotion?

That is a different question, and the last block of `promo.py` answers it with a
number. A profit row is one customer and one product; a promotion belongs to an
**order**. So a profit row can only carry a promotion by being shared out over
the promotions its own orders ran under, and that is honest only where a row's
orders mostly sit on one.

The run measures exactly that, per level, on the finest key the two files share
(portal group x product code):

| | |
|---|---|
| **on one** | the share of rows whose units sit on a single promotion |
| **units on the biggest** | the average share each row's biggest promotion holds |

High on both and a stack by promotion is near enough a measurement. Low and the
chart would be apportioning, which is worth knowing **before** it is built
rather than after.

## A promotion is not a division of the revenue

The run prints one more number first, and it is the one that decides what shape
a chart can take: **how many units ran under more than one rule at once.**

A stacked bar divides a total - every unit in exactly one band. An order that
came in on a welcome voucher *and* a product discount *and* a PWP is in three at
once. On MX that is not an edge case: `Discount + Voucher`, `Discount + PWP +
Voucher` and `Discount + PWP` together are **59% of promoted units**.

On MX the answer is **82% of promoted units**. Promotion is not a partition of
the revenue.

So promotion works as a **filter** without further argument - narrow the page to
the EPP welcome voucher and read its P&L - because filtering needs no partition.

As a **stack** it needs a rule saying which family a unit counts as when it
matches three, and **family already applies one**: first match in the table
wins. That makes it a partition by construction, which is why it concentrates
better than any other level. The run therefore measures how much work that rule
is doing - per family, the share of its units that match **only** it - so the
precedence is argued from numbers rather than assumed.

`--precedence` reorders it from the command line:

```powershell
py tools\promo.py --division MX --precedence "% off RRP,$ off,Accessories offer,EPP welcome voucher"
```

That order is worth trying, because the default is likely backwards. The EPP
welcome voucher is **always on** - it is 5% off a first purchase, not a reason
anything sold this month - and being first in the table it collects every unit
that also ran under a real campaign. Putting it last attributes those units to
the campaign that drove them and leaves the voucher holding only what it won
alone.

When a level comes back with thousands of distinct values, it is not a level,
it is a pile - and before a rule for grouping it can be written, the pieces have
to be visible. `--tokens 40` counts the commonest pieces the offer strings are
built from, by the units behind them. A token on a large share of the units is a
grouping waiting to be named: a campaign, a mechanic the vocabulary is missing,
or a wave code that only fragments what is otherwise one offer.

`--division MX` asks the question of one division and takes several names, so
`--division VD DA` asks it of CE if the master splits it that way;
`--month 2608` asks it of one month. A division asked for by a name the master
does not use comes back with **the names it does use**, and their line counts,
rather than with "nothing" - which otherwise reads as "nothing was promoted"
when it means "that is not the word".

Output goes to `docs/promo_levels.csv`, which is **not** committed - like every
other csv these tools write, it holds real customers and real revenue.

### What CE's plan turned out to be

`CE_product` needs **no flags**: every slot the loader looks for is spelled
exactly as MX spells it, so the differences are all in the columns MX does not
have - `Division`, `Category`, `Range`, a discount **percentage** per tier, an
`Overlap` flag, `EPP_Tier`, `Hot_Deals`, `Aged_Clearance`, `SOH`. 9,906 lines,
9,660 of them live, over 557 SKUs.

Four things in it changed the code:

**`Offer_Type` is clean.** 100% filled, ten values, and four of them were in no
vocabulary: `Delivery/Install`, `Samsung Care+`, `Rewards Earn`, `Rewards Burn`
(1,044 live lines, a ninth of the file). They are now mechanics like the rest,
with an `EXECUTED_AS` entry each - free delivery is a discount on the delivery
line, Samsung Care+ at a dollar is a PWP, burning points is a voucher nobody
paid cash for, and earning points changes no price at all. CE therefore needs
no mechanic *parsed* out of anything: unlike the store's rule codes, its plan
states the mechanic in a column.

**`DTC_Campaign1` was being read by nothing.** The plan has three campaign
columns; `promo` took `Nationwide_Campaign` and `promo2` took `DTC_Campaign2`,
and the one in the middle - 49% filled on CE, and where Samsung Week, Samsung
Boost Week, Clearance and the launches live - fell through the gap. It is now
its own slot and part of the label.

**The plan's own discount percentage is `1 - price / RRP`.** Over 5,540 lines
that carry both, the median gap between `S.COM_Discount_Percentage` and that
division is **+0.00pp** and 99.8% are within 1pp. So the discount the plan
quotes is measured off RRP exactly as `asp_xlsx`'s DC % column defines it, and
`S.COM_Price` and `RRP` are on the same basis - both consumer prices, GST
included - which is what makes the `÷1.1` in that column necessary against
ex-GST net sales. Ten lines of 9,660 disagree by more than 1pp, all Monitor, one
of them reading `52425.0%`: a typed percentage, not a wrong RRP.

**A SKU has more than one live plan line in a month.** Median 2, up to 17, and
66% of SKU-months have at least two; the plan flags `Overlap` on 27.6% of live
lines itself. That is the plan-side version of what the store side showed on MX
(82% of promoted units under more than one rule), and it is why "the promotion"
for a material-month is reported as the biggest with its share rather than as
the only one.

Its `Division` reads `TV & SD`, `DA`, `Monitor`, `Memory` - four names, none of
them "CE", and not necessarily how the SAP product master spells the same thing.
`--division` takes several names for that reason, and says which names the
master actually uses when the one asked for is not among them.

### The family table is MX's table

It was read off MX's own codes, so pointed at another division it is a
hypothesis. CE's offers run to cashback, redemption, a bonus gift, delivery and
installation, and none of those is in the table. So every run reports what the
table **fails** to name - the share of promoted units in the residual, and the
commonest pieces those units are built from:

```
what the family table does not name: <units> unit(s) (<pct>% of the promoted)
    TV                                   <units>   71%
    INSTALL                              <units>   29%
    DELIVERY                             <units>   29%
    FREE                                 <units>   29%
```

That list is where the division's own families get written from - the same way
MX's were - and `FAMILIES` at the top of `tools/promo.py` is where they go. A
high residual means the table does not fit that division yet, not that its
offers are unstructured.

### What the store's CE rules then showed

Running it over the ten store exports, CE is **82,576 of 352,963 order lines**
(`TV & SD`, `DA`, `Monitor` - MX is the other 76% of the store, which is what a
DTC store selling phones looks like). 60% of CE's units carry a promotion, and
**74% of those ran under more than one rule at once** - the same finding as MX's
82%, from the other side of the join.

Three things in that run changed the code again:

**`BOGO` is a mechanic**, 11,109 units of CE's promoted - the third largest
thing in the file - and it was reading as "mechanic not in the code". So are
`SHIPPING`/`FREE SHIPPING` (delivery) and `FOC` (free of charge, a gift).

**`MESSAGE` and `AUME` are prefixes, and a long number is an id.** `MESSAGE` is
on 60% of CE's promoted units and `AUME` on 50%, and `AUME 18596` / `AUME 19733`
/ `240207` are the promotion's own serial. That is why CE's offer level came
back with 3,949 distinct values whose eight biggest covered a third: the same
offer, re-numbered every time it ran. They are noise now, along with any token
of four or more digits - `5PCT` and `50` stay, because those are the offer.

**Nothing falls back to the raw code.** `' '.join(rest) or d['what']` put the
whole rule string back as the offer whenever every word of it had been taken as
a mechanic or a serial, which undid the strip it had just done: `DISCOUNT
RULE-EXECUTE-AUME-19733` came back as an offer in its own right, 967 units of
serial number counted as a promotion. A rule with nothing left is `(no detail)`
- which is a real answer, and a useful one.

**A family is read from the mechanic as well as the offer.** Pulling the
mechanic out is what makes the offer level readable and it is also what can
empty it: `BOGO HW LS60D XY AUME 18596` leaves a bare model code and
`FREE SHIPPING` leaves nothing, and neither had a family. The mechanic is part
of what the offer was, so it is put back for that one question.

### The precedence, decided from numbers

`EPP welcome voucher` was first in the table and took **21,935** of CE's
promoted units - 42% of them - and its "only this one" was **0%**. Every single
unit it held also ran under a real campaign. It is a standing 5% off a first
purchase; it is not why anything sold in September.

So the table is now ordered by what each row *is*, not by which division it came
from:

| | |
|---|---|
| **what the offer was** | a named offer - trade-in, price match, stunt promotion, BOGO, delivery, bundle |
| **why it ran** | the campaign. The offer type level already answers "what mechanic", so this level is where "why" belongs: `[Boost Week] EPP $100 Voucher` is filed under Boost Week |
| **the standing offer** | the EPP welcome voucher, below every campaign so its units go to the campaign that drove them - but above the rows below, so a rule that is *only* the welcome voucher is still named as one rather than as "% off" |
| **how the price was written** | `% off RRP`, `$ off`, `% off`, `Price off`, `$ voucher` - descriptions, not offers |
| **last resorts** | `EPP`, which says only which tier could buy; then the plan-note words |

That is a **choice**, and the run measures how much work it does: 62% of CE's
promoted units match more than one family, so that much of the split is the
order of this table rather than anything read off a code. `--precedence` changes
it from the command line, and the earlier MX family numbers in this session were
taken with the welcome voucher first, so they will move.

One of the CE rows was **wrong on the store side**: `CVM` and `CRP` were put in
the plan-note pattern because the plan writes `[CVM/CRP]` in its comment field,
and on the store side `CRP` is part of a live rule - `B2C CRP CE 231103` - which
is 9,843 of CE's promoted units. They are out of the pattern, and the whole
plan-note row is last now, because its words are ordinary English and a store
rule that happens to use one is still a real offer.

CE's own rows are there now, read off `CE_product`'s `Offer_Detail` the same
way. On MX's table alone, CE's offer details came out **75.6% unnamed**; with
its own rows that is **1.9%** - a long tail of one-offs (`$100 DA Smart Things
CRM`, a bare model code, `Disti Promo`). The rows were **appended**, not
interleaved: first match wins, so anything placed above MX's would quietly
re-bucket MX, and these were derived from a file MX is not in. Inside the block
the order is offer before campaign - `[Boost Week] EPP $100 Voucher` is a
voucher that ran during Boost Week, not a campaign that happened to be a
voucher.

Two of them are worth knowing about:

| | |
|---|---|
| `Price off` | MX's `% off` and `$ off` match `50PCT` and `100OFF`, because the store writes a promotion as one token. CE's plan writes the same thing in prose - "20% off", "$100 Discount" - and punctuation is stripped before matching, so it arrives as `20 OFF` and matched neither. Its own row rather than a space added to MX's, which would have moved MX units between named families. |
| `Plan note (not an offer)` | `Override`, `Promo Extended`, `Offer change (price sharpening)`, `[CVM/CRP]`, `Retail Promo` - 208 live lines where the `Offer_Detail` cell was used as a comment field. Named so they can be counted and set aside, rather than sitting in the residual looking like offers nobody has classified yet. |

The table is now 27 rows, so the overlap report - how much of each family is
**only** in that family - counts more overlap than it did: a longer table means
more offers match more than one row. The precedence does correspondingly more
work, which is the number that report exists to show.

## The order export already knows

`26 DTC Aug` carries **`promotion_rule`** - the code the store itself applied -
and **`Voucher Code(s)`** - what the customer typed. Neither is a guess, so
both are used before anything is inferred. Three sources, in order of how much
they can be trusted, and every row says which one answered it:

| Source | |
|---|---|
| `rule` | the store's own promotion code, parsed into something readable |
| `voucher` | the order's voucher found in the plan's `Voucher_Code` |
| `plan` | the SKU, in a promotion whose window covers the order date, at a price near the one paid - **an inference** |

A rule like `AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT` is pulled
apart on its dates: whatever sits before them says where it ran, whatever sits
after says what the offer was. The shape is read off the dates rather than off
fixed positions, because the positions vary. One cell can hold several rules,
comma-separated; all of them are kept.

## A trade-in is not a discount, and it sits in the price column

The plan quotes what the promotion sells a phone for. The order export quotes
what was collected - and a traded-up phone pays part of the price in a phone, a
points redemption pays part of it in points. Both land in
`AUD Revenue excl. GST`, the same column the price test reads.

So a Fold8 on the FF8 Pre-Order at $2,579 arrives as about $1,350 after a $700
trade-in, the nearest plan price is 47% away, and the line is thrown out on
price - **inside its window, on the right product code, at the right price until
the trade-in came off it**. Nothing about the match was wrong except the number
it was given.

The price test now tries two readings of each line at once: the amount as
written, and the amount with `AUD Trade-in Product Value excl. GST` and
`Points Redeemed AUD Price` added back. Nearest over both together, so adding
the trade-in back can only rescue a line the amount as written would have lost -
it never pulls a line that already fits onto a different plan row. The run says
how many lines it rescued.

Everything that compares a price to the plan uses the pre-trade-in price, for
the same reason:

| | |
|---|---|
| the plan match | or a traded-up line fits nothing |
| **does the price belong to the promotion the rule names** | or it reads "planned, and the customer did not pay it" |
| **paid DC** in planned-vs-arrived | or a campaign that gave 4% reads 23% |

What the customer actually paid is still carried beside it, and the discount
report still reads `Average Net Discount`. The two prices answer different
questions and neither replaces the other.

## Was anything able to name the discount that came off?

"Is all of this caught?" is two questions, and they have different answers. The
export states a discount per line; whether a *promotion* could be put against
that discount is separate. Four outcomes, counted in units, revenue and average
discount:

| | |
|---|---|
| **named** | the rule, the voucher or the plan answered |
| **rule not read** | the cell holds something, but not a shape this build can parse - `2025_05_02_20_PERCENT_FIRST_PURCHASE_DISCOUNT_WESTPAC_BUSINESS` |
| **no rule recorded** | the discount is real and `promotion_rule` is empty - order `AU260803-38105969` lost 25% with nothing to say why |
| **trade-in, not a price cut** | the only discount is the phone the customer handed over |

The last two get three real rows each, biggest revenue first, because they are
the ones worth looking up. A number cannot be chased; `SM-S938BZKEATS` on
`AU260803-38105969` can.

### Net discount, not customer discount

The export states both, and they are not the same thing:

| | |
|---|---|
| `Average Customer Discount` | everything off the sticker, trade-in and redeemed points included |
| `Average Net Discount` | what the promotion took off the price |

A Fold8 traded up reads `0.760685056` and `0.5` on one line: 76% is what the
customer experienced, 50% is what the promotion cost. **Net is read**, and
`AUD Trade-in Product Value excl. GST` and `Points Redeemed AUD Price` are read
beside it so the gap can be named rather than silently included. Where the two
columns disagree the run says by how much and on how many units.

`AUD RRP`, `Average Net Discount`, `Average Customer Discount`, the trade-in and
the points columns are all found by name now, so the August export needs no
`--order-rrp` or `--order-disc` at all.

## Did the orders come in on the promotions that were planned?

That is what the run's last block answers, and it compares the two sides four
ways:

| | |
|---|---|
| **where the answer came from** | how many lines the store's own rule answered for, how many a voucher did, how many only the plan could infer, and how many nothing fits |
| **rule vs plan** | of the lines both answered for, how often the **mechanic** agrees. The two name promotions in different vocabularies - a rule says `PWP`, the plan says "Black Friday / PWP" - so the mechanic is the part both spell |
| **outside its own window** | lines carrying a rule whose own dates do not cover the order date. The rule names its window, so this needs no plan at all |
| **price paid vs plan price** | the median gap. Far from zero means the two quote prices on different bases - `--gst`, `--amount-is` |

It also reports what **looser matching would buy**: how many of the plan matches
only fit because of `--window-slack`, and how many more lines each extra day
would catch. Each one is a looser rule, not a better one, and the row says which
lines it brought in.

**The mechanic comparison was wrong until now.** It took the first three
characters of whatever the code happened to start with and looked for the plan's
word in them - so on a rule carrying no dates, which comes back as one unbroken
string, it tested `AU_` and said the two differ every single time:

| rule | plan says | old | now |
|---|---|---|---|
| `AU_EPP_T2-T3_all_welcome-voucher_-_percentage-discount` | Discount | differ | **same** |
| `AU_SCOM_WEB_SP_14AUG26_09SEP26_PWP_FOLD-WATCH-30PCT` | PWP | same | same |

There was a second gap on the other side. The store writes `TRADEUP` as one
token; the plan writes **Trade-Up**, **Cash Back**, **Gift with Purchase** - and
splitting those gives TRADE and UP, neither of which is a mechanic, so the plan
side fell back to its raw wording and could never match. Adjacent words are now
tried joined as well, and the words the plan uses are in the table.

Both sides go through one vocabulary. Any agreement figure read before this
understated itself twice over.

**The run shows what the disagreements are** - the commonest
`rule says / plan says` pairs, with a line count each. A count on its own cannot
tell a promotion that ran off plan from one of the two sides being read wrong;
the pairs can.

### They are not two vocabularies. They describe different things.

The pairs settled it. On August, with the two sides finally read properly, the
cross-check still said 14% - and 74% of every disagreement was one pair:

| the rule says | the plan says | lines |
|---|---|---|
| `Discount + PWP` | Bundle | 1,719 |
| `Discount + PWP + Voucher` | Bundle | 605 |
| `PWP` | Bundle | 214 |
| … | Bundle | 2,967 in all, **78%** |

A **bundle** is sold as purchase-with-purchase at a discount. The plan names
what the offer **is**; the rule names what the engine **did** to deliver it.
They are the same promotion described one level apart, and comparing them as
though they were synonyms measures nothing.

So a plan type is now compared against the mechanics it is **executed as**, and
the run prints both readings:

| | |
|---|---|
| **the same mechanic** | the strict comparison, kept so nothing is hidden |
| **the plan's offer as run** | a Bundle delivered as `PWP + Discount` counts here |
| **neither** | what is left, and the pair table says what it is |

On August that took the agreement from **14% to 91%**, and what is left is one
pattern: 357 of the 411 remaining are the plan saying **Discount** against a
rule that ran **PWP**. That is the comparison working, not failing - the plan
said a straight discount and the store ran buy-with-purchase, which is a
question for whoever set the promotion up.

`EXECUTED_AS` holds the equivalences and is meant to be read and argued with.
Only what is genuinely implied is in it - a voucher is a discount applied by
code, a trade-in is a discount for the trade. **`Discount` stays strict**: a
plan that says Discount against a rule that says PWP is a difference worth
keeping.

## The plan

### One plan file per division, read together

`--plan` takes several stems and defaults to **`MX_product ce_product`**. An
order does not know which division's file it belongs to, so it is matched
against all of them at once, and the plan line it matched records which file
answered. That is the difference between "the plan has no line for this product"
and "the other division's plan has it", which are not the same fault and do not
have the same fix. A stem that names no file is said and skipped, not fatal: one
division's plan arriving late should cost that division's rows, not the run.

The two files are **the same shape with a few differences**, and the differences
are where a column quietly reads as blank, so every run with more than one plan
prints them before doing anything with the data:

```
the plan files, side by side: <n> column(s) in all of MX_product.csv, ce_product.csv
  only in MX_product.csv: DTC_Campaign2, Offer_Type, SKU, Start_Date, Voucher_Code
  only in ce_product.csv: Bonus_Gift, Model Code, Offer Type, Promo Price, Start Date
  what each file answers with:
    MX_product.csv  sku='SKU', promo='Nationwide_Campaign', type='Offer_Type', ...
    ce_product.csv  sku='Model Code', promo='Promotion Name', type='Offer Type', ...
                    nothing for: voucher - read as blank
```

The last two lines are the ones that matter: a slot with nothing behind it is
read as blank for every row of that file, and a file with no `RRP` column gives
no list price. `--promo-sku` and the other overrides apply to whichever file has
that column and are a warning, not an abort, for the one that does not.

`tools/promo_match.py`, `tools/promo_profit.py` and `tools/asp_xlsx.py` all read
the plan through the same loader, so none of them can disagree with the others
about which status was never live, which columns hold a price, or how a window
is read.

### The label

`MX_product` has no single promotion-name column, so the label is built from
`Nationwide_Campaign`, `DTC_Campaign2` and `Offer_Type` - whichever are filled;
in `ce_product` the same three slots land on `Promotion Name`, `Offer Detail`
and `Offer Type`.
Lines whose `Status` or `PUMI` reads cancelled, tentative, draft or rejected
are **left out**: nothing sold under a promotion that was never live.
`--keep-cancelled` keeps them, and cancelled orders, in.

Every price column the plan carries - `S.COM_Price`, `T1_Price` … `T3_Price`,
`EDU_Price`, `RRP` - is tried, nearest to what was paid. Which one won is
written on the row, so **`paid the T2_Price`** says which tier the customer was
on without the portal having to be mapped by hand.

### The two prices must be on the same basis

`AUD Revenue excl. GST` is a line total without tax; the plan quotes retail
prices per unit. So the amount is divided by the quantity and grossed up by
`--gst` (10 by default) before anything is compared. `--amount-is unit` turns
off the division.

The run prints the **median gap**. Near zero means the two agree; far from zero
means they do not, and every comparison is then wrong in the same direction:

```
price paid vs plan price, 1,361 comparison(s): median +2.43, from -277.64 to +129.88
a median far from zero means the two quote prices on different bases - try --gst or --amount-is
```

Check that before trusting the split.

## Reading the result

```
attributed 3,785 order line(s) (215 cancelled left out):
   2,130   56.3%  the store's own promotion rule
     250    6.6%  a voucher the plan lists
     335    8.9%  inferred from the plan - code, window, price
   1,070   28.3%  nothing fits
  of 467 line(s) the rule and the plan both answered for, the mechanic matches
  on 125 and differs on 342
  689 line(s) carry a rule whose own dates do not cover the order date
```

Two cross-checks, both chosen so they mean something:

- **The mechanic.** The rule and the plan name promotions in different
  vocabularies - a rule says `PWP`, the plan says `Black Friday / PWP` - so
  comparing the names would measure nothing. The mechanic is the part both
  spell, so that is what is compared.
- **The rule's own window.** A rule names the dates it runs between. An order
  dated outside them needs no plan to spot, and says something is wrong with
  one of the two files.

`why nothing fit` splits the misses into the three different answers they are -
no plan line for the product, nothing running that day, or a price no promotion
offers - because each wants something different done about it.

## Matching dirty data on purpose

The rules above are the strict ones. When the files are not yet clean, what
matters is knowing what each loosening is worth and what it costs, so the run
counts both rather than leaving it to be guessed at:

```
what looser matching would buy, on the lines nothing fits now:
  --stem 8                     1,204 more line(s) - the same model in another colour
  --window-slack 3               192 more line(s) - ordered that close to a window
  --window-slack 7               365 more line(s) - ordered that close to a window
  --price-tolerance 10           105 more line(s) - paid within 10% of a plan price
```

| Flag | What it loosens |
|---|---|
| `--stem N` | a product code matches on its first N characters, so the same model in another colour or capacity finds its plan line. Try 8 |
| `--window-slack DAYS` | an order this far outside a window still counts; the row records how many days out it was |
| `--price-tolerance PCT` | how far the price paid may sit from a plan price (3 by default) |
| `--agree PCT` | how much of a portal group's accounts must agree before a customer level is taken as settled (80 by default) |

Every one of them is a *looser* rule, not a better one. So nothing is hidden:

- The row's **`Matched by`** carries the whole chain - `code starts with
  SMS931B, in window give or take 4 day(s), paid the T2_Price` - and
  **`Days outside window`** is its own column.
- On the page, a plan match that needed a loosened rule is **its own colour**,
  counted apart as *Loosened rule*. A bar that is mostly yellow is held up by
  the loosening and will move when the data is cleaned; a bar that is mostly
  blue will not.

That way a loosening can be turned on to see the shape of the month, and read
back off afterwards.

## What comes out

| File | |
|---|---|
| `docs\promo_orders.csv` | one row per order line: source, promotion, the raw rule, the voucher, what the plan would have said, how it matched, which price column, and the gap |
| `docs\promo_summary.csv` | per source and promotion: order lines, units, amount |

Both are UTF-8 with a BOM, so Excel opens them without the import wizard.

The plan's answer is kept **on every row even when a rule won**, in `Plan says`
and `Plan matched by`. That is what makes the two comparable rather than one
overwriting the other.

## The page

```powershell
py tools\promo_match.py --html        # -> dashboard\promo_2608.html
```

One self-contained file with the profit chart's controls - the same cascading
selects, breadcrumb, **← Back** and **Bars by** - and three things on it:

- **How each line was attributed** - the KPI row and a daily stacked bar. The
  grey band is what nothing could answer for, and *its shape over the month* is
  the thing to look at: a flat grey band is a systematic gap, a spike is one
  day's promotion missing from the plan.
- **Revenue by offer**, biggest first. The page opens on **Offer Type** -
  Discount, PWP, GWP, Bundle - and clicking a bar opens it by **Offer Detail**,
  then on into Product Category. Each bar is *stacked by which source answered*,
  so a bar that is mostly blue needed no inference and a bar that is mostly
  green rests entirely on the SKU-window-price guess.

  Both sources land on the same two levels: the plan names an `Offer_Type` and
  an `Offer_Detail`, and a rule runs the same two together in its code, so the
  mechanic is read back out of it (`DISC` → Discount) rather than charting two
  vocabularies that cannot be compared.
- **Why nothing fit**, as a table, since each reason wants something different
  done about it.

### The customer half

The order export carries a **portal group**, not a payer - and its vocabulary
is not the customer master's `Portal Group` column. `S.COM` and `EPP` are
spelled in the master's **Type**, `EDU` and `Partnership` in its **Type2**, and
the master's own Portal Group holds different words again (`EPP External`,
`3PD`). Matching one named column against another misses almost everything.

So every value of every level is indexed as a possible spelling, and a lookup
returns **only what the accounts behind it agree on**. Asking for `EPP` settles
the Type, because every account spelled that way carries it; it leaves Type2 as
`(master does not say)`, because those accounts carry several. That is worth
more than a plausible guess, and it reads differently from
`(no customer match)`, which means the group was not found at all.

The build prints which column each group was found in and what it settled:

```
portal groups: 42,151 of 42,151 line(s) found their group in the customer master
  EPP        11,953 line(s)  <- Type; says type=EPP / channel=E-STORE
  EDU         8,952 line(s)  <- Type2; says type=EPP / portal=EPP External / type2=EDU
```

What comes back is the hierarchy the profit chart drills:

```
Channel -> Type -> Type2 -> Portal Group -> Portal -> Offer Type -> Offer Detail -> Product Category
```

**Portal** is the order file's own finer column - `samsung_benefits_au`,
`commbank_yello_au`, `au` - so it breaks a portal group down without inferring
anything. Where Type2 is unsettled because one portal group spans several of
them, Portal is usually the level that actually separates them.

A level the master cannot settle is explained rather than left blank:

```
EPP     11,953 line(s)  <- found in Type; settles type=EPP / channel=E-STORE
    type2 unsettled: EDU 46%, GOV 26%, Corporate 20% ...
```

That is the whole answer to "why is Type2 nearly empty": a single portal group
value cannot pick between four Type2s its accounts carry. `--agree` lowers the
bar (default 80%) if the commonest is good enough for the question being
asked.

A portal group whose accounts disagree on a level takes the value most of them
carry, and the disagreement is printed - it is a judgement, not a lookup, so it
is not made silently.

Rows are rolled up to one per source, per level value and per day - always
fewer than the order lines, usually far fewer - so the page stays small and the
filters and the drill work off sums.

### What it can cover

The plan only lists one division, so nothing outside it can be attributed at
all. The build prints the order export split by division, which is the ceiling
on what any of this can explain:

```
the order export by division - the plan only covers what it lists, so the rest
cannot be attributed at all:
  MX                     28,140 line(s)   66.8%
  TV & SD                 7,905 line(s)   18.8%
```

## When a guess is wrong

`--profile` prints every column of both files and then the columns it chose.
Each can be named directly: `--order-rule promotion_rule`, `--promo-name
DTC_Campaign1`, `--order-amount "AUD RRP"`, and so on. The columns decide every
number below them, so fix those first.

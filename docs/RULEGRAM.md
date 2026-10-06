# What a promotion rule is made of

```powershell
py tools\rulegram.py --orders "26 DTC Sep"
```

One file, read on its own terms. Nothing here is matched against a plan - the
point is to find out what the store's own vocabulary **is** before asking
whether two files share one.

## The dates are the landmark

The store writes a promotion as one joined code:

```
AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT
```

Read left to right it is plainly not arbitrary - a country, who may buy, where,
what it is on, when it runs, the mechanic, then the offer. But the number of
pieces varies, so counting from the left gets the wrong answer on half the codes
and counting from the right gets it on the other half. The **dates** hold
whatever the length: everything before them says where the promotion ran and to
whom, everything after says what it was.

The run reports the shapes first, as `(pieces before / dates / pieces after)`,
by the units behind each - because a shape on four hundred units says more about
the vocabulary than one on four. A rule with no dates has no landmark and is
read as one piece, which is counted and said rather than guessed at.

## What turns up in each position

Each piece before the dates and each piece after gets its own table, biggest
first. On a month of CE orders the first three before the dates come out as the
country, the buyer and the site, and the first after the dates is the mechanic -
but that is a **reading of the output**, not a rule written into the tool.

| | |
|---|---|
| **the piece immediately before the dates** | what the rule is about: `TV`, `AV`, `DA`, `SP`, `REF`, `MX`, `WM`, `MON`. The share of those that the **product master also spells** is reported, so the short forms only the store uses stand out as the ones to read off the list rather than guess at |
| rules with no piece there | counted separately: their last piece before the dates is the site or the buyer, so those rules say nothing about what they are on |

## The grammar a month of CE orders comes out with

```
AU  _  EPP  _  T2-T3  _  TB  _  05SEP26 _ 19SEP26  _  DISCOUNT  _  <the offer>
country  who     tier     what it is on      when           mechanic
```

| piece | what turned up | |
|---|---|---|
| 1 | `AU` 98.5% | the country |
| 2 | `EPP` 61.6%, `B2C` 35.0%, `SME`, `SMB` | **who may buy** - the rule says it, so EPP needs no inference from the customer master |
| 3 | `WEB` 54.2%, **`T2-T3` 32.4%**, `CRP`, `EPROMOTER` | where, or - on EPP rules - **which tier** |
| 4 | `ALL` 35.7%, `MX`, `TV`, `SP`, `TB`, `WR`, `CE`, `MO`, `HA`, `AC`, `RF`, `WM` | what it is on, and `WM-DR-VC` style combinations say several at once |
| after the dates, 1 | `DISCOUNT` 31.9%, `PROMOTEXT`, `PWP`, `BOGO`, `TRADE-IN`, `BMSM`, `SHIPPING` | the mechanic |
| after the dates, 2 | the offer itself | |

`(4, 2, 2)` is 56% of units and is that shape. The next two shapes, `(11,0,0)`
and `(12,0,0)`, are a third of the units between them and are almost entirely
**one** rule - the standing welcome voucher, which carries no dates and spells
itself out in eleven pieces.

The short forms the product master does not spell - `SP`, `TB`, `WR`, `MO`,
`HA`, `RF`, `DR`, `VC` - are in a table at the top of `tools/rulegram.py`, read
off that run rather than invented, and reported as a **different kind** from the
groups the master does spell, so a wrong one is visible rather than blended in.
Edit the table, not the code.

## How wide is a rule?

The number that decides whether a rule can be matched to a plan at all. The plan
is written per **product code**; a rule that names a category and sold over four
hundred of them is not a line in that plan and never was, and no amount of
loosening the price or the window will make it one. So the run reports how many
product codes each rule covers, the median and the widest, and what share of the
units sit on rules covering ten or more.

## What each piece is

Every piece is classified by what it looks like and nothing else - a date, a
country, a buyer, a site, a mechanic, a percentage, a serial, a product group -
and the product group vocabulary is the **product master's own** divisions,
categories and ranges, passed in rather than written in the tool.

Everything left over is `unnamed`, and that is the answer the run exists for: a
piece sitting on a lot of units that no vocabulary in these tools names is a
category this file uses and nobody wrote down. The unnamed pieces are listed
biggest first, and split by whether they sit before the dates or after, because
the two sides are different questions.

## The csv

`docs/rule_grammar.csv` has one row per distinct rule, taken apart: the pieces
before the dates, the dates, the pieces after, the mechanic and offer those
resolve to, the family it lands in, and the pieces nothing could name. It is
**not** committed - like every other csv these tools write it holds real
promotions and real volumes.

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

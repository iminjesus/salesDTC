# One cost line, month by month - and whether it moved on rate or on mix

```powershell
py tools\deduction.py
py tools\deduction.py --column AK --where "Div 1=DA" --was 2601..2606 --now 2607..2609
py tools\deduction.py --column "Paid Commission" --where "Div 1=DA" --out docs\comm.csv
```

Sales deduction is the default because it was the first question asked of this,
but **any money column of the profit export** works the same way, and a total
hides four very different stories:

| | looks like |
|---|---|
| **a rate** | every row deeper, in step - an accrual, a programme that applies to all of it, or **a mechanic that moved out of the price and into this line** |
| **a mix** | the same rates, more of the deeper rows |
| **a few accounts** | one customer's rebate - a negotiation, not a trend |
| **one month** | a true-up: a lump landing where it was settled rather than where it was earned |

So the trend comes first - per channel, per month, as a total, as a share of
sales and **per unit** - and then two periods are taken apart:

```
paid commission, month by month
  month    channel         units        gross   Paid Commission  of gross   per unit
  202601   online             20          200                 6      3.0%       0.30
  202607   online             20          200                12      6.0%       0.60

E-STORE: paid commission 3.0% of gross -> 6.0%  (+3.00pp)
  the rows themselves deepened (rate)         3.00pp
  the business moved (mix)                    0.00pp
                                          --------
  the change                                  3.00pp
```

The split is shift-share over one row per **account × Div 3 × model**: hold
each row's own rate and move the weights (mix), then hold the weights and move
the rates (rate). The run says in words which of the two it is when one
dominates, and lists the rows that moved it most - with `--out` for all of
them.

## A ratio has two sides

A share of sales rises when the amount grows **or** when sales fall, and the
two call for opposite responses. So before the rate-versus-mix split, both
sides are put on a monthly footing - the periods are rarely the same length -
and the gap is divided between them:

```
E-STORE: paid commission 0.93% of gross -> 1.21%  (+0.28pp)
  145,377 over 6 month(s)  ->  71,576 over 3 month(s)
  a month of it                    was           now
  the paid commission           24,230        23,859      -1.5%
  the gross                  2,612,879     1,978,259     -24.3%
  the units                      3,410         2,543     -25.4%
  the base shrank               +0.30pp  107%
  the amount itself             -0.02pp   -7%
```

**A cost that does not flex with sales reads as a deepening rate when sales
fall, with nothing having been decided anywhere** - and it does that in every
market at once, which is the tell. An allocated pool, a committed fee, a
headcount-driven charge: all of them behave this way. When the base carries
the gap, the rate-versus-mix verdict says so too, because "every row deepened
together" is precisely what one number over a smaller number looks like.

## Just the months

`--total` prints one row a month for the whole business and stops there - no
channel split, no rate-versus-mix, nothing to read past:

```powershell
py tools\deduction.py --column "*Paid Commission" --total
```

```
paid commission, month by month
  month          units        gross   Paid Commission  of gross   per unit
  202601        35,212   14,419,584           270,110      1.9%      11.33
  202602        29,841   10,584,668           172,927      1.6%       9.62
```

The channel split is the next question, not that one, and two rows a month is
how a nine-month answer stops being readable at a glance.

## The scope, said every time

The figures are right and the **scope** is what differs from the profit page,
so every run prints what it covers before it prints anything else:

```
  scope: every channel and every product; returns in
         the profit page shows E-STORE only and drops Biz=Memory and Biz=(blank),
         so its figures are smaller - --where "Channel=E-STORE" --drop "Biz=Memory" --drop "Biz=(blank)" matches it
```

This tool reads **the file as it is**: both channels, every business, returns
in. The page opens on the online business with Memory and the blanks dropped,
so the same column comes to a different number on each - January's gross is
203m here and 14m there, and both are correct. `--where` narrows and `--drop`
excludes, in the page's own spelling, so the two can be made to agree.

## Picking the column

`--column` takes a header name (`--column "Paid Commission"`) or a
**spreadsheet letter** (`--column AK`), because that is how a column gets
quoted in practice. A letter is positional and an export gets re-cut, so the
run always prints the header it landed on:

```
  column: 'Paid Commission' (column AK, counted across), as a share of gross
```

**Check that line before reading anything else.** If the export gained a
column, `AK` is now the one next door and the number below it is a different
question's answer. `--of net` makes the rate a share of net sales instead of
gross.

The column's sign is decided once, by where the column's own weight sits, so
an export that carries costs negative reads the same as one that carries them
positive - and a credit keeps its own sign instead of being counted as one
more cost.

## Narrowing to one part of the business

`--where LEVEL=VALUE` is repeatable and takes a value list:

```powershell
py tools\deduction.py --column AK --where "Div 1=DA"
py tools\deduction.py --column AK --where "Biz=CE" --where "Div 2=REF,WM"
```

`Biz`, `Div 1`, `Div 2`, `Div 3`, `Range`, `SKU`, `Account` and `Channel` all
work, in any spelling (`div1`, `Div 1`). The levels come from the product
master, so a level that master does not carry is an error up front rather than
an empty table further down, and a value no product has prints the values it
does have. Every run says how much of the export the slice kept:

```
  div1=DA: 41,882 of 214,097 rows
```

## Choosing the level, and reading the months

The split is computed over whatever level the question is at. `--by` takes a
level list, and the default `account,div3,sku` is the finest one:

```powershell
py tools\deduction.py --column "*Paid Commission" --where "Div 1=DA" --by div2 --grid
py tools\deduction.py --column "*Paid Commission" --where "Div 1=DA" --by account
```

`--grid` then prints the rate **month by month for each group**, which is the
view that separates the two things a two-period split cannot:

```
paid commission as a share of gross, by div2
  group                         01      02      03      07      08      09     all
  WM                         1.02%   1.05%   0.31%   1.22%   0.54%   1.60%   1.05%
  REF                        0.81%   0.83%   0.24%   1.15%   0.49%   1.42%   0.88%
```

A group that moved once and **stayed** is a rate - a fee schedule, a programme.
A group that **spiked and fell back** is a posting: an accrual or a true-up
landing in the month it was settled. Both read as "the rows themselves
deepened" in the rate-versus-mix split, and only the months apart tell them
from each other. A step that lands in the same month across every group is the
same event seen many times, not many events.

`--channel` picks the side (default the online one). `--was` and `--now` take
month lists in either spelling (`2606` or `202606`) and accept a **range**,
`2601..2606`, which matters when the comparison is a half against a quarter
and writing six months out by hand is where one goes missing. With neither it
compares the last three months in the folder against the three before.

## What it will not tell you

- **Where a cost was booked** is the export's decision. A rebate or a
  commission posted against the account rather than the model lands on that
  account's rows and on no particular product, which reads as a rate across
  everything that account bought.
- **When it was earned.** A true-up lands in the month it was settled. A rate
  that jumps for one month and falls back is that, and the monthly trend above
  it is what shows it.
- **Whether the column is the whole cost.** One column of an operating-cost
  block can rise because the cost rose or because it was re-classified out of
  a neighbouring column. The neighbour's own trend, run the same way, is what
  separates those two.
- Returns are in by default, as everywhere else; `--no-returns` takes them out.

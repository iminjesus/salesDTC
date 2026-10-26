# Sales deduction: what moved it, and whether it is a rate or a mix

```powershell
py tools\deduction.py
py tools\deduction.py --was 2601,2602,2603,2604,2605,2606 --now 2607,2608,2609 --out docs\ded.csv
```

Deduction is the line a channel is paid through, and a total hides four very
different stories:

| | looks like |
|---|---|
| **a rate** | every row deeper, in step - an accrual, a programme that applies to all of it, or **a mechanic that moved out of the price and into this line** |
| **a mix** | the same rates, more of the deeper rows |
| **a few accounts** | one customer's rebate - a negotiation, not a trend |
| **one month** | a true-up: a lump landing where it was settled rather than where it was earned |

So the trend comes first - per channel, per month, as a total, as a share of
gross and **per unit** - and then two periods are taken apart:

```
sales deduction, month by month
  month    channel         units          gross     deduction  of gross   per unit
  202606   online            125        112,500         2,250      2.0%      18.00
  202607   online            160        130,000         6,500      5.0%      40.62

E-STORE: deduction 2.0% of gross -> 5.0%  (+3.00pp)
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

`--channel` picks the side (default the online one), `--was` and `--now` take
month lists in either spelling (`2606` or `202606`), and with neither it
compares the last three months in the folder against the three before.

## What it will not tell you

- **Where a deduction was booked** is the export's decision. A rebate posted
  against the account rather than the model lands on that account's rows and
  on no particular product, which reads as a rate across everything that
  account bought.
- **When it was earned.** A true-up lands in the month it was settled. A rate
  that jumps for one month and falls back is that, and the monthly trend above
  it is what shows it.
- Returns are in by default, as everywhere else; `--no-returns` takes them out.

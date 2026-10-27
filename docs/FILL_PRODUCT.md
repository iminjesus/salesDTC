# Rows for the product master, for the codes it has not got

```powershell
py tools\lead_time.py --blank --out docs\unplaced.csv
py tools\fill_product.py --in docs\unplaced.csv --out docs\product_add.csv
```

`--blank` says which codes the orders use and the master cannot place. This
writes the rows to add, **in the master's own format** - its header, its
column order - so the block can be pasted straight in.

Nothing here invents a classification. Every row is filled from evidence the
folder already holds, and `product_add_why.csv` beside it says what that
evidence was for each one:

| `from` | |
|---|---|
| `plan` | the promotion plan names a category for the code, and the codes already in the master under that same plan category agree on a product chain |
| `code SM-X` | no plan line, but every master code starting `SM-X` carries one chain. `SM-X940NZAIXSA` and `SM-X940NZAAXSA` are one product in two colours, and a shorter prefix still separates a tablet from a phone |
| `-` | neither. The row is written with its levels empty, to be filled by hand |

The prefix is taken on the code **as written**, punctuation and all: `SM-X` is
four characters, where the normalised `SMX` is three and would be let through
by any threshold that also let `SM-` through. A prefix match must be
**unanimous** - a split prefix is a guess about nothing - while a plan
category takes the majority, since a category with a hundred codes in it will
have an odd one filed strangely.

## What to look at before pasting

The run ends with the rows that rest on thin or split evidence, worst first:

```
filled from: plan 28, code 3, - 1
  3 row(s) rest on thin or split evidence - look at these before pasting:
    RF71DB9956QDSA      plan                      1/1   CE / DA / REF
```

`1/1` is one code agreeing with itself - true, but one row. `3/5` is a
majority with two dissenters. Both are written; both are worth a look.

Only the **level** columns are filled - Biz, Div 1, Div 2, Div 3, Range,
whichever of them the master has. Everything else in the row, a marketing name
among them, is left empty: the folder has no evidence for it and a guessed
product name is worse than a blank one.

`--known` also writes the codes the master already has a row for whose levels
are only partly filled. Those are a different job - one cell to fix, not a row
to add - so they are left out by default.

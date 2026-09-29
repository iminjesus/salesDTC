# Do the shipped online orders turn up in the profit file?

```powershell
py tools\reconcile.py --statuses    # list the order statuses and how each is read
py tools\reconcile.py               # -> docs\reconcile_sku.csv
```

Two files counting different things. `26 DTC Aug` is **online orders**, and an
order placed is not a sale: one that has not shipped is not August revenue.
`profit_2608_3` is **sales, online and offline together**, so its online half
is what the shipped orders should have become.

So the comparison keeps the orders whose status says they shipped, keeps the
profit rows whose customer is online, and puts them side by side by product.

## Read the statuses first

Which statuses mean shipped is a judgement about your own process, so the run
prints every one with what it would do:

```
order statuses in 26 DTC Aug.csv (20 of them):
  status                            lines      units        revenue   read as
  COMPLETED                         3,279      4,086      1,762,288   shipped
  SHIPPING_PREPARATION                865      1,105        436,233   not shipped
  DELIVERED                           719        896        356,104   shipped
  CANCELLED                           478        610        259,737   not shipped
```

A **return is not a state of shipping**: the order shipped and then came back.
The profit file counts quantity net of returns, so a completed return nets to
nothing there and counting it as a shipment would invent a gap. Every
`RETURN_*` status is therefore read one way and left out, rather than some
landing in shipped on the word "completed" and others in not-shipped on
"refunded".

Anything it cannot read either way is **left out and named**, never guessed at.
`--shipped "COMPLETED,DELIVERED,PICKED_UP"` replaces the built-in list with
yours; everything not named is then not shipped.

`--statuses` stops there, which is the right first run.

## Units, not money

Both files carry a quantity that means one thing - a unit shipped. The amounts
do not: they differ by tax, by currency, and by what each file counts as
revenue. So units are the comparator and money is reported beside it, with the
ratio:

```
                            shipped orders      online sales      difference
  units                              4,982             4,447            -535
  amount                         2,118,393         2,078,171         -40,221
  units matched                      89.3%
  amount ratio                       0.981   (the two count money differently;
                                              a steady ratio is a basis, not a gap)
```

A ratio that holds steady across products is a basis difference. One that moves
about is a real gap.

## What it looks for

| Bucket | What it means |
|---|---|
| **agree** | same units on both sides, within `--tolerance` (0.5 by default) |
| **differ** | in both, units do not match |
| **orders only** | shipped, but the profit file has never heard of it |
| **profit only** | sold, but no shipped order for it |

A profit file that splits a line across payers leaves fractions behind, so a
small difference is rounding rather than a missing sale - hence the tolerance.

Each product also carries **units still to ship**, which is what the
unshipped orders hold. Where the profit file shows *more* units than shipped,
that column is the first thing to compare the excess against, and the run says
how often it accounts for it:

```
4 product(s) show more units sold than shipped. For 3 of them the excess is no
larger than what is still waiting to ship, so the profit file counted orders
the order file has not shipped yet.
```

## The online half of the profit file

The profit rows are filtered to the online channel, which comes from the
customer master the same way the profit chart does it - the account name says
which side of the business a payer is on. The split is printed, so what is
being left out is visible:

```
profit rows by channel (the comparison keeps E-STORE):
  E-STORE                      69 rows       4,447 units        2,078,171
  OFF-LINE                    900 rows       3,970 units        4,122,891
```

`--online ""` compares against every channel instead, and `--online OFF-LINE`
against the offline half - useful for showing that an unmatched product went
out through a different channel entirely.

## What comes out

`docs\reconcile_sku.csv`, one row per product: where it was found, order lines,
shipped units, sales units, the difference, units still to ship, and all three
amounts. Sorted by the size of the unit difference, so the worst is first.
UTF-8 with a BOM, so Excel opens it without the import wizard.

# Which orders became the month's sales

```
py tools\cohort.py                 # the whole test
py tools\cohort.py --profile       # describe the two order files and stop
```

The hypothesis under test: **August's sales are August's COMPLETED orders, plus
the July orders that were not COMPLETED in July and completed later.**

That is a claim about the data, so the data is asked rather than taken at its
word. Every order line goes into a bucket by which file it came from and what
its status says, several readings of the month are built out of those buckets,
and each one's predicted units are compared with the profit file's.

Units are the comparator, never money: both files carry a quantity that means
one thing - a unit shipped - while the amounts differ by tax, by currency and by
what each file counts as revenue.

## Read the output in this order

**1. Does either file carry a second date?** The profile names any shipping,
delivery, completion or invoice date it finds. If one is there and filled in,
none of this inference is needed: the month a unit belongs to is read off the
row, and the right thing to do is use that column instead.

**2. Do the two files share order lines?** This decides everything after it.

- **No shared lines** - `26 DTC Aug` is a month of orders. July's carry-over is
  *not* in it, so adding July's unfinished orders is a real correction and the
  hypothesis is worth testing.
- **Shared lines** - `26 DTC Aug` is the **order book**, and the July lines are
  already inside it with a later status. Adding July again counts those units
  twice, `Aug COMPLETED only` is already the hypothesis, and the run says so
  before scoring anything.

Where lines are shared, the status each line carries in the two files is a
before and an after - the only direct evidence either export holds about *when*
something moved. `PAYMENT_PENDING -> COMPLETED` between a July file and an
August one means that line completed in August.

**3. How finished does each file look?** A month-end snapshot leaves plenty of
units in flight. A file re-exported months later has almost nothing left open -
and then it cannot say when anything moved, only that it eventually did. The run
prints the percentage so the file can be judged rather than assumed.

## The readings it scores

| Rule | What it would mean |
|---|---|
| Aug COMPLETED only | the month is its own completed orders and nothing else |
| Aug COMPLETED + Jul not-completed | the hypothesis, loosely: every July order still open at the end of July landed in August |
| Aug COMPLETED + Jul open that later completed | the hypothesis, strictly - needs the two files to share lines |
| Aug COMPLETED + Jul COMPLETED | both months booked in August, which would mean July was not booked in July |
| every Aug order, whatever the status | the month is everything ordered in it |
| Aug shipped-ish | COMPLETED, DELIVERED, SHIPPED and the rest of `reconcile.py`'s list |

Two numbers score each one:

- **vs sales** - the predicted total against the profit file's.
- **per-product err** - every product's miss added up in both directions,
  divided by the month. This is the one that matters: a rule can be right in
  total by cancelling a product it overstates against one it understates, and
  the per-product figure refuses to let it hide there.

`--completed` renames the status(es) that mean the money was booked; the default
is `COMPLETED` alone. `--before` and `--after` name the two exports.

## What comes out

A ranked table, a verdict on the hypothesis in one sentence, the worst-fitting
products, and `docs/cohort_sku.csv` with every product's buckets side by side -
sold, the winning rule's prediction, and each bucket that fed it, sorted by the
size of the miss. That file is where a rule that fits in total but not in detail
gives itself away.

## What it cannot do

It cannot see a shipment. Every answer here is inferred from a status and the
file a line sits in, and the inference is only as good as the status being a
faithful record of when the money was booked. If the order export can be made to
carry a shipping or invoice date, this test stops being necessary - and so does
the allocation the profit page runs on, which is described in `docs/PNL.md`.

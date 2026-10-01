# Which orders became the month's sales

```
py tools\cohort.py                 # the whole test
py tools\cohort.py --profile       # describe the two order files and stop
```

**The months are found, not named.** The profit file says which month it covers,
and the order exports named for that month and the one before it are the ones
read - `26 DTC Aug` and `26 DTC Sep` for `profit_2609`. An export whose order
dates say it is another month stops the run rather than being tested anyway;
`--before`, `--after` and `--any-month` override all of that. Every rule is
named after the months it is actually about, so a run explaining September never
prints a table that says August.

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

Shared **lines** are `(order number, product)`. An order split across the cut -
one product fulfilled in July, another in August - shares its *number* without
sharing a line, so the order numbers are compared separately and reported on
their own. Numbers in both with no product in common is one order cut across two
months; no numbers in both at all means the files are cut by the order and
nothing crosses between them, which leaves the statuses as the only evidence.

Where lines are shared, the status each line carries in the two files is a
before and an after - the only direct evidence either export holds about *when*
something moved. `PAYMENT_PENDING -> COMPLETED` between a July file and an
August one means that line completed in August.

**3. How finished does each file look?** A month-end snapshot leaves plenty of
units in flight. A file re-exported months later has almost nothing left open -
and then it cannot say when anything moved, only that it eventually did. The run
prints the percentage so the file can be judged rather than assumed.

## How a status is read

A status does one of three things, and which list it is in is the whole model:

| | |
|---|---|
| **books this month** `+` | `COMPLETED`, `PICKUP_COMPLETE` |
| **takes money back this month** `-` | `RETURN_COMPLETED`, `RETURN_REFUNDED`, `PARTIAL_RETURN_COMPLETED`, `PARTIAL_RETURN_REFUNDED` |
| **waits for a later month** | everything else - `SHIPPED`, `SHIPPING_REQUESTED`, `READY_FOR_PICKUP`, `RETURN_SHIPPING_PREPARATION`, `CANCELLED`, the `WAITING_*` family |

Returns are **subtracted, not dropped**. The profit file counts quantity net of
returns, so a return completed in September is already taken out there; dropping
it on the order side would leave the two counting different things.

Matching is on the **whole status**, never a word inside it: `RETURN_REFUNDED`
is money back and `RETURN_SHIPPING_PREPARATION` is a return that has not landed
yet, and nothing but the exact name separates them.

`--positive` and `--negative` move a status between the lists. A status in
neither waits, so a new one that appears in a later export is carried forward
rather than silently booked.

The run prints **the status list read two ways** - the signed reading beside the
COMPLETED-only one it replaced - so the difference between them is a number
rather than an argument.

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

A **cancelled or returned** order is left out of the open buckets: it was called
off or came back, so it is no part of a later month. `--keep-dead` counts them
anyway, which is worth one run to see how much they were worth.

## Where the miss sits

The per-product error is split three ways, because they are three different
problems:

| | |
|---|---|
| **in both** | the orders and the profit file disagree about a product both have - the real fit |
| **ordered, never sold** | a product ordered every month that never reaches the profit file. Usually not merchandise at all: a service plan, a subscription, a bundle header. `--skip-sku PREFIX` leaves them out |
| **sold, never ordered** | sold with no online order behind it - an offline row that slipped the channel filter, or a code the two files spell differently |

## The month in and out

The last block is what the test was for: how much of the month was its own, how
much came in from the month before, and how much it hands on. When a month takes
in more than it hands on, its revenue is **flattered by the difference** - a
backlog cleared, not demand earned in the month - and the run says so.

## What comes out

A ranked table, a verdict on the hypothesis in one sentence, the worst-fitting
products, and `docs/cohort_sku.csv` with every product's buckets side by side -
sold, the winning rule's prediction, and each bucket that fed it, sorted by the
size of the miss. That file is where a rule that fits in total but not in detail
gives itself away.

## The one test it was not fitted to

```
py tools\cohort.py --next-profit profit_2609
```

Everything else is scored against the month the rule was *chosen* on, so it had
every chance to fit. What the month carries out is a claim about a month the
rule never saw: those units have to turn up in it. The run reports how much is
carried out, how much the next month sold, and - product by product - how much
of the carry-out **will not fit** in what that month actually sold.

This cannot prove the rule. It is the thing that would have disproved it: a
carry-out larger than the month it lands in is wrong whatever else fits. Past a
quarter not fitting, the run says so in those words.

The full out-of-sample test needs the **next month's order export** as well,
which turns the check into the same scoring run on a second month. Two months
reproduced by one rule is not a coincidence; one is.

## What it cannot do

It cannot see a shipment. Every answer here is inferred from a status and the
file a line sits in, and the inference is only as good as the status being a
faithful record of when the money was booked. If the order export can be made to
carry a shipping or invoice date, this test stops being necessary - and so does
the allocation the profit page runs on, which is described in `docs/PNL.md`.

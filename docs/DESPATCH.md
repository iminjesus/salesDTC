# When an order actually left

```
py tools\despatch.py                 # every orders_* export in the folder
py tools\link.py                     # join those to the store's own export
```

`tools/cohort.py` had to **infer** which month a unit belonged to, because no
export said. SAP's sales-order export says: `Created On` is when the order
arrived, `Goods Issue Date` is when it left, and the difference is the whole
question. No join and no store export are needed to read it.

## The trap in Goods Issue Date

SAP fills that field on **every schedule line**, delivered or not. On a line that
has gone it is the day it went; on one that has not it is the day it is *meant*
to go. In the September export, 2,810 lines carry a goods issue date **later
than the day the export was taken** - including 1,360 the status column calls
Completed.

They are not the same kind of fact, so the run never adds them together:

| | |
|---|---|
| **left** | delivered, and the date is on or before the day the export was taken |
| **due to leave** | everything else with a date - a schedule, not a measurement |
| **no date at all** | neither |

The day the export was taken is taken to be the last order it recorded, which
is right for a month-end pull and wrong for one taken later. Being wrong there
reports despatches that **did** happen as merely scheduled, which understates
every month's measured carry-over - so when a folder's exports were all pulled
recently rather than each at its own month end, say when with `--as-of`. The run
prints which day it is using and where it got it.

## Where a month's units went

```
the carry-over ladder - ordered down the side, despatched across the top
  (a date past the day an export was taken is a schedule, shown in brackets)
  ordered in        26-06        26-07        26-08        26-09        open
  2026-06           9,194    0 (4,109)      0 (168)            -           0
  2026-07               -        9,514    0 (3,819)      0 (138)           0

  month        own demand   carried in   carried out        net
  2026-06           9,194            0         4,277     -4,277
  2026-07           9,514        4,109         3,957       +152
```

One row per month an order **arrived** in, one column per month it **left** in.
The diagonal is a month earning its own demand. To the right of it is that
month handing revenue forward; below it in a column is a month being handed it.
Nothing is inferred - every cell is a goods issue date against a creation date.

The brackets are the whole point of the layout. A bracketed cell is a date that
had not come when the export was pulled: a plan, not a measurement, and no
amount of it is evidence that the units moved. Reading the ladder means reading
the unbracketed numbers as fact and the bracketed ones as intent.

Underneath, each month as three numbers and their result:

| | |
|---|---|
| **own demand** | ordered in the month and left in it |
| **carried in** | left in the month, ordered before it - revenue the month did not earn |
| **carried out** | ordered in the month, leaves after it - revenue it earns for a later one |
| **net** | carried in minus carried out. Positive and the month's revenue is **flattered** by a backlog clearing; negative and the month sold less than it sold for |

A month at the right-hand edge of the ladder always looks like it carries
everything out, because the exports cannot see past themselves. Only a month
with a full month of export after it has a carry-out worth reading.

## A month cannot measure its own tail

An export of September pulled on 30 September shows 73% of the month's orders
gone and 26% still scheduled. That 26% is not late - it has not happened yet,
and it is missing from the file rather than visible in it. Any cumulative share
read off such an export is a share **of what has gone so far**, and it only
falls as the rest goes.

To settle a month, re-export it after it has had the runway: same `Created On`
filter, pulled two months later. The run prints each export's runway and marks
the short ones.

## One export per month

The same export often sits in the folder twice, as a csv and as a workbook. A
spreadsheet round-trip renames headers and turns a number into text, and nothing
downstream can tell that apart from a column that moved - so **the csv wins**,
the duplicate is named rather than read, and `tools/link.py` walks the
candidates and takes the first that actually carries the columns it needs
instead of failing on the newest name.

## The month a unit belongs to, with nothing inferred

`py tools\link.py` reads **every** `orders_*` export, joins each to its own
month's store export, and pools the result by the month the goods actually left:

```
revenue by the month the goods actually left
             left   still only due
  2026-08   ...            ...
  2026-09   ...            ...
  2026-10     0            ...
```

Then it puts each month's total beside what `profit_<month>` reports for the
same channel - total, and per product. **No status is read and no carry-over is
inferred.** A unit is in the month its goods issue fell in, whatever month it
was ordered in and whatever the store's status column says.

That last point is the one that matters. The store's `COMPLETED` is not the
revenue event - the goods issue is, and the store's status follows it rather
than leading it. The join shows lines whose goods issue was 29 September sitting
under a SAP status of `Open`, which is exactly the gap the status-based model in
`docs/COHORT.md` was trying to bridge by inference.

Three readings are scored against the profit file:

| | |
|---|---|
| **left** | despatched on or before the day the export was taken - measurement only |
| **left + due, through the store join** | adds what was scheduled. A month's revenue is both, and only the first half is measured |
| **left + due, SAP alone** | the same, counted straight off the SAP lines that carry a store reference |

The last one is the one to read. The join exists to prove the key works and to
show the store's own view of an order; the **measurement does not need it**, and
going through it costs units - one store order can become several SAP documents
with different despatch dates, and the join keeps one. On September that was
1,070 units, 5% of the month.

A month can only be scored where the exports can see all of it: September's own
export, taken on 30 September, knows nothing of what left in October. The run
says when the latest export was taken so a short month is not read as a settled
one.

## What it is worth

The status-based inference in `docs/COHORT.md` put September's carry-out at 27%
of the month. The SAP export, by a completely different route, says 26% had not
left by month end. Two methods that share no assumption landing in the same
place is the strongest thing either of them has said.

`tools/link.py` joins these orders to the store's own export on
`Customer Reference (Header)` with the date stamp removed, which is what carries
the despatch date into the world the profit page lives in.

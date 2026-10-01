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

The day the export was taken is taken to be the last order it recorded;
`--as-of` overrides it.

## A month cannot measure its own tail

An export of September pulled on 30 September shows 73% of the month's orders
gone and 26% still scheduled. That 26% is not late - it has not happened yet,
and it is missing from the file rather than visible in it. Any cumulative share
read off such an export is a share **of what has gone so far**, and it only
falls as the rest goes.

To settle a month, re-export it after it has had the runway: same `Created On`
filter, pulled two months later. The run prints each export's runway and marks
the short ones.

## What it is worth

The status-based inference in `docs/COHORT.md` put September's carry-out at 27%
of the month. The SAP export, by a completely different route, says 26% had not
left by month end. Two methods that share no assumption landing in the same
place is the strongest thing either of them has said.

`tools/link.py` joins these orders to the store's own export on
`Customer Reference (Header)` with the date stamp removed, which is what carries
the despatch date into the world the profit page lives in.

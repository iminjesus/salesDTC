# What a month's revenue was ordered in

```powershell
py tools\order_lag.py --month 2607
py tools\order_lag.py --month 2607 --campaign "S26 Launch" --out docs\lag_2607.csv
```

The profit page bands a line by the day it was **ordered** and sits it in the
month it **left**. So a campaign that closed on 8 April keeps a row in May,
June and July. That is the rule - and whether a four-month tail is really in
the data is a different question, which this answers off SAP's own two dates.

```
what left in 202607, by the month it was ordered
  ordered     lag   lines       units    share          amount
  202603        4       2           5     4.6%           9,100
  202604        3       1           1     0.9%           2,400
  202606        1       1           5     4.6%           9,000
  202607        0      40          97    89.8%         217,824

ordered 2+ month(s) before it left: 3 line(s), 6 unit(s), 11,500
  by campaign:
    S26 Launch                          dtc              5 unit(s)
    S26 Launch + Tech Fest              dtc              1 unit(s)
  the longest-waiting lines:
    order                 sku               ordered     left           units  campaign
    AU260315-11111        SM-S948BZSFATS    2026-03-15  2026-07-04         3  S26 Launch
    AU260320-11112        SM-S942BZKEATS    2026-03-20  2026-07-18         2  S26 Launch
```

**Carried in is not "last month".** `tools/sap.py` buckets a line by comparing
two months and nothing else:

```python
if gi_m == month:
    which = BOOKED if made_m == month else CARRIED_IN
```

Anything that left in the month but was ordered before it is carried in,
whether that was four weeks or four months earlier. The lag column says which.

`--least N` sets how long a line has to have waited to count as a tail
(default 2 - a month of lag is ordinary). `--campaign` narrows to one
campaign's lines, and `--out` writes every line read, with its order number,
both dates, the lag, the units, the money and the campaign - which is the file
to send when someone asks what a band is made of.

Lines that came back as a credit are **in**, the same as everywhere else;
`--no-returns` takes them out.

## What it does not cover

Only what the SAP order export carries. A **credit or a return** usually
arrives as its own document, not as an order line, so it is in the profit file
and not here. That matters for reading a band's tail: the page splits a
combination's **whole month** - credits included - across the bands its orders
came in on, so a June credit against an old order lands on that old campaign
without any line appearing in this report. A tail with money but no units in
this report is that, not late despatch.

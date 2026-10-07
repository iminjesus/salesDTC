# The wide P&L: database, structure, chart

The profit export is a wide profit-and-loss file - a couple of hundred amount
columns where a total and the lines behind it sit side by side. Nothing in the
file marks which is which. The asterisks in the header are a habit of the export,
not a guarantee, so the tooling here reads the numbers instead.

**Which file gets read.** The tools take the highest-numbered `profit_*` file
in the folder - `profit_2608_3` over `profit_2608_2` over `profit_2608_1` - so a
re-cut export needs no code change, only the file dropped in. `--file NAME`
picks a different one. Both commands print the name they chose.

Columns move between cuts, which is the point of reading the structure from the
numbers: a renamed, added or dropped column changes the tree rather than breaking
the run. A relation that no longer adds up is simply not reported, and the column
turns up under **Not part of any total** in the report.

Two commands. The first loads and analyses, the second draws.

```powershell
py tools\analyze_structure.py          # -> rawdata\sales.db, docs\structure.md, docs\structure.json
py dashboard\build_pnl.py --open       # -> dashboard\pnl_2608.html
```

## 1. The database

Every file in `rawdata\` becomes a typed SQLite table in `rawdata\sales.db`.
Columns that hold amounts are `REAL` so SQL can sum them; everything else stays
`TEXT`, because a customer number with a leading zero is not a number.

Two extra tables come with it:

| Table | What it holds |
|---|---|
| `column_map` | original header, SQL column name and type, per table |
| `structure` | the discovered relations as `parent, child, sign, ordinal` |

So the analysis is queryable too:

```sql
SELECT child, sign FROM structure WHERE parent = '*Net Sales' ORDER BY ordinal;
```

Nothing leaves the machine and no server is involved - SQLite is a single file.

## 2. What adds up to what

For every amount column the analyser looks for a set of other columns that adds
up to it **on every single row**, and keeps only what holds exactly. A relation
that is off by a cent on one row of eleven thousand is not reported.

It works in this order:

1. **The layout.** An export prints a total and then its own lines, so the block
   that follows a column is tried first. A line that is itself a total has its
   own lines skipped rather than counted twice.
2. **Two subtotals, then three.** What the layout leaves standing usually turns
   out to be a difference - net sales as gross less deductions, operating profit
   as gross margin less operating expense.
3. **Peeling.** The catch-all for a total whose lines are scattered through the
   row: take off whatever shrinks the remainder most, until nothing is left.

Two rules keep the results honest:

- **A column may not be explained by anything it is already part of.** Otherwise
  `gross sales = amt + other` gets rearranged into `amt = gross sales - other`,
  which is true and useless.
- **Columns named like identifiers are left out of the arithmetic.** A customer
  number, a material code and a Nielsen id all parse as numbers and none of them
  is an amount.

Relations found early can only draw on the subtotals known at the time, so a
final pass replaces each one with its shortest form.

The result lands in `docs\structure.md` as a tree plus a list of relations, each
with the worst gap it was checked to:

```
- `*Net Sales` = `*S.Gross Sales` - `*Sales Deduction`  (holds on all 11,573 rows, worst gap 0.0000)
```

On a 251-column, 11,573-row export the whole run takes about ten seconds.

## 3. The chart

`dashboard\build_pnl.py` turns that into one self-contained page: one bar for
gross sales, a stack beside it for sales deduction, cost of goods sold and
operating cost, and a line for operating profit over net sales. Same shape as
the Sales Dashboard's profit chart (`new-sales2`, branch
`claude/crawl-product-pricing-Hafp4`) - two stack names on a stacked x axis so
the pair sits centred on each tick, the line last so it takes no column of its
own - drawn across the members of a dimension rather than across months.

### How customers are divided

The account name only says which side of the business a row is on, so it is
reduced to a **Channel**: anything marked off-line becomes `OFF-LINE`, anything
else - `E-STORE`, `E-STORE_B2B` and the rest - becomes `E-STORE`. The detail
comes from the levels underneath:

```
Channel  ->  Type  ->  Portal Group  ->  Type2
```

`tools/customer.py` holds that rule, so this page and `build_dashboard.py`
divide customers the same way. Reordering `LEVELS` there reorders both.

**The page opens on `E-STORE`.** The offline rows are still in the file:
setting Channel to *All* steps up and brings them back for comparison, which is
also what puts `Channel` on the x axis as two bars side by side.
`--start-channel ""` opens on everything instead.

### Time on the x axis

The build draws **every** `profit_*` export in the folder, and the page is one
chart with **a bar per month**. Not a month behind a button: the whole span at
once, because what a month did only means something next to the months around
it.

The months arrive separate - each read from its own export, with its own
customers, its own products, its own column positions - and are joined **in the
page, by name**. A customer is the same customer in two months when it is spelt
the same; a figure is the same figure when its key is. Index 3 in August's
Division list is not index 3 in February's, so nothing is matched on position,
and a month missing a level reads as the placeholder rather than shifting
everything along.

Narrowing does not change the axis. Click the **MX** band and the same months
come back with only MX in them - which is the comparison the click was asking
for. The split then steps down to the level below, so MX becomes Mobile and
Wearable across the year.

The eight biggest members take a colour **across the whole span**, not per
month, since a stacked bar on a time axis cannot be read at all if a colour
means something different in each column.

With one month in the folder the button row is not there at all.

`--months` picks which ones go on it: `--months 2607,2608` draws those two, and
`--months -2609` draws every month **but** September. Use it for a month whose
sales have not settled yet - an export pulled before the month's despatches
finished is not wrong so much as incomplete, and a month like that sitting on
the page beside settled ones reads as a collapse rather than as a month still
filling in. The run names what it left out.

### One menu

Everything that drives the page is in the card at the top - both charts read
the same levels, so there is one set of controls rather than one per chart.

**A chain is one line.** Its levels run in order, each a name and its members,
and the members are joined into a block so a level reads as one control:

```
CUSTOMER  CHANNEL [All|E-STORE|OFF-LINE]  TYPE [All|EPP|S.com]  PORTAL GROUP [All|PG0|PG1] ...
PRODUCT   DIVISION [All|DA|MX|VD]  CATEGORY [All|FRIDGE|PHONE|TV]  ...  SKU [All (60) v]
```

The **name** puts the bars on that level; the one they are on is underlined in
the accent colour. The **members** narrow to one value, and *All* widens back.

A level whose members outnumber `BTN_MAX` (eight) gets a **search box** instead
- Range and SKU are lists to search, not rows to scan. The search is loose on
purpose, because these lists are zero-padded keys and half-remembered names:

| Typing | Finds | |
|---|---|---|
| `sku023` | `SKU023` | the whole thing |
| `sku` | `SKU023` | the start of it |
| `23` | `SKU023` | anywhere inside |
| `sku23` | `SKU023` | the padding is not part of the key |
| `gs24` | `GALAXY-S 24` | the letters in order, from three characters up |

Case, spaces and punctuation are ignored throughout. Two words mean both, in
any order - `sku 23` and `23 sku` are the same search - and a word nothing
matches drops the value, so narrowing always narrows. Matches are ranked by
which of those lines caught them, exact first and a guess last, with the part
that was caught picked out in the list. Enter takes the top one, the arrows
walk them, Escape or a click outside closes.

The levels cascade: each only offers what the levels above it leave available,
so picking a Type leaves Portal Group listing that Type's values and nothing
else. *All* is marked as current without being marked as a choice - an
untouched page should not read as eight selections.

Where a level has no value for a row the build writes a placeholder in brackets
- `(blank)`, `(no customer match)`. Those are somewhere to put the money, not
somewhere to go, so they stay off the menu unless one is already what is being
shown, in which case its button is there to step back out of. The rows behind
them are untouched: still in every total, and still a bar and a slice of a
stack. `--find` and `--where` are what chase them down.

### The rest of the menu

| Control | What it does |
|---|---|
| **click a bar** | open that member, and move the bars to the next level |
| the breadcrumb | go back to any step of the path; **All** returns to the top. It lists **every** narrowing in force, from either chain, and ends with what the months are split by |
| **← Back** | widen the deepest narrowing, whichever chain it was in |
| a level name | split each month by it, clearing what was narrowed at and below it |
| **P&L** | the whole statement **for whatever is picked to its left**. A view of its own, not a figure - picking a Stack by or a Figure leaves it |
| **Stack by** | **Customer**, **Product** or **When ordered** - what splits each bar |
| **Figure** | **Net Amount (AUD)** or **Qty** - the same two in every stack mode |
| **Period** | **Month** or **Quarter** - how wide a bar is |
| **Cumulative** | each bar becomes the running total up to and including it |
| **Amount / % of bar** | sizes between bars, or the mix inside each one. Not in P&L mode, where there is no mix |
| **Numbers** | the totals behind the chart, and the profit split by where the order came from. **Off by default** - the page is the chart |
| **Table** | every figure behind the bars, with quantity, ASP and the margin |
| **Reset** | back to the opening view |

### Orders, and the month they belong to

The page needs to know which month a unit's revenue fell in. There are two ways
to find that out, and it prefers the one that does not guess.

**Measured - where SAP's sales-order exports are there.** `orders_<month>`
carries `Created On` and `Goods Issue Date`, so the month a unit earned in is
**read** rather than argued for. It also carries the **payer** - the same
`Sold-to Party` the profit file is keyed on - so a line lands on one customer at
full depth with nothing spread anywhere. Only the lines whose customer reference
carries the store's own stamp (`AU260930-46262020`) count: Amazon, Myer, MyDeal
and eBay carry something else, so the shape of the reference separates the
business with nothing to configure.

```
booked       left in this month, ordered in this month    its own demand, earned
carried in   left in this month, ordered before it        earned here, ordered there
carried out  ordered in this month, leaves after it       a later month's revenue

the month's revenue    = booked + carried in
the month's own demand = booked + carried out
```

**Inferred - where they are not.** The store's own export has no despatch date,
so which month a unit belongs to has to be argued from its status; and the
portal group it carries cannot settle a customer at full depth, so each order
has to be spread across the sales it is consistent with. `docs/COHORT.md` is
where that reading gets scored against the month it claims to explain.
`--no-sap` forces it.

`docs/DESPATCH.md` puts the two side by side. On September the measured answer
came back at **99.8%** of the month against the inferred answer's **96%**, with
less per-product error - which is why the measured one goes first. The build
says which basis it used and how it came out against the month as sold.

A cancelled or rejected order belongs to no month and is in none of the three.

There used to be a **Basis** control that read the whole page on one of those
slices. It is gone: the profit split above the chart prints all three at once,
which is what it was being used to read, and one number beats a mode you have to
remember you are in.

The build prints the same split outright, so the carry-over's own profit is a
number on the way past rather than something to go and switch to:

```
  what the month earned, by the month the order came from
                                       units           gross       op profit   margin
  ordered in 202609 and earned in it  18,193      11,876,810         593,840     6.1%
  ordered in 202608, earned in 202609  2,494       1,621,123          81,056     6.1%
  = the month as sold                 20,687      13,497,933         674,896     6.1%
  ordered in 202609, earns in 202610   1,710       1,129,810          56,490     6.1%
```

and the page says it two ways: the **profit split** above the chart, for the
whole span, and **Stack by: when ordered**, month by month. A carry-over that
converts at a different margin from the month's own demand is the thing this
whole split exists to show, which is why both carry a margin as well as a size.

*Carried out* is the only one of the three that is not a measurement: the month
it lands in has not happened, so its units are priced at this month's rates. It
is printed on the build and kept out of the chart for that reason.

Off *Sales*, every figure is an **allocation**: one multiplier per key, applied
to the money and the units alike. It holds exactly as far as the units of one
key being worth the same as each other - the assumption the per-unit view
already runs on - and the subtitle says so while it is on. Both ratios are
modelled over modelled, so the model's own fit against the month does not leak
into the figures; what it changes is the **mix**, which is the point of asking.

A key the orders never reached weighs nothing, and the build says how much of
the month that leaves out.

### How an order finds its sales

The order export knows its portal group and its product. It does not know the
payer, so it cannot say which Type2 an order belongs to when the accounts behind
a group disagree - and keyed at full depth it would never meet the profit file
at all.

So an order is **spread across the sales it is consistent with**: the
combinations that agree on every level the order does assert, in proportion to
the units each one sold. An order for 100 EPP units of a SKU lands on the EPP
rows of that SKU, in the shape those rows already have. The build prints which
levels the match was made on, and how many units found nothing to be.

The portal group is resolved through `portal_levels` in `tools/promo_match.py`,
which indexes the customer master under every spelling of every level and
returns only what the accounts behind a group agree on. `--agree` sets how much
agreement that takes.

The build then says what the model makes of the month beside what was sold. A
gap wider than 15% means the booking rule does not describe this export, and it
says to go and run `tools/cohort.py` rather than leave the page quietly wrong.

### One chart, two modes

There were two charts: a P&L under a stacked breakdown, on **different x axes**.
Reading one against the other meant holding two sets of labels in your head, and
drawing them on top of each other was worse - four stacked costs beside eight
stacked categories is two questions answered at once and neither of them
clearly.

So there is one chart, in one of two shapes:

| | |
|---|---|
| **P&L** on | the statement: **two bars a period** - the gross, and what it went out on stacked beside it |
| **P&L** off | **one bar a period**, split by whatever Stack by names, in whichever Figure |

P&L sits **after Figure**, and apart from it. It is not a figure - a figure is
a measure a split can cut, and the P&L is the whole statement with no split -
and it comes last because it reads whatever everything to its left has narrowed
down to. Drill into MX and press it and you get **MX's** P&L, not the file's.
Operating profit is not in the Figure row for the same reason: it is already a
band of this view.

Stack by and Figure stay on the menu while it is on, and **picking one leaves
the P&L** - which is what pressing a control that is plainly there should do.
They were hidden for one commit, which meant a page that opens on P&L opened
with most of its controls missing and nothing saying why. Only **Scale** goes,
since normalising to 100% is about a mix and the P&L is not one.

That separation is also what holds the y axis still. The three figures are the
same in **every** stack mode, so there is no figure one mode has and another
does not, and nothing is swapped out underneath the reader. While P&L was in the
Figure row, choosing **When ordered** from it fell through to Operating Profit
and the axis dropped from 3,500,000 to 900,000 - a different measure, not a
different calculation, but it read as the chart disagreeing with itself.

The profit line is on both shapes, each point labelled with its own figure, so
switching between them never loses it. There is no right-hand axis: a line that
writes its value over every point has nothing left for a scale to say, and
dropping it gives the bars the width back.

**Solid is the whole slice; dotted is a band of it.** Where the bars are split,
each band also gets its margin as a dotted line in its own colour. A stacked bar
says how big every member is and nothing at all about how well it did - and two
members the same size can be a long way apart on margin, which is usually the
question the sizes raise. Only the solid line's points are labelled; eight
labelled lines would bury the chart they are drawn over, and the dotted ones
are read against it rather than off a number. They are drawn faint, and with no
point markers, for the same reason: at full strength eight of them read as the
chart and the bars underneath read as the background, which is backwards.

Choosing **Qty** gives the units split with the profit line over it and **no
cost bars**: costs share no scale with a count of units, and the same goes for a
bar normalised to 100%. Controls that do not apply disappear rather than greying
out, since a dead button still costs a row of a menu that is already tall.

### Month, quarter, year

**Period** sets how wide a bar is - a month or a quarter. Nothing else
changes: the same slice, the same split, the same figure, summed into fewer
columns. A month's `ym` is `YYYYMM`, so the quarter falls straight out of it,
and the months arrive in order so the columns do too.

The totals are the same whichever period is showing - that is the point of it
being a bucket rather than a different reading. Across every combination of
period and stack, the span comes to one figure.

**Cumulative** sits beside it, as a toggle rather than another period, because
it answers a different question: not how big each piece is but how the span is
tracking. Every bar becomes itself plus everything before it, so the last one is
the whole span.

It is applied to the **columns**, not to the drawn bars - so the bands, the
margin lines, the axis and the tooltips all cumulate together and cannot drift
apart. The profit line then reads as margin **to date**: profit so far over net
so far, which is the figure a year-to-date number is usually quoted at.

There was a **Year** period too, until this arrived. The last bar of a running
total is already the whole span, so drawing it as one bar was a third way to say
a number the page says twice over - and it is still there whichever period is
showing, which Year was not.

### The chart's own controls

Top-right, on the legend's row - not over the plot, where they covered whatever
the top of the chart happened to be:

| | |
|---|---|
| **← Back** | the same step as the menu's. By the time you have drilled three levels the menu is a long way from the bar you just clicked, and the step back belongs next to the step in |
| **⤡ Expand** | that chart takes the window and everything else stands down |

Expanding is also what turns **the number inside every bar** on. Off by default,
because three charts' worth of numbers on one page is clutter; on when a chart
is expanded, which is both the moment there is room for them and the reason
anyone expanded it. A segment too short to hold its text is left alone rather
than given a number that spills over its neighbours. **Esc** closes.

### Stack by: when ordered

A third way to cut the same revenue, beside Customer and Product: **not by who
bought it but by when the order behind it was placed.** Two bands a month:

| | |
|---|---|
| **Ordered this month** | the month's own orders, earned in the month |
| **Carried in from the month before** | ordered earlier, earned here |

plus a third in grey:

| | |
|---|---|
| **No order matched** | an offline row, a marketplace, or a code the two files spell differently |

That band is there so **the bar comes to the same total as every other way of
stacking it**. A month that reads smaller under one split than another is a
chart arguing with itself. It gets no margin line of its own - it is a residual,
not a cohort.

**Carried out** is still not in the bars: ordered this month, ships later, so it
is next month's revenue. Putting a projection in a bar of measurements would
make the bar mean nothing.

The figure defaults to **Operating Profit**, which is the question this view
exists for: how much of the month's profit the month actually earned, and how
much was last month's backlog clearing. Net Amount and Qty are still there; P&L
is not, since it is the whole statement and has no split.

A month knows its carry-in only when the month before it was read - so January
needs **December's order export in the folder**, even though December has no
profit export of its own and never appears on the chart. A month without it is
drawn **empty**, not as nil, which would claim it earned everything itself, and
the hint names which months those are.

**The y axis does not move when Stack by does.** It is scaled to the figure over
the whole slice, not to the bars actually drawn - so Customer, Product and When
ordered share one scale, and the figure carries across wherever both modes have
it.

This replaced a second chart under the first. That chart drew the same split
against the drill level instead of time, with a line for the share of revenue
the month's own orders earned; the split reads better as a band of the main
chart, on the same months as everything else.

### The profit split

Under **Numbers**, with the totals - off by default, since the page is the
chart and this is what gets pulled up when someone asks for the figure behind
it. Three figures and a total:

| | |
|---|---|
| This month's own orders | ordered in the month and earned in it |
| Rolled in from *the month before* | ordered before the month, earned in it |
| No order matched | sold with no order behind it - offline, a marketplace, or a code the two files spell differently |
| **Total** | **the profit export's own figure** |

The total is the one number that has to be right, so it is **not** split or
rebuilt: it is summed straight off the export with no share applied, and the
three rows are made to add back to it. "No order matched" is therefore a
residual rather than a figure in its own right, and any drift lands there
instead of in the total anyone quotes.

The first two rows come from sharing each combination's money on the share of
its units that came from each place. That holds as far as one combination's
units being worth about the same as each other - the same assumption the
per-unit view already runs on. Everything follows the filter, so drilling in
splits the slice rather than the month.

The same split prints on the build, with the export's own total marked.

### ASP

There was a **Per unit** mode that divided every bar by the quantity behind it.
It is one tile now - **ASP**, in the row under the menu - because that was the
only per-unit figure anyone read off it, and a mode you have to remember you are
in costs more than the one number it was carrying.

ASP is the weighted price: the totals divided, never the average of the rows'
own prices. It sits in the KPI row and in the table as `ASP`, always on net
sales over net quantity. The drill runs down to the **SKU**, so a category price
can be opened until the model behind it shows.

A group with no net quantity - returns cancelling its sales - has no price, so
it reads as a blank rather than a zero, which would read as "free".

`tools\asp.py` computes the same figures as csvs, for a spreadsheet rather
than a page; `docs\ASP.md` covers it.

### How a bar is cut

**Stack by** picks what splits each month's bar: the customer chain, the product
chain, or when the order came from. On a chain, the split is the first level
that has not been narrowed to a single value - so Channel split by Type, click
EPP, and the months come back as EPP alone split by Portal Group. The drill runs
the whole chain and carries on into the product side once the customer levels
are used up.

A cost is carried negative in the export, so the whole figure is flipped when
its total is: an **Operating Cost** stack stands up like the others, and a
member that really does run the other way still points the other way inside it.

**% of bar** normalises each month to its own total, so the mix inside a small
month reads as clearly as inside a large one. The tooltip keeps the amount
behind each share: a share with no size behind it is how a rounding error comes
to look like a trend. It is off the menu in P&L mode, which is not a mix.

The eight largest members get a colour each, **fixed across the whole span** - a
ninth folds into **Other** rather than being handed a generated hue. On a time
axis that is not a nicety: a colour that meant MX in one month and DA in the
next would make the chart unreadable.

Clicking a band and clicking a member button are the same act. Narrowing moves
the split down to the next open level; widening with **Back** or the breadcrumb
brings it up again.


Costs are drawn as amounts whichever sign the export stores them with. The six
figures are found by header name and the build prints what it matched:

| Series | Headers accepted |
|---|---|
| Gross Sales | `*S.Gross Sales`, `*Gross Sales`, `S.Gross Sales AMT`, then `*Net Sales` |
| Sales Deduction | `*Sales Deduction`, `*Delear Discount` |
| COGS | `*Cost of Goods Sold`, `COGS`, `*Ref. CoGS` |
| Operating Cost | `*Operating Expense`, `*Operating Cost`, `*Other Expense` |
| Operating Profit | `*Operating Profit`, `Subsidiary Op.Profit` |
| Net Sales (the line's denominator) | `*Net Sales`, `Net Sales Amt` |

The build also says whether operating profit is a total the analysis broke
down. Where it is, the bars and the line come from one statement; where it is a
column of its own, the bars are not guaranteed to account for it exactly.

Only those six figures are embedded, not all two hundred, so the page stays
small however wide the export is. It needs no server and no connection
(`--cdn` links Chart.js instead, for a smaller file that then needs the
internet).

**The numbers travel with the file.** Everything behind the chart is readable by
anyone who opens it, in the browser or in a text editor. Sending the page is
sending the data.

## If a figure looks wrong

The build prints what it matched, and that is usually the answer:

- `N amount column(s)` - if a figure you expected is missing, it was read as a
  dimension. The name test in `is_measure` is the place to look.
- `-- not found --` beside one of the six series - the export spells that
  header differently. Add the spelling to `SERIES` in `build_pnl.py`.
- `joining on:` - the column each join is made on. A `-- no such column --`
  here is why nothing matched, and the export's headers are printed beside it.
  When a key is found but matches nothing, both sides are printed together -
  the mismatch is usually obvious once they sit side by side.
- `N repeated key(s) in customer_2608` - the same Sold-To listed more than
  once. Each column is taken from the first row that fills it, so a later stub
  with empty detail columns cannot blank out a real account; a later row that
  disagrees on a filled column is reported by key and left, so a conflict that
  matters can be looked up in the master.
- `joined: N of M rows matched a customer` - a zero here means the export does
  not carry the key the master is on, and the filters fall back to the columns
  of the profit file itself.
- `filter values:` - every value each select offers, where it came from, and
  any value the master lists that **no row of this export carries**. A name
  missing from a filter is one of two different things, and this separates them:
  the master does not know it, or it knows it and nothing was sold under it this
  month. `--find VALUE` asks the same question of one code: which column holds
  it, how often, and **every column of its master row**, marked with the filter
  level that reads it - so a value that is plainly in the file but never reaches
  a filter shows up as sitting in a column no level reads.
- `--where VALUE` goes the other way: which Channel / Type / Portal Group paths
  carry that value and how many rows, and, when no level does, which master
  column holds it instead.

A value missing from a level's row is one of three things, and these separate
them: the cascade is hiding it because a level above is narrowed, no row of this
export carries it, or it lives in a column no level reads. The last one is fixed
by adding the column's name to `LEVELS` in `tools/customer.py`.
- `N total(s) read straight off the layout, M column(s) left to place` - a large
  M means the export is not printed as totals-then-lines, and most of the work
  fell to the wider search.

## Stack by Promo

A fourth button beside Customer, Product and When ordered - and **the same
mechanism as those two, not as When ordered.** The promotion is two more levels
of the key, so the existing code draws it: clicking a bar narrows to that value
and the next level down splits what is left, Back steps out, and the filter rows
carry it like any other level.

> **Promotion** -> **DTC campaign**

Three bands, which is what the page is read for:

| | |
|---|---|
| DTC + Nation-wide | a plan line covering that product on that date names both |
| DTC promotion | it names a DTC campaign only |
| No promotion | nothing above |

Clicking **DTC promotion** opens it by **DTC campaign** - the campaigns inside
that band, folded to one spelling each, so `DTC Boost week` and `DTC Boost Week`
are one bar.

`--promo-bands all` keeps five apart instead of three. The two that fold are
real and different, and the distinction is kept in the data rather than thrown
away:

| | |
|---|---|
| Nation-wide only | a plan line covers it and names the nationwide campaign, no DTC one |
| Not in the plan | **no plan line covers it at all** - the product is not in the plan, or every line for it has a window the order date sits outside |

*Not in the plan* is the absence of a statement, not a finding: the plan says
nothing about that line either way. Folded into *No promotion* it reads as "this
much sold unpromoted", which it does not support - so the fold is a display
choice the data can be asked to undo, not a loss.

### How a profit row gets a promotion on it

The profit file has no promotion. Each combination is split across the
promotions its orders came in on, in proportion to the units each carried, and
the split rides the spreading the order side already used - an order that cannot
settle a level lands on the combinations it is consistent with, in the shape
those rows already have. What no order could band keeps a row of its own, so the
month still comes to its own total.

That is an allocation. It assumes every unit of a product earns the same margin
whichever promotion brought it in, which is the one thing a discount does not
do. It ranks promotions; it does not price one.

### Either order source, not just one

The page takes its orders from SAP where `orders_*` exports are there, and falls
back to the store export otherwise - and **the promotion split comes out of
whichever one answered.** Reading it only off the store export left the band
levels missing on every build SAP answered, so the button was disabled on
exactly the builds most likely to be run. The bander is built once, before
either source is read, and both pass it through.

On the SAP side the units are banded on **`Created On`, not `Goods Issue
Date`**: the promotion was live when the customer bought, not when the warehouse
got to it. Carried out is left unbanded - it is next month's revenue and has
earned nothing here to split.

The band is read from the product code and the date, **never from the price** -
the price rejects plan lines the plan does cover, because a trade-in or a
stacked voucher moves what was collected away from what the plan quotes. The
same test `promo_match --dtc-only` and `promo_profit` use, so the three cannot
disagree about one order.

```
py dashboard\build_pnl.py                      # -> dashboard/pnl_promo_<yymm>.html
py dashboard\build_pnl.py --promo-bands all    # five bands, not three
py dashboard\build_pnl.py --no-promo           # -> dashboard/pnl_<yymm>.html, as before
```

**A different file on purpose.** The promotion split is new and the page being
read today is not replaced by it. `--plan` names the plan files (default
`MX_product ce_product`).

A disabled button looks exactly like a broken one, so a build that bands nothing
says so at the end, with what it would need:

```
Stack by Promo will be OFF on this page: nothing was banded by promotion.
  It needs an order source (SAP orders_* or the store export) and a plan
  (--plan, default MX_product ce_product) that lists the products sold.
```

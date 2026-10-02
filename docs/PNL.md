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

### One page, every month

The build draws **every** `profit_*` export in the folder - one month each - and
puts them in one page behind a **Month** button. The months stay whole rather
than merged: a month has its own customers, its own products and its own levels,
and merging them would invent a key that was in neither.

Switching month starts the drill again, because the levels are that month's.
How the page is being *read* - the basis, amounts or per unit, which chain
stacks, % of bar - carries over, since that is about the reader rather than the
data.

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
| the breadcrumb | go back to any step of the path; **All** returns to the top |
| **← Back** | step out one level |
| a level name | put the bars on it, clearing what was narrowed at and below it |
| **Stack by** | which chain splits each bar of the stacked chart |
| **Figure** | what the stacked chart charts |
| **Amount / % of bar** | sizes between bars, or the mix inside each one |
| **Amounts / Per unit** | money, or every figure divided by the units behind it |
| **Basis** | whose month the figures describe - see below. Only there when an order export was read |
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

**Basis** reads the whole page on one of those:

| | | |
|---|---|---|
| **Sales** | the month as the profit file reports it | measured |
| **Own orders** | `booked` - last month's carry-over stripped out | measured |
| **Carried in** | `carried in` - what **last month's** orders earned here, on its own. These units really were sold this month, so their profit is read rather than projected | measured |
| **Carried out** | `carried out` - what this month's unshipped orders are worth at **this month's** rates | a projection |
| **Own + to come** | `booked + carried out` - this month's own orders in full | part projected |

Every one of them is a share of the same denominator, `booked + carried in`, so
**Sales = Own orders + Carried in** and the month decomposes exactly. Picking
*Carried in* reads the whole page - gross, every cost, operating profit, profit
%, ASP - for the carry-over alone, which is how a month's carried-over business
gets compared with the business it won itself.

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

and the orders chart says it in a line: what the carried-in units earned, and
the margin they earned it at **against the month's own**. A carry-over that
converts at a different margin from the month's own demand is the thing this
whole split exists to show.

*Carried out* is the only one that is not a measurement: the month it lands in
has not happened, so its units are priced at this month's rates. The subtitle
says so while it is on.

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

So there is one chart, and **Figure** chooses what it draws:

| Figure | |
|---|---|
| **P&L** | the statement: the gross bar, what it went out on stacked beside it, and the profit line |
| anything else | that figure split by the level below - who it came from - and the profit line |

The profit line is on both, on the right-hand scale, so switching between them
never loses it. Choosing **Qty** therefore gives the units split with the profit
line over it and **no cost bars**: costs share no scale with a count of units,
and the same goes for a bar normalised to 100%.

In P&L mode **Scale** disappears rather than greying out - normalising to 100%
is about a mix and the P&L is not one, and a disabled button still costs a row
of a menu that is already tall.

### The orders chart

Under the profit chart, **one stack** per member of the level the bars are on,
read bottom to top:

```
  carried out    ┐ the month's own demand - what its orders will earn in all
  booked         ┘ ┐
  carried in       ┘ the month's revenue - what it actually earned
```

Two side-by-side bars drew `booked` twice and said nothing the one stack does
not. The one stack says it better, because **both** totals come off it at once:
the segments below the dashed rule are the month as sold, the two above the
carried-in band are its own demand. The line is the share of the month's revenue
its own orders earned.

**Units or Amounts.** Units is what the two exports genuinely agree on - both
mean one unit shipped, while the amounts differ by tax, by currency and by what
each file calls revenue. Amounts puts the chart on the profit file's gross,
shared over those same units, so it can be read against the chart above it.

In Amounts a fourth band appears: **no order matched**. Without it this bar
would sit below the chart above by exactly the sales the join could not place -
every time - and that gap reads as the two charts disagreeing when they do not.
With it, everything below the rule adds to the profit file's own total, which is
the number the chart above draws. The grey is the palette's neutral slot and
belongs to that bucket; carried in is a real category and takes a real colour.

Past twelve members the chart draws the biggest and drops the rest, and then its
bars are **not** the whole month. The hint says so rather than letting the
shortfall look like a disagreement.

When a month takes in more than it hands on, its revenue is **flattered by the
difference** - a backlog cleared, not demand earned - and the hint says so in
those words, with the number.

```
py dashboard\build_pnl.py                    # every month in the folder, one page
py dashboard\build_pnl.py --open             # and open it in the browser
py dashboard\build_pnl.py --file profit_2609 # one month only
py dashboard\build_pnl.py --months -2609    # every month but that one
py dashboard\build_pnl.py --no-orders        # sales only
py dashboard\build_pnl.py --booked "COMPLETED,DELIVERED"
py dashboard\build_pnl.py --skip-sku SMC-AU-
py dashboard\build_pnl.py --columns          # what each month's export carries
```

When the page draws a figure for one month and not another, that is nearly
always the exports having been cut differently. `--columns` puts every profit
export's columns side by side with each one's total, and marks the two lines
that explain it: a column **not in every export**, and a column that is in both
but **empty in one of them**.

The two order exports are found **by month**: the profit file says which month
it covers, in its own `YYYYMM` column where it has one, and the exports named
for that month and the one before it are the ones read - `26 DTC Sep` and
`26 DTC Aug` for a September profit file. `--orders` and `--orders-before`
override that.

An export whose order dates say it is a different month is **not used**: the
build says which month it actually holds and which one it wanted, and the page
comes out as sales only. Modelling a month with another month's orders is worse
than not modelling it, and nothing downstream would show that it had happened.
`--any-month` overrides the check. `--booked` names the
status(es) that book the money; everything else in flight is carried forward and
`tools/cohort.py` is what says whether that reading holds. `--skip-sku` drops
product codes that are ordered but never reach the profit file - service plans,
subscriptions, bundle headers - which otherwise charge the model with units it
could never have sold.

Under the booking rule every status has somewhere to go, so none is left
unread. `tools/reconcile.py --statuses` still lists them all with how its own
shipped/not-shipped reading takes each one.

### The profit split

Above the profit chart, three figures and a total:

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

### Per unit, and ASP

**Per unit** divides every bar by the quantity behind it. The gross bar becomes
the **average selling price** and the stack becomes what a unit costs, so the
gap between them is profit per unit. The profit line does not move - a
percentage is the same figure either way - which is what lets price and profit
be read off one chart.

ASP is the weighted price: the totals divided, never the average of the rows'
own prices. It sits in the KPI row and in the table as `ASP`, always on net
sales over net quantity, whichever mode the chart is in. The drill runs down to
the **SKU**, so a category price can be opened until the model behind it shows.

A group with no net quantity - returns cancelling its sales - has no price, so
its bar is left empty and the hint counts them. A blank is the honest answer
where a zero would read as "free".

`tools\asp.py` computes the same figures as csvs, for a spreadsheet rather
than a page; `docs\ASP.md` covers it.

### The stacked chart

It comes first on the page: the same slice, one bar per member of a level,
**each split by the level below it**. The chart under it says what a figure is
made of; this one says who it came from, so the page opens on the mix.

It starts one level above the bars below it - a single **E-STORE** bar split
into EPP and S.com, rather than an EPP bar and an S.com bar that have to be read
against each other. Comparing sizes is what the chart below is for.

**Stack by** picks the chain that splits each bar. On the same chain as the
bars it takes the level below them; on the other one it starts that chain at
its top - so **Stack by Product** while the bars are on Type puts the division
mix inside each customer.

So Channel split by Type, click the bar, and it becomes Types split by Portal
Group - the drill carries the stack down with it, and the chart below moves
with it, since one level drives both.

A cost is carried negative in the export, so the whole figure is flipped when
its total is: a **Operating Cost** stack stands up like the others, and a
member that really does run the other way still points the other way inside it.

**% of bar** normalises each bar to its own total, so the mix inside a small
bar reads as clearly as inside a large one. The tooltip keeps the amount behind
each share: a share with no size behind it is how a rounding error comes to
look like a trend.

The eight largest members get a colour each, in a fixed order; a ninth folds
into **Other** rather than being handed a generated hue, so the colours mean
the same thing from one view to the next.

Clicking a bar and clicking a member button are the same act: narrowing to one value
moves the bars down to the next level, and widening back to *All* brings them
up again. The drill runs the whole chain - Channel, Type, Portal Group, Type2,
then Division and Category - so it carries on into the product side once the
customer levels are used up.

The line is a percentage and the bars are amounts, so the line carries its own
scale on the right - the one place in these pages with two y axes, because the
two cannot share one. Each point is labelled, so the right-hand scale rarely
needs reading.

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

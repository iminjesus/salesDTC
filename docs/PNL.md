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

`profit_2608_3` is a month of **sales**. `26 DTC Aug` and `26 DTC Jul` are months
of **orders**. Nothing joins a sale to the order it came from - that link was
never exported, and the two order files share not one order number - so the
month is **modelled** from the order statuses instead:

```
booked       units this month's own orders completed     its own demand, earned
carried in   units last month left unfinished            earned here, ordered there
carried out  units this month leaves unfinished          a later month's revenue

the month's revenue    = booked + carried in
the month's own demand = booked + carried out
```

A cancelled or returned order is carried nowhere and is in none of the three.

**That reading was tested, not assumed.** `tools/cohort.py` scores it against
every rival on the month it claims to explain, product by product. On the real
August it comes back at **99% of the units with 11% per-product error**, where
August's own completed orders alone give 61%/44% and the next best rival 75%/38%.
`docs/COHORT.md` is the test; run it again whenever a new month lands, and
whenever `--booked` is changed.

**Basis** reads the whole page on one of those:

| | |
|---|---|
| **Sales** | the month as the profit file reports it |
| **Own demand** | `booked / (booked + carried in)` - last month's carry-over stripped out, leaving the revenue this month's own orders earned |
| **Demand + to come** | `(booked + carried out) / (booked + carried in)` - what this month's orders will earn in the end, the unshipped part priced at the same per-unit rates |

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

### The orders chart

Under the profit chart, the month's two sides - one pair per member of the level
the bars are on, `earned` on the left and `ordered` on the right. Units, not
money: both files carry a quantity that means one thing, a unit shipped, while
the amounts differ by tax, by currency and by what each file calls revenue.

`booked` is drawn in one colour across **both** bars, because it is one set of
units: the orders this month both took and earned. What sits above it is what
the other bar does not have - last month's leftovers on the revenue side, next
month's on the demand one. The line is the share of the month's revenue its own
orders earned.

When a month takes in more than it hands on, its revenue is **flattered by the
difference** - a backlog cleared, not demand earned - and the hint says so in
those words, with the number.

```
py dashboard\build_pnl.py                    # reads both order exports if they are there
py dashboard\build_pnl.py --no-orders        # sales only
py dashboard\build_pnl.py --booked "COMPLETED,DELIVERED"
py dashboard\build_pnl.py --skip-sku SMC-AU-
```

`--orders` and `--orders-before` name the two exports. `--booked` names the
status(es) that book the money; everything else in flight is carried forward and
`tools/cohort.py` is what says whether that reading holds. `--skip-sku` drops
product codes that are ordered but never reach the profit file - service plans,
subscriptions, bundle headers - which otherwise charge the model with units it
could never have sold.

Under the booking rule every status has somewhere to go, so none is left
unread. `tools/reconcile.py --statuses` still lists them all with how its own
shipped/not-shipped reading takes each one.

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

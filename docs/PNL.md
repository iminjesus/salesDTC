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
py dashboard\build_pnl.py --open       # -> dashboard\PNL_OCT.html
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

## The shape of the page

Top to bottom: a title line, the menu, then the cards.

- **The menu is one row of switches**, with the levels under it. **Filters**
  folds the levels away once the narrowing is set and the room is wanted for
  the charts, and carries a count while any of them is on.
- **Achievement is first and on by default**: the month against its target is
  what the page is opened for during an open month. Then the price tiles, the
  daily chart, the monthly chart, and the optional Numbers and Table cards.
- **No captions.** What `--drop` left out is reported by the build that did
  it and on the workbook's Scope sheet, not on the page: it is the same
  sentence on every page of a folder whose drops never change. A line under a
  chart appears only when something has been left out or cannot be compared - a month whose carry-in is unknown, margin
  points over the cap, an export that stops mid-month, target money that could
  not be placed. A caption that is always there is scrolled past; one that
  appears only when it matters is read.
- The page takes the width of the monitor, capped, so a wide screen is not
  mostly margin.

## 3. The chart

`dashboard\build_pnl.py` turns that into one self-contained page: one bar for
gross sales, a stack beside it for sales deduction, cost of goods sold and
operating cost, and a line for operating profit over net sales. Same shape as
the Sales Dashboard's profit chart (`new-sales2`, branch
`claude/crawl-product-pricing-Hafp4`) - two stack names on a stacked x axis so
the pair sits centred on each tick, the line last so it takes no column of its
own - drawn across the members of a dimension rather than across months.

### How customers are divided

At the top, the account name only says which side of the business a row is
on, so it is reduced to a **Channel**: anything marked off-line becomes
`OFF-LINE`, anything else - `E-STORE`, `E-STORE_B2B` and the rest - becomes
`E-STORE`. The detail comes from the levels underneath, and the account's own
name comes back at the bottom:

```
Channel  ->  Type  ->  Portal Group  ->  Type2  ->  Customer name
```

**Customer name is the account itself**, and it is there because *show me
Myer* had no answer anywhere else on the page: Myer is not a Channel, a Type,
a Portal Group or a Type2 - it is an account underneath all four, and the
levels above it stopped one step short of naming it. It always gets the
**search box** rather than a row of buttons, whatever its count: an account is
looked up by name, and buttons are the wrong shape for that question even when
the answer happens to fit in six of them.

It is read from the master's own name column, and **`Account Name` is not
it** - that column holds `E-STORE`, `E-STORE_B2B` and `off-line`, which is all
this page has ever asked of it. The build looks for the name in four passes
and says which column it took and how:

1. `--customer-name-column`, where it was named by hand;
2. the usual SAP spellings - `Customer Name`, `Sold-to Name`, `Name 1`,
   `Cus_name`, and `Customer`, `Cus_group` and `Customer Group` where the
   channel marker did not already claim them;
3. any header with `name` in it that no other level is reading, because the
   list of spellings is always one short - `Cust Name 1`, `SoldTo Name`,
   `Name of Customer` have all turned up;
4. the **widest column left**, by shape rather than by its header. In a
   customer master the account code and the account name are the two columns
   with a value per customer, and the code is the key and already spoken for,
   so what is left is the name. This pass can be wrong, which is why the run
   says it took it:

```
the customer name comes from 'Cus_desc' in customer.csv
    (the widest column left, by shape rather than by its header)
```

A wrong guess shows in one glance - the menu fills with towns instead of
customers - and `--customer-name-column "<header>"` fixes it in one run.
Codes in the search box help nobody, so guessing and saying so beats refusing
and leaving it unusable.

Where there is no master at all, the **account code** stands in: still one
customer per value, still something to search. Only `--no-customer-name`
removes the level.

**The page opens on `E-STORE`**, so a marketplace account is narrowed out
before it is searched for. The search says so rather than coming back empty:
*"MYER PTY LTD" is here, but Channel E-STORE narrows it out.* Set Channel to
*All* and it is there. "Nothing matches" and "nothing matches in what you are
looking at" are different answers, and only one of them means we do not sell
to them.

It is also the level that multiplies combinations, since it sits in the key
with the SKU. `--no-customer-name` leaves it out - the switch to reach for if
the page gets too heavy to send.

A narrowing to one account turns the achievement table's comparison off and
says so: the Blue File sets a target by product group with a customer mix
down to Type2, and there is no per-account target to put beside it. The
actuals, the daily chart and the planned-price tables all narrow normally.

`tools/customer.py` holds that rule, so this page and `build_dashboard.py`
divide customers the same way. Reordering `LEVELS` there reorders both.

**The page opens on `E-STORE`.** The offline rows are still in the file:
setting Channel to *All* steps up and brings them back for comparison, which is
also what puts `Channel` on the x axis as two bars side by side.
`--start-channel ""` opens on everything instead.

### How products are divided

The product master draws its own tree, and the page drills it as it stands:

```
Biz  ->  Div 1  ->  Div 2  ->  Div 3  ->  Range  ->  SKU
```

```
MX      ->  MX  ->  MX  ->  Mobile, Accessories, Tablet, Wearable
CE      ->  VD  ->  VD  ->  TV, Monitor, AV
        ->  DA  ->  HA  ->  REF, WM, VC, BIC, MWO, DW
                ->  AC  ->  RAC, SAC, Air Purifier
Memory  ->  Memory  ->  Memory  ->  Memory
```

It replaces `Division` and `Category`, which were two flattenings of this same
tree - `Div 3` is `Category` with Aircon split back into `RAC` and `SAC`. A
master written before the `Div` columns existed still fills the chain: each
level keeps the old spellings as fallbacks, so `Division` lands in all three
and the page walks through them in one step, which is the next section.

**A level that holds one value is not a choice, so the drill steps over it.**
MX is `Biz` MX, `Div 1` MX and `Div 2` MX, and only at `Div 3` does it become
Mobile and Accessories and the rest; the whole of Memory is Memory four times
over. Clicking **MX** therefore lands the bars on `Div 3` rather than on two
more bars saying MX, and clicking **CE** lands them on `Div 1`, where DA and VD
are a real choice. The level is still in the menu, still in the breadcrumb and
still a column in the workbook - it is greyed, and says so if you hover it.

It is counted over the slice on screen, not over the file, so `Div 2` divides
CE into HA and AC and holds one value once MX is picked. The same rule covers a
level the master could not fill at all, and a customer level like Portal Group
with one value in it: one value is one value, wherever it came from.

### Leaving a value out altogether

Two values are **left out of every build**, because neither is the business
this report is about:

| Left out | Why |
|---|---|
| `Biz=Memory` | another business; it was a band on every bar and a dotted margin line across the chart |
| `Biz=(blank)` | where rows the product master could not place end up |

```
left out of this page: Biz: (blank), Memory   (--add brings one back, --add-all draws the file as it is)
  26 combination(s), 26 row(s), 318,608 in net sales - out of the bars, the
  totals and the workbook alike
```

A default rather than a flag because it is a property of **the report**, not of
one run - a page that needs a flag to be right is a page that will be wrong the
first time someone forgets it. It is not a silent default: every build prints
what went and how much, so a `(blank)` that starts growing is visible rather
than quietly thrown away.

**Out of everything** - the bars, the totals, the line and the workbook. Hiding
a value from the bars while keeping it in the totals would leave the stack and
the line disagreeing about the same slice. It is applied **after** every source
has been merged, so a value dropped from the sales side cannot come back
through the order side carrying a booking.

| Flag | |
|---|---|
| `--add "Biz=(blank)"` | add one of the defaults back, e.g. to chase down a join that is failing |
| `--add-all` | add everything back: draw the file as it is |
| `--drop "Div 3=Service,Gift Card"` | leave more out |

All three take `LEVEL=VALUE[,VALUE]` by level name, ignoring case and spacing,
and all are repeatable. A name that is not a level stops the build; a *value*
that matches nothing is only a warning, and the run names it, because a typo
there leaves the page carrying what was meant to be excluded.

What went is said **on the page** - under the menu, beside the narrowing, and
on the workbook's `Scope` sheet. Nothing on the page can bring it back, which
is exactly why it has to be written where the page is read:

```
Showing everything else in the file. Not in this page - Biz: (blank), Memory.
```

### Returns

**Goods that came back are in.** A credit is a real movement and the export's
own total carries it, and a page that quietly differs from the file it names is
worse than one with an awkward month in it.

`--no-returns` takes them out for a run where a ratio has to be read cleanly -
a credit is the one row that makes one hard, because its units and its money go
out negative while the cost does not always follow them. Then the run prints
what went and the page says it under the menu beside anything `--drop` removed,
because from that point the totals are no longer the file's own:

```
returns left out: 412 row(s), -1,207 unit(s), -1,884,350 in net sales   (--no-returns asked for that)
```

A return is **negative units**, and where a row has no units, negative money -
one definition, in `rawdata.is_return`, so the page, `channel_cogs.py` and
`order_lag.py` all draw the same line.

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
for. The split then steps down to the next level that divides what is left, so
MX becomes Mobile, Accessories, Tablet and Wearable across the year - past
`Div 1` and `Div 2`, which are MX again.

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
PRODUCT   BIZ [All|CE|MX|Memory]  DIV 1 [All|DA|MX|VD]  ...  DIV 3 [All|Mobile|TV|REF]  SKU [All (60) v]
```

The **name** puts the bars on that level; the one they are on is underlined in
the accent colour. The **members** narrow to one value, and *All* widens back.

A level whose members outnumber `BTN_MAX` (eight) gets a **search box**
instead - Range and SKU are lists to search, not rows to scan - and so does
Customer name at any size, for the reason above. The search is loose on
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
| **Excel** | this view as a workbook - see below |
| **Reset** | back to the opening view |

### The Excel download

**Excel** writes the view on screen to an `.xlsx` named after the page:

| Sheet | What it holds |
|---|---|
| `Chart` | the bars as drawn - one row per series, one column per period. The margin lines come with a percent format, so 14.4% is not written beside the amounts as `14` |
| `Table` | the breakdown under the chart, **every row of it**. The screen stops at twelve because it runs out of room, which is no reason for a workbook to |
| one per figure | **every combination, month by month** - see below |
| `RRP` | the list price the promotion plan set, by model and month |
| `ASP` | what was actually collected per unit, and how far under list that is |
| `Scope` | what was on screen when it was taken: the source files, the narrowing in force, Stack by, Period, and the totals |

Between the two is a sheet per figure - `Gross Sales`, `Deduction`, `CoGS`,
`Opex`, `Net Sales`, `Profit`, `Qty` - holding what the chart and the table are
summaries **of**: one row per customer-and-product combination, **one column per
month**, then a Total and the row count behind it.

| Channel | Portal Group | Biz | Div 3 | SKU | Promotion | Jul 26 | Aug 26 | Sep 26 | Total | Rows |
|---|---|---|---|---|---|---|---|---|---|---|

One sheet per figure rather than one sheet with them interleaved: months across
the top is only readable while a row means one thing, and a header of `Aug 26
Net / Aug 26 Profit / Aug 26 Qty` across nine months is not a sheet anybody
filters. Biggest first, so it opens on what matters.

The filters apply. Opened on E-STORE, that is the DTC business month by month;
narrow to a division or a model and the sheet narrows with it. **Period and
Cumulative do not** - those shape the chart, and a detail sheet quietly holding
quarters where it says months would be the one table in the book that lies.

Each figure's Total column adds to that figure on `Scope`, which is the check
worth making before anyone builds on it.

#### The two price sheets

`RRP` and `ASP` are the same rows in the same order, and they are **prices, not
amounts** - so their last column is not a sum. `Weighted` and `Period` hold the
figure for the whole period, weighted by the units that earned it, which is why
a price drop halfway through lands where the volume was rather than halfway
between the two prices.

`RRP`, after the same level columns the other sheets carry:

| ... | SKU | Jul 26 | Aug 26 | Weighted | Units |
|---|---|---|---|---|---|
| | SM-F971BLVDATS | 2,899.00 | 2,699.00 | 2,852.85 | 13 |

`ASP`, the same rows in the same order:

| ... | SKU | Jul 26 | Aug 26 | Period | Off RRP % | Units |
|---|---|---|---|---|---|---|
| | SM-F971BLVDATS | 2,500.00 | 2,344.33 | 2,464.08 | 13.6% | 13 |

`Off RRP %` is where the two meet: `1 - ASP / RRP`, the discount the slice
actually ran at. It is read over **the units that have a list price**, not over
the whole slice - mixing a list price from one set of units with an ASP from
another is how a book ends up quoting a discount nobody ran. `Scope` carries
the same three figures for the whole slice, plus how many units they cover.

**RRP comes from the promotion plan** (`--plan`, default
`mx_promo|MX_product` / `ce_promo|CE_product` — see below), by model and month: the lines whose window touches the month,
and where they disagree the commonest value. The profit export says what was
collected, never what was asked - so without a plan there is no `RRP` sheet and
no discount column, and a model the plan never names is left **empty** rather
than filled with the price it sold at, which would read as a unit that sold at
list.

An empty cell is therefore the **plan** being silent, not the product having no
list price, and the build says which of the two silences it was:

```
  list price: 412 of 605 SKU(s) have an RRP in the plan
    181 not in the plan at all: AC100HEHPKG/SA, ...
     12 planned, but no RRP on the line: ...
```

`--rrp CODE` reads one product out of the plan - how the code was matched,
every line it matched, each line's window and price columns, which lines fall
outside the month, and the value the sheet writes:

```
py dashboard\build_pnl.py --rrp AC100HEHPKG/SA

what the plan says about 'AC100HEHPKG/SA':
  code read as 'AC100HEHPKGSA'
  no plan line for it
```

A product that never ran a promotion is normally in neither file: accessories,
bundles and packages are planned separately or not at all, which is why a
package code comes back empty while the model inside it has a price. That is
the plan's coverage, not a bug in the lookup - and `--rrp` is how to tell those
apart before anyone goes looking for a missing price.

It is the slice the filters leave, not the whole file - a download that quietly
held more than the page showed would be a different report wearing its name.
Narrow first, then press it.

The workbook is written in the page itself, not fetched: an `.xlsx` is a zip of
XML, and the page has to stay one file that opens from an email attachment. It
is the same four parts `tools/xlsx.py` writes, so a workbook from the page and
one from the toolchain open alike. Numbers go in as numbers, so the sheet can
be summed.

### Orders, and the month they belong to

> **Is the store export still needed?** Not by this page, while `orders_*` is
> there: SAP wins and `26 DTC <Mon>` is never opened. The run says so -
> `26 DTC Sep.csv is in the folder and was not read - SAP answered`. It is
> still the only file carrying the store's own `promotion_rule`, the voucher
> codes, the portal and tier, and the discount the store applied, so
> `promo_match.py`, `promo_profit.py` and `rulegram.py` read it directly.
> `cohort.py` is the one tool SAP makes unnecessary: it exists to work out
> which orders became a month's sales, which SAP answers off its own dates.

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

**Every block carries its percentage**, on the same denominator as the line -
net sales - so the bar and the line are read together:

```
  Gross Sales      104.7%        Sales Deduction   4.7%
                                 COGS             71.8%
                                 Operating Cost   10.0%
                                 line             18.2%
```

The two stacks then settle against 100% from either side: gross less deduction
is 100% of net sales, and cost of goods plus operating cost plus the profit
line is the same 100%. Over **gross** would have been each bar's own total, but
nobody quotes cost of goods over gross - the ratio repeated in a meeting is
over net, and a chart printing a different one invites the two to be compared.

A block too short for a label is left alone, as everywhere else on the page.
**Expand** adds the amount on a second line under the percentage, where the
block is tall enough to hold both.

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

**A margin over 80% is left off the chart.** Operating profit cannot be most of
net sales: what makes a figure like 1,120% is the denominator - a band with a
few thousand in net sales carrying a cost line that landed somewhere else. One
such point rescales the percent axis until every real line on the chart is the
same flat row, so the point is dropped and the caption says how many went. It
is dropped rather than clamped, because a band pinned at 80% is a figure
somebody will read. **Only the positive side is cut**: a band really can lose
more than it sells, and -200% on a clearance band is a result, not an artefact.
`MARGIN_CAP` in the template is the number.

**And a band too small to read loses its line, not its bar.** Two units of an
accessory are a real band and belong in the bar; a margin read off them is a
ratio over almost nothing that swings by hundreds of points between months
while saying nothing about the business. A band under **0.5%** of its own
month (`LINE_FLOOR`) keeps its bar and drops that month's point from its dotted
line - the line simply has nothing to say that month - and the caption counts
how many went.

Choosing **Qty** gives the units split with the profit line over it and **no
cost bars**: costs share no scale with a count of units, and the same goes for a
bar normalised to 100%. Controls that do not apply disappear rather than greying
out, since a dead button still costs a row of a menu that is already tall.

### The open month, day by day

Above the monthly chart, its own card, **the same height**: one bar a day for
the month the order export covers. October's orders exist while October's P&L
does not, so it is a chart of its own rather than a narrower setting of the one
below - the monthly chart keeps the closed months and nothing about it changes.

**The menu above drives both.** The narrowing, the split (Stack by), the
Figure, Cumulative and Scale all apply to the daily chart as well, so there is
one set of controls on the page and not two. The card's only button of its own
is **Values**, which puts the figure on every bar - the monthly chart reveals
its figures by expanding and this one has no expand. Nothing appears on hover,
here as everywhere else on the page.

**Clicking a band drills**, exactly as it does below: it narrows the page to
that member and steps the split down a level, so the monthly chart follows the
click made on the daily one. The x axis does not move - it is time - so the
same days come back with only that member in them. **Back** sits on the card
beside Values and undoes the deepest narrowing, so a drill made here is
stepped out of here rather than from a button further down the page.

Two things it cannot follow, and the hint says so when they are on:

- **P&L** is a statement a day has no columns for, so the chart falls back to
  the money figure.
- **When ordered** is not a level: it cuts a month by where its orders came
  from, and a day *is* the orders. The split stays on the level the drill is on.

#### Which column the money comes from

`Actual to date` - and every bar on the daily chart - is the order export's
own money column, summed over the lines the basis keeps. The reader takes the
first of these the file has:

1. `Net Value (Item)`
2. `AUD Revenue excl. GST`
3. `USD Revenue excl. GST`
4. `Net Value`

and `--currency USD` makes it prefer a column whose name carries that code,
for an export that holds more than one. Units come from `Confirmed Quantity
(Item)` under the same first-match rule.

The build names the one it used, so this never has to be worked out from the
code again:

```
the daily chart, off orders_2610.csv (202610):
  the money is Net Value (Item); --currency picks another
```

#### Marketplaces are on it

`AU260930-46262020` is the store's own order number; Amazon, Myer, MyDeal and
eBay carry something else, and the shape of the reference is the only thing
separating them. The daily chart used to drop those lines.

That was wrong, and visibly so: the profit export has no such filter, so a
marketplace customer sat plainly on the monthly chart and drew **nothing** on
the daily one - which reads exactly like a customer that sold nothing, the
opposite of the truth. A customer on one chart belongs on the other.

They are counted now, and where that line gets drawn is the page's own job:
**Channel** and **Customer name** take them out for anyone who wants them out,
the same way every other row on the page is narrowed.

The build still reports them, because the reference shape is the only thing
that knows which they are, and *is Amazon in this figure* is a question about
a number:

```
  not the store's own order: 1,284 line(s), 3,910 unit(s), 2,106,400
      - counted; narrow by Channel or Customer name to take them out
    reference shapes: MD-###### x842, AMZ-####### x442  (# is a digit)
    whose: MyDeal.com.au (842), Amazon AU (442)
    on OFF-LINE 2,106,400
    none of it is on E-STORE, so the page's opening slice is unchanged
```

That last line is the one to read after a rebuild. The page opens on
`E-STORE`, so while every marketplace is marked off-line in the customer
master, counting them changes no figure anyone was already reading - and the
build says whether that holds rather than leaving it assumed.

`--no-marketplace` restores the old behaviour. On such a build, a marketplace
customer's empty chart says so rather than looking like a quiet month - and
the achievement card is then worth a second look, because if the Blue File's
Sokbo covers marketplace sales, the denominator includes Amazon while the
numerator no longer does, and every achievement is understated by that much.

#### Weeks on the daily chart
#### Weeks on the daily chart

A month of bars is a month of bars: which of them are one week and which are
the next is not visible at all unless the chart says so, and *is this week
ahead of last* is what a daily chart gets asked. So **every other week is
shaded**, Monday to Sunday, behind the bars - a block rather than a line at
each Monday, because the question is about a stretch and not a boundary.

Over a fortnight the axis is labelled **by week**: every Monday, in bold, plus
the first and last day. Under a fortnight every day fits and every day is
named. Either way each shaded block carries its own date rather than only an
edge.

Monday because the business week starts there, not because the data does. The
week a day belongs to is taken off the **date**, not off the column's
position: a day with no orders is not drawn at all, and counting columns would
shift every week after it.

#### Which day a promotion opened

A campaign that opened on the 8th shows up in the bars as a step on the 8th,
and only if it was big enough to move the day. The pins say it outright: a
**dot and the campaign's name above the chart** on the day it started, drawn
on every stack, and **clicking one opens that campaign's own sheet** - launch
date, end date, the daily shape, the same popup the Promo bands open.

They sit in the strip *above* the plot, not inside it. A bar reaching the top
of the chart is common and a label over it is unreadable exactly on the day
that is interesting. Several opening on one day stack upwards so none hides
another; a name that would land on one already drawn is left off and its dot
stays, so the day still says a campaign opened on it.

The pins are on the **daily chart only**. On twelve monthly columns every
campaign of the year would land on the same few bars and the strip would be a
wall of names.

**Only the DTC campaigns are pinned.** A campaign the DTC campaign levels
never name is a nationwide one, and the band records *that* a nationwide
campaign was live rather than which - it can be neither narrowed nor
attributed, and a nationwide run is the trading backdrop rather than something
this channel did. The strip is for the campaigns that are ours.

**A campaign that comes round again is pinned on this month's run.** Samsung
Week runs in September and again in October, and those are two runs, not one
long one. Two things used to collapse them into the first:

- the build's window search took the first run within a month's shoulder of
  the day, and thirty days of shoulder reach across a month end - so every
  October day landed on the run that closed on 20 September, and the October
  run was left holding nothing;
- the page then merged a name's payloads by taking the earliest start and the
  latest end, which dated the campaign to the first time it ever ran.

Between them, a recurring campaign was never an October campaign and never got
a pin. Now a day belongs to the run it is **inside**, and a shoulder is only a
fallback - the nearest run, not the first listed. The page keeps a name's runs
apart (`campaignRuns`) and each view asks for the run in **its own window**, so
the daily chart of October pins October's run and the sheet it opens shows
October's dates. Only payloads whose windows meet are added together, which is
how one run that crosses a month end stays one run.

**They follow the narrowing.** With nothing selected, every DTC campaign that
opened in the month is pinned. Once a product or a customer is chosen, only
the campaigns that sold something inside that slice stay - the campaign levels
are part of the combination key, so this is the same filter the bars use, not
a second one that could disagree with them. A product no campaign touched
shows no pins at all, which is the honest answer to *what was running on this*.

#### It is a different export

The monthly chart is the profit export - gross sales, deduction, COGS,
operating cost, operating profit. A profit export is a month with no day in it,
so a daily chart cannot come from one. This comes from the order export
(`orders_*`, SAP), which carries a date on every line, so its figures are
**Order Value** and **Order Qty** and there is no cost and no margin line.

The heading carries the month to date - the sum, not the last bar, so it does
not move when Cumulative is pressed - and how many of the days have sold.

#### Promotion, measured rather than allocated

**Stack by Promo works on it**, and works better than it does on the month.
The profit file carries no promotion, so the monthly chart has to spread each
combination across the bands its orders came in on, in proportion to units -
an allocation, and the doc says so where it is set up. A day *is* the orders,
so each line's own band is the line's own band: the plan is asked what was live
for that product on the day it was ordered, and that is the bar.

Banded on the **order** date, not the despatch date, because the promotion was
live when the customer bought - the same rule the month's banding runs on, so
the two agree. The bands keep a fixed order and a fixed colour in both charts:
the daily card sits directly over the monthly one, and a band that changed
colour between them would read as two different things.

Where no plan covers those days there is no band to split by, so the bars are
drawn whole and the hint says why rather than showing one column labelled
`(blank)`.

#### Achievement, by product group

The **Achievement** button in the menu puts a table under the daily chart: the
same month against the same target, by product rather than by day. The chart
says whether the month is on plan; the table says which products are carrying
it and which are behind.

| column | |
|---|---|
| Target (month) | the Blue File's Sokbo for this slice |
| Target to *n* Oct | that, divided evenly over the month's calendar days and taken to the last day the export covers |
| Actual to date | the days above, added up |
| **Achievement** | actual to date over target to date |

**Payment base or Order base.** Two readings of the same month, from the same
lines, and neither is the other's total:

| | what the actual is |
|---|---|
| **Payment base** (default) | what the month will be **paid** for: carried in from last month on the day it left, plus this month's orders that leave inside it. The rollover is out |
| **Order base** | what the month **took in**: every order placed in it, on the day it was placed. Nothing carried in - that was last month's demand - and the part leaving after the month is still in |

A month can take good orders and be paid for few of them, which is the thing
worth seeing; an average of the two would hide it. The card's heading says
`payable` or `ordered` so a screenshot carries which one it is.

**The rows are the product tree the page drills** - Biz, then Div 1, Div 2,
Div 3 - each parent carrying its children's total, so a division is its groups
added up and the total is the tree rather than the column. The target is set
at Div 3, which is where the tree ends.

A level that repeats the one above it gets no row of its own. Div 1 `DA` under
Biz `CE` is a step; Div 2 `REF` under Div 1 `REF` is the same thing said twice,
and the drill skips those for the same reason.

```
▾ CE        400,000   348,387   283,000    81%
  ▸ DA      200,000   174,194   225,500   129%
  ▸ VD      200,000   174,194    57,500    33%
▾ MX         50,000    43,548   106,200   244%
    Mobile   50,000    43,548   106,200   244%
  Total     450,000   391,935   389,200    99%
```

**It opens to the divisions**, because a Blue File names up to seventeen
product groups and a table that long is scrolled past rather than read. Click
a row to open it; **Expand all** drops the floor and opens everything. What is
held is the rows that *differ* from that default, by name, so a branch left
open survives a narrowing, a redraw and a figure change.

A row only gets a marker if there is something under it once the repeats are
folded: `Mobile` above is Div 2 and Div 3 both, so it is a leaf however deep
the tree goes under it.

**The achievement reads as a bar as well as a number.** The track runs 0-150%
with a notch at 100, cut in the card's own colour so it shows over the fill as
well as over the track - a mark that a full bar hides is missing exactly when
the row is worth looking at. Over 150% the bar fills; the number is beside it,
so nothing is lost.

Three colours and no more - **on plan (>= 100%), nearly (90-99%), behind
(< 90%)** - on the bar and on the number together. A gradient would put a
different colour on every row and say nothing about which one to look at.

There is no projected-achievement column and there cannot be one: the target
is spread evenly over the days, so projecting the month at the rate so far and
dividing by the month's target gives back the achievement to date, exactly. It
was in the table for one run and every row repeated the column beside it.

**Money, always.** The target is an amount and a quantity has no target, so the
table stays on order value whatever figure the chart is showing. That also
means the actual is **demand placed, not revenue booked** - the order export is
what exists for an open month.

Two honesty notes the table prints rather than leaves to be discovered:

- Narrow below the target's own key - a Range, a model, a campaign - and there
  is nothing to compare against, so the table says so instead of putting a
  whole month's target beside a slice of a month's sales.
- Target money that could not be placed (a product group with no Div 3 match,
  or one the customer mix could not split) is not in the total, and the hint
  says how much. Otherwise a reader adds the column up and believes it.

#### Planned price vs actual

Under the daily chart, three tiles, a table and two lists that only the open
month has: what it was **planned** to sell at, beside what it sold at. The
source is the GSCM sheet (`rawdata/gscm*`, read by `tools/plan_price.py` - see
`docs/PLAN_PRICE.md`), which is the same month target the chart's line comes
from, written one level further down: a planned price and a planned quantity
per **material**.

The question is price, not volume. We expected $1,100 for this fridge - what
did it actually leave at.

**The tiles** are the whole slice, whatever the table below is filtered to -
two figures headed *Actual* that meant different things would be the worse
trade:

- **Negative price impact** - the money given away by the models that sold
  under their planned price, with how many they were and what the net comes
  to once the ones above plan are counted back in.
- **Actual amt** - what the slice sold, against the plan's own amount.
- **Actual qty** - the same for units.

**The table** is Biz -> Div 1 -> Div 2 -> Div 3 -> model, collapsible, under
three grouped headings:

| group | columns |
| --- | --- |
| Actual | Qty, Amt, Gross ASP |
| Plan (GSCM) | Qty, Amt, Gross ASP |
| Actual vs plan | Diff, Diff %, Price impact |

A row only expands where there is a real step under it: `MX / MX / MX` in the
product master is one row, not three, because a level that repeats the one
above it is a spelling and not a division. The chain comes from the page's own
product master, not from the GSCM sheet - the sheet's `Biz / DIV 1 / DIV 2`
are read but only ever used to name a planned code that never sold.

**Diff is not the difference between the two columns it sits beside:**

```
Diff = ASP  -  the price these units were planned at
```

That second figure is **not on the row** - it is the plan's own price
re-weighted onto the units that actually sold - which is why hovering a Diff
spells the subtraction out and names it. On one slice of the fixture, `ASP`
reads 737 and `Plan Gross ASP` 800 while Diff reads -67, because the planned
price of *those particular* units is 804.

**Plan Gross ASP** is the plan's own amount over its own units: what the month
would have averaged had it gone to plan. Subtracting that instead would fold
*we sold more of the cheap one* into a figure headed price, so the column is
price and not mix. The plan's own mix would fold *we sold more of the cheap
one* into a figure headed price and send a reader looking for a discount
nobody gave. Built this way, `Diff x Qty` is the impact exactly, and the model
rows add up to the category they sit in.

**Negative only** is on by default: the table is pulled up to find what is
being given away, and every row is then a number to act on. Off, it is every
model with a line in the plan and the total is the net.

**Re-priced**, where `tools/reprice.py` has run, is a third column group
between the plan and the difference: the price the month could have been
planned at - the promotion plan's list price, discounted by what the same
campaign had been selling at over the six months behind it - with its own
price impact and how that compares with the plan's. A fourth tile carries the
same pair.

It is **not** assumed to be the better reading. The column is green where it
closes the gap and red where it widens it, because which of those happened is
the finding; a column painted green either way would be answering its own
question. Every other figure on the card is untouched - same units, same
materials, same basis - so only the price being measured against moves.
`docs/REPRICE.md` has the method, and `--no-reprice` leaves it off.

**The two lists** are the Top 10 models of the two businesses giving the most
away - CE and MX on the real plan. Side by side rather than one list of twenty,
because a single ranking reads as a league table and MX against CE is not a
comparison anyone wants: they are two sets of models with two sets of prices.
Each list's bars are scaled to its own worst line for the same reason.

Everything follows the page's narrowing, its currency and the same
Order/Payment base the achievement table is on, so the two agree.

Three notes the card prints rather than leaves to be discovered: codes that
sold with no line in the plan (not in the table, with their units and money
said); planned materials that sold nothing in this slice (a volume question,
not a price one); and, in USD, that **both sides are converted at the page's
own rate** rather than the sheet's USD column, so what is left in the gap is
price and not the difference between two exchange rates.

#### The drops apply

`--drop` takes its values out of the daily chart as well - Memory and the
blanks by default. A chart that drew them on days and not on months would be
two charts about two different businesses. The run says how many day rows went
with them.

#### Which day a line counts on

A month is paid for what **leaves** in it, and an order placed near the end of
one leaves in the next. So the default - `--day-basis mixed` - is not one date
read one way; it is three cases, because they are three different facts:

| | where it sits | counted |
|---|---|---|
| ordered last month, despatched this one | **the day it left** - its only day in this month | yes |
| ordered this month, already despatched | the day it was ordered | yes |
| ordered this month, not despatched yet | the day it was ordered | **only if its division can get it out in time** |
| ordered this month, leaving after it | the day it was ordered | no - drawn hatched |

The last two are the **Maybe rollover** band: hatched rather than filled,
because the bar under it is a measurement and this is a prediction. It is in
no total on the card, in no Achievement figure and in no export of them - a
KPI that added it would be claiming money the month will not be paid.

Which way a not-yet-despatched line goes is **measured, not assumed**: the
build reads last month's orders and takes each Div 1's average days from order
to despatch - the same reading `tools/lead_time.py` prints - and an order
placed later than that many days before month end is a rollover. A division
with nothing sold last month falls back to the figure over everything; with no
previous month at all, nothing is called a rollover and the run says so.

```
  lead time off 202609, days to despatch: VD 10.0, HA 7.0, DA 2.0; anything else 6.2
  by day, on last month's orders on the day they left, this month's on the day they were placed:
    5 day(s), 2026-10-03 .. 2026-10-30, 6 combination(s)
    3,400 counted; 1,200 leaves after the month and is drawn dashed, out of the total
```

A line that has already left is certain either way and is never a "maybe": the
prediction is only ever applied to lines with no despatch date on them.

`--day-basis made` and `gi` are the older readings - every line on one of its
two dates, with no carry-in and no rollover - kept for a straight count of
order intake or of despatch.

`--day-month YYMM` picks the month; the default is the latest month the order
export carries, which is normally the open one. `--no-days` leaves the card
out, and it is absent anyway when the build had no order source.

#### The two sets share one index

The months and the days are **unified together and then split into two
views**. That sharing is the whole trick: a member is the same number in both,
so narrowing to MX on the page narrows the daily chart to the same MX.
Unified separately, index 7 of Biz would be two different businesses and the
daily chart would quietly be about someone else.

Each view also carries only **the figures and the chains its own export
declared**. Left holding the union, a day has a column for Operating Profit
full of zeroes - a P&L saying the day made nothing, rather than a day that was
never asked - and each view titles itself from its own exports, or a page with
closed months through September comes out called "Aug 2026 - 3 Oct Profit".

### AUD or USD

**Currency** switches every money figure on the page - the charts, the tiles,
the achievement table, the target line, the workbook - between AUD and USD. It
needs `rawdata/fx_rate.csv`, two columns:

```
month,Rate
2601,0.67698
2602,0.70473
...
```

**A month is converted at its own rate**, which is what a monthly rate is for.
Quantities are left alone: a column whose key ends in `qty` is units, and
everything else is money.

The conversion happens **once, at the combinations**, rather than at each of
the dozen places that add money up. One of those missed would be a chart with
one column in the other currency and nothing saying so, which is the kind of
wrong that gets believed; here there is a single place that knows a rate
exists. Ratios are unaffected by construction - an achievement of 123% is 123%
in either currency, being two converted numbers divided.

**A month with no rate turns the button off**, rather than drawing that month
in AUD among USD ones. The build says which month is short:

```
the currency button:
  fx_rate.csv: 10 month(s) with a rate, 0.67698 .. 0.71818
  no rate for 202611 - the button stays off rather than drawing one month in
  a currency the others are not in
```

Blank rows in the file are months not set yet and are simply absent; they only
matter if the page is drawing that month. `--fx STEM` names a different file
and `--no-fx` leaves the button off.

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

**And the figures are only there.** The chart on the page says nothing under
the pointer: a number that appears on hover is read by whoever happens to be
moving the mouse and by nobody else, and on a page being shown to a room it is
a figure nobody asked for. Expand is the deliberate step - it labels every
value at once, for everyone looking at it - and the tooltip belongs to that
mode, where it carries what the labels cannot: the bar's total, its margin, and
in **% of bar** the amount behind each share. The caption under the chart says
so, because a chart that answers nothing on hover otherwise reads as broken.
Clicking still drills: a click is a choice, a hover is not.

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

### The two bars

The left bar is **net sales**, with the **Sales Deduction** that came off
gross **hatched over it**. So the bar's full height is gross, its solid part
is net, and the hatching is what never arrived. The right bar is what the
month **spent**: COGS and Operating Cost, and nothing else.

That is the whole point of the arrangement. Every figure is a share of net,
the solid left block *is* that 100%, and the gap between it and the cost stack
is the **operating profit** - which is what the eye was trying to measure all
along. The old layout put the deduction in the cost stack beside COGS, so the
gross bar could stand taller than the whole stack over a margin line in the
red, and the chart argued with itself.

The deduction is hatched rather than filled because it is not a cost of the
month. It is the step from gross to net, and a reader should not have to
remember that.

**Each stack carries its own total over it** - `Gross Sales 2,558,120` over
the left bar, `Cost 2,432,090` over the right - because the two questions
asked of this chart are how big gross is and how big the cost is, and
answering either meant adding blocks up by eye. Expanded, the tooltip carries
the same pair under the blocks, with the operating profit and the quantity.
Hovering says nothing until the chart is expanded; the totals over the bars
are there either way.

**Where gross is not net plus the deduction**, the left bar is short of gross
by the difference and the hint says by how much. Nothing is drawn for it: a
block with no name anyone recognises was worse than the question it answered.
It is a column the export does not name, and the page can only say that it is
there.

### Clicking into a cost
### Clicking into a cost

The four bars of the P&L are the top of a tree the export already carries, and
a reader who sees Operating Cost move wants to know **which line inside it**
moved. **Click a cost block** and the chart redraws as that cost's own lines;
click one of those with more under it and it goes further. **Back** steps out
a level, and the breadcrumb shows where you are:

```
All > E-STORE > Operating Cost > Marketing, by month
```

Inside a drill the **gross bar and the margin line come off**, and the
percentages are a share of the cost being looked at rather than of net sales.
Operating Cost is a tenth of gross and its own lines a tenth of that, so drawn
beside the gross bar they were slivers; and *Media is 2% of net sales* is true
and not what anyone opened Marketing to find out. *Media is 73% of Marketing*
is. **Other** carries whatever the detail lines do not account for, so a stack
never comes up quietly short of the total it stands in for.

Leaving the P&L closes the drill, so coming back opens where it opened the
first time.

#### Where the breakdown comes from

Not from `tools/analyze_structure.py`, which answers a harder question than
this one - which columns add up to which, judged on the values alone. It is
right to work that way and the answer it reaches is not always the statement's
own: `*Sales Deduction = *Net Sales - *S.Gross Sales` is perfectly true and no
use at all to a reader asking what the deduction is made of.

So the build reads the **layout**, which is where a P&L puts the answer: the
detail lines sit beside the total they make up. Walking out from a total and
adding columns until they match it finds them - **left first**, where a P&L
usually closes a block with its total, then **right**, for an export that
leads with the total instead. One wrinkle either way: a block can hold a
sub-total of its own, and `*Marketing` counted beside `*Media` and `*Agency
Fee` would count those twice, so a column that is itself a total of the run
behind it covers that run and the walk steps over it. Nothing is taken on
trust: a block is kept only where the sum matches on the column totals **and**
on every sampled row.

Where no block holds, there is nothing to click into, and both ends say so -
the build under *the cost breakdown*, and the chart in its own hint. The
pointer is asked the same question the click is, so a block that does not open
does not offer a hand cursor.

The run prints the tree it found, with each line's total:

```
the cost breakdown: 10 column(s), 3 level(s) deep
  Sales Deduction:
    Trade Discount                              -6,819
    Customer Rebate                             -2,079
  Operating Cost:
    Paid Commission                             -5,879
    Marketing                                   -4,604
      Media                                       -3,373
      Agency Fee                                  -1,231
```

#### What it costs

Each line kept is another number **per combination**, because the breakdown
rides on the same key as everything else - that is what lets it follow the
narrowing. `--cost-parts N` caps how many columns are carried (24 by default,
`0` for none, biggest first so a cap cuts the lines nobody would have read)
and `--cost-depth N` how deep it goes (3). The build prints the page size, so
the trade is visible on every run.

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

### ASP, RRP and the discount

Three tiles sit between the menu and the chart, and they answer the narrowing
like everything else - pick a Div 3, a campaign, a customer, and they are that
slice's:

| Tile | |
|---|---|
| **RRP** | what the promotion plan says the slice was meant to sell for, weighted by the units that sold under it |
| **ASP** | what it actually sold for: net sales over net quantity |
| **Average discount %** | `1 - ASP / RRP`, the discount the slice really ran at |

Above the chart rather than inside **Numbers**, because this is the pair of
figures the page is read for after the profit itself - and because the chart
cannot draw them: a price is not an amount, and it would be a flat line along
the bottom of a bar chart in millions.

**Which export** is a switch on the card, and the card says which it is on:

- **Orders** (the default where there is an open month) - the order export's
  own money, `Order Value`, over its own units, for the month the daily chart
  draws. The same file the achievement table and the planned-price card are
  read from, so an ASP here and an ASP there are the same kind of number.
- **P&L** - the profit export's `Net Sales` over its units, for the closed
  months. The one that ties to the statement above, and the one to use when
  the question is about margin rather than about price.

They are not interchangeable: `Net Sales` has had the sales deduction taken
out of it and `Order Value` has not, so the same model reads perhaps fifteen
per cent higher on Orders. The card used to be on P&L with nothing saying so,
sitting between a card headed *Oct 2026* and one headed *1 Oct - 28 Oct*, and
the difference read as a price that had jumped.

The weighting is by **units**: `RRP = sum(list price x units) / sum(units)`
over the slice's combinations, so a price that changed during the year
averages across the months by how much sold at each. Signed units, not
absolute: returns are in these figures by default, and a combination that came
out net negative was adding its units to the weight while subtracting its
money from the price.

**Returns are in**, which the card says. A credit takes its units and its
money back out of both sides of the division, so the ASP is net of what came
back; `--no-returns` takes them out and the card says that instead.

**It is not the ASP on the card below.** That one is the order export's own
money - `Order Value` - over the order export's units, and this one is the
profit export's `Net Sales`. Different columns from different files, over
different months, so the same model reads at two prices and neither is wrong.
The card below names its own column in the header and says so in the hint.

**The discount is read over the units that have a list price**, which is not
always all of them: the plan does not price everything. Each tile says what it
is read over whenever that is not the whole slice, and the discount tile also
gives those units' own ASP - without it, a list price that reads *lower* than
the ASP beside it looks like an error rather than two figures over different
sets. Mixing the two - a list price from one set of units, an ASP from another
- is how a page comes to quote a discount nobody ran.

Where there is no plan, or nothing picked has a list price, RRP and the
discount read `-` and say which of the two it is. `--rrp CODE` chases a single
product down; see **The two price sheets** above for where the list price comes
from.

There was a **Per unit** mode that divided every bar by the quantity behind it.
It is one tile now - **ASP** - because that was the only per-unit figure anyone
read off it, and a mode you have to remember you are in costs more than the one
number it was carrying.

ASP is the weighted price: the totals divided, never the average of the rows'
own prices. It sits in the tile row, in the KPI row under **Numbers**, and in
the table as `ASP`, always on net sales over net quantity. The drill runs down
to the **SKU**, so a category price can be opened until the model behind it
shows.

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
month reads as clearly as inside a large one. Expanded, the tooltip keeps the
amount behind each share: a share with no size behind it is how a rounding
error comes to look like a trend. It is off the menu in P&L mode, which is not a mix.

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

### What the file is called

```
dashboard/PNL_OCT.html
```

Named after the month the page is **read for**, in capitals, with no year:
the folder holds one page per month and a rebuild replaces the page it
supersedes rather than leaving a `_2`, a `_final` and a `_v3` beside it.

That month is the **order export's**, not the profit exports' - October's
orders are what the page is opened for while September's profit is the newest
closed month behind it. Nor is it the calendar's: taking it off the clock
would rename the October page to November on the first of the month, which is
exactly when October is still being closed. Without a daily chart there is no
open month and the newest profit month names the file instead.

`--out` overrides it, and `--no-promo` adds `_NOPROMO` so the two builds do
not overwrite each other.

### The tab says which page this is

The page's `<title>` is built rather than fixed, because it is two things at
once: the browser tab, and the name a browser offers when someone saves the
file. Three of these get opened side by side, and a static `Profit` had every
tab reading the one thing they all have in common.

```
Aug 2026 - Sep 2026 Profit - to 27 Oct - built 28 Oct 2026
```

The months it covers, the day the open month is read to, and the day it was
built. Plain characters and hyphens, since this becomes a file name. It is set
once at load rather than in `render()`: a title that moved as the page was
narrowed would rename the file a reader is about to save.

The build date comes from the build (`built` in the payload), not from the
browser, so a page opened next March still says when it was made.

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

> **Promotion** -> **DTC campaign 1** -> **DTC campaign 2**

Three bands, which is what the page is read for:

| | |
|---|---|
| DTC only | a plan line covering that product on that date names a DTC campaign **and no nationwide one** |
| DTC + Nation-wide | it names **both** |
| No promotion | nothing above, **and** what no order could be banded at all - no DTC promotion brought it in either way |

The three are **exclusive**: a unit is in one of them. See *The shape* below -
DTC + Nation-wide does not contain DTC only.

Clicking **DTC only** opens it by **DTC campaign 1**, and clicking one of
those opens it by **DTC campaign 2** - what ran inside that campaign. The plan's
two DTC columns are a hierarchy, so they are two levels: joined into a single
`A + B` value they were neither campaign and there was nothing to open. Names
are folded to one spelling each, so `DTC Boost week` and `DTC Boost Week` are
one bar.

Three blanks, three different statements:

| on the page | what the plan holds |
|---|---|
| `(no second campaign)` | the first column names a campaign and the second is blank - there was not one |
| `(named in campaign 2)` | the **first** column is blank and the second names a campaign. There is a campaign; the plan wrote it in the other column. Clicking the band drills to the column that holds it |
| `(no campaign)` | both columns blank. The line is live and names nothing, which is what puts the band in **No promotion** |

The middle one is not an edge case: **3,374 lines** across the two plans are
like it, and whole programmes live there - CE's `Tech Upgrade`, `BOOST WEEK`,
`SECRET SALE` and `FLASH SALE`, MX's `SmartThings`, `W9U2 Launch` and `Aging`.
Reading those as "no campaign" said the opposite of what the plan holds, which
is why the label names the column instead. Where a product is in two campaigns
at once the names are joined with `+`, so `Aging + SmartThings` is one value
and not two.

### The shape

**The bands are a partition, not a nest.** Every unit is in exactly one of
them, and neither of the two DTC bands contains the other:

| | what it holds |
|---|---|
| **DTC + Nation-wide** | the DTC business that had a **nationwide campaign running over it as well** |
| **DTC only** | the DTC business that did **not** |
| **No promotion** | everything else |

So **all the DTC business is the two together**, and the same campaign can
appear in both - `Tech Fest` under DTC + Nation-wide in one month and under
DTC only in another, split by whether a nationwide campaign overlapped it.
There is no one control that selects both; *All* at the Promotion level gives
everything, No promotion included.

Bottom to top, always the same order, each band full width, stacked like any
other split. The order is fixed rather than sorted by size: a band that moves
between months cannot be read along a time axis at all.

> They used to be drawn as a **nest** - the DTC band inset inside the
> nationwide one, to say a DTC sale sat inside the nationwide campaign that ran
> over it. The drawing said something the data does not, and it read as
> *DTC + Nation-wide contains DTC*, which is the wrong way round: the wrapped
> band is the one **without** a nationwide campaign. The nest is gone and the
> labels carry the distinction instead.

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

### Taking a band out, or keeping only it

A legend entry is a switch. **Click** takes that band out of every bar - and its
dotted margin line with it, or the chart keeps a line for a band it is no longer
drawing. **Double-click** keeps only that band, and double-clicking the band
that is already alone puts the rest back, so the gesture is its own undo. Reset
clears both: a band switched off is as much a narrowing as a filter is.

**A filter is a filter, and only the Stack by buttons change the stack.**
Narrowing a level that the current stack does not contain says which rows to
count, not what the bars are split by - so picking Div 1 DA while stacked by
Promotion shows *that division's* promotions, which is what the pick was asking
for. It used to move the page into that level's own chain instead, so the bars
stopped being promotions and became products.

Narrowing a level the stack *does* contain still steps the split down, and a
bar click is exactly that: a bar is always a level of the current chain.

**Back steps back inside the stack you are on**, and is disabled at that stack's
first level. Measured against the whole page instead, it stayed alive at the top
of a chain and widened a narrowing belonging to a different one - which is how
Back out of Customer landed on Product, and Back out of Promotion landed on
Biz. A SKU picked earlier is still a narrowing; it is just not the one Back
was pressed for.

### One campaign, day by day

**Pick a campaign and its own days open over the page.** The month chart says
how big a campaign was; this says how it went - the shape of a launch, whether
a pre-order built or spiked, whether the last week was worth running.

```
FF8 Pre-Order
Launched 16 Jul · ended 13 Aug · 29 days · 36 units ordered · 81,408 · 1.2 a day

  ▍30d before │ ▍ ▍▍ ▍ ▍ ▍▍▍ ▍ ▍ ▍ ... one bar a day ... │ 30d after
```

- **Between the two dates, one bar a day.** A day with nothing sold is a gap
  in the run, not a day the chart skipped, and **nothing is drawn past the end
  date** - a bar there would say the campaign was still running.
- **Either side, one averaged bar**: the same products' **units a day** over
  the month before it opened and the month after it closed. Those days are not
  the campaign's and are not worth a bar each; the question they answer is
  whether the campaign moved the rate, and the footer says by how much.
- The outer bars are a **different measure on the same axis** - units a day,
  not units - so they are drawn in another colour and named for what they are.
  Where the export does not cover those days, they are not drawn at all.
- **The window is drawn, not just written.** A tint sits behind the bars
  inside it, a dashed rule marks each edge, and the two dates ride on the
  rules - `Launch 16 Jul` and `End 13 Aug`. The outer bars fall outside the
  tint, which is the point of drawing it: what the campaign did and what the
  same products did around it should not need a caption to be told apart.

It follows **the products the campaign named**, not the banding: outside its
window a campaign bands nothing, so a before and an after could not exist. And
it counts on **the day the order came in**, which is the day the promotion was
live - not the day it shipped.

A campaign name comes round again - Black Friday ran last year and runs this
year - so the plan's lines are folded into **runs** and the run with the most
units is the one drawn. Only overlapping lines merge, with two days of slack
for a weekend: a fortnight of slack chained a quarter of short bursts into one
run, taking the real plans from 131 runs to 94 and the 90th percentile from
112 days to 176, which is a campaign nobody ran.

Some names are used **all year** rather than for a campaign - the plans carry
a `Tech Fest` line running fifteen months - and a run over **70 days** is
drawn **a week at a time** instead, labelled `w/c 2 Oct`. The header says the
run's real length and that it is weekly, and where a run crosses a new year
the dates carry it.

**Campaign days** on the chart's own row reopens it; Escape, the veil or
Close puts it away. The button is live only while one campaign is picked.

### How a profit row gets a promotion on it

The profit file has no promotion. Each combination is split across the
promotions its orders came in on, in proportion to the units each carried, and
the split rides the spreading the order side already used - an order that cannot
settle a level lands on the combinations it is consistent with, in the shape
those rows already have. What no order could band keeps a row of its own, so the
month still comes to its own total.

**Most of it is not divided at all.** A combination whose orders all came in on
one band keeps the profit file's own figure - its share is 1.0 and there is
nothing to assume. Only a combination carrying two bands at once has to be
split, and the run says how much of net sales that is:

```
  of that, 0.0% of net sales sits on a combination whose orders came
  in on more than one band and so had to be divided between them, by units.
  The other 100.0% is the profit file's own figure, undivided.
```

Where it *is* divided, the split goes by units, which assumes a promoted unit
earns what an unpromoted one does - the one thing a discount does not do. Read
the percentage before reading the margins: it says how much of the page that
assumption touches. The order line carries its own amount, so that share could
be split by money rather than by units; it is not today.

#### Why a campaign that ended in April still has revenue in June

**The band follows the order; the bar follows the revenue.** A line is banded
on the day it was *ordered* - the promotion was live when the customer bought,
not when the warehouse got to it - and it sits in the month it was *earned*,
which is the month it left. The two are the same month for most of a DTC book
and not for the tail:

- an order taken inside the campaign that **ships later** - a backorder, a
  launch allocation, a corporate order with a delivery date,
- a **return or a credit** against one of those orders, which lands whenever it
  is settled and carries the band of the order it reverses.

So `S26 Launch` ending on 8 April does not mean its row is empty from 9 April.
A tail two or three months long is the shape to expect, and it is usually
**small and often negative**: a band whose margin goes to -19% and -28% in the
months after a campaign is credits, not selling. Check it by narrowing to that
campaign and switching **Figure** to **Qty** - a tail with money but barely any
units is the allocation, not a sale.

And it *is* an allocation: a combination's whole month is split across the
bands its orders came in on, by units. One carried-in order from March in May's
order set therefore pulls a slice of that combination's May profit onto the
March campaign, in proportion to its units. The slice is right in aggregate and
is not a claim about those particular units.

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
py dashboard\build_pnl.py                      # -> dashboard/PNL_OCT.html
py dashboard\build_pnl.py --promo-bands all    # five bands, not three
py dashboard\build_pnl.py --no-promo           # -> dashboard/PNL_OCT_NOPROMO.html
```

**The split keeps the plain name.** It once went to a file of its own so a new
page would not replace the one being read that day; it is the page now, and
the build without it is the one that gets marked. `--plan` names the plan
files.

**One division has gone by several names.** The MX plan was `MX_product` and is
now `MX_promo_<yymm>`, so the default is written with a bar -
`mx_promo|MX_product ce_promo|CE_product` - and each division takes the first
of its names that matches a file in the folder. A dated series resolves to its
**newest** cut, so `MX_promo_2610` wins over `MX_promo_2609` sitting beside it;
nothing has to be renamed when next month's lands. `--plan MX_promo_2610`
still names one file outright.

A disabled button looks exactly like a broken one, so a build that bands nothing
says so at the end, with what it would need:

```
Stack by Promo will be OFF on this page: nothing was banded by promotion.
  It needs an order source (SAP orders_* or the store export) and a plan
  (--plan, default mx_promo|MX_product ce_promo|CE_product) that lists the products sold.
```

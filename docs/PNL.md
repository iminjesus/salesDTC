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

The selects cascade - picking a Type leaves Portal Group listing only that
Type's values, and a level with nothing left to choose greys out.

### The chart itself

| Control | What it does |
|---|---|
| **click a bar** | open that member, and move the bars to the next level |
| the breadcrumb | go back to any step of the path; **All** returns to the top |
| **← Back** | step out one level |
| the six selects | Channel, Type, Portal Group, Type2, Division, Category |
| **Bars by** | which of those is on the x axis |
| **Table** | every figure behind the bars, with the margin |

Clicking a bar and changing a select are the same act: narrowing to one value
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

A value missing from a select is one of three things, and these separate them:
the cascade is hiding it (the select says how many and under which level), no
row of this export carries it, or it lives in a column no level reads. The last
one is fixed by adding the column's name to `LEVELS` in `tools/customer.py`.
- `N total(s) read straight off the layout, M column(s) left to place` - a large
  M means the export is not printed as totals-then-lines, and most of the work
  fell to the wider search.

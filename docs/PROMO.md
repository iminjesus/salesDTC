# Which promotion did an order come in on?

```powershell
py tools\promo.py --division MX        # what the promotions look like, in three levels
py tools\promo_match.py --profile      # describe both files, change nothing
py tools\promo_match.py                # attribute, and cross-check the two
```

## Three levels, widest first

The store's codes are unreadable in bulk - hundreds of them, few shared between
months. `tools/promo.py` pulls each one apart into three levels and reports how
far each gathers:

| | |
|---|---|
| **offer type** | the mechanic: PWP, GWP, Discount, Cashback, Bundle, Trade-Up |
| **offer** | what it was on, with the mechanic taken out - `S25-LAUNCH-10PCT` |
| **rule** | the code itself, dates and all |

A cell holding two rules keeps both. A line that ran under two offers ran under
both, and picking one would quietly halve the other.

The run prints, per level, how many distinct values there are and **what the
eight biggest would cover** if a chart stacked by it - a level that gathers
badly is one a chart cannot say much with.

## Can the profit page stack by promotion?

That is a different question, and the last block of `promo.py` answers it with a
number. A profit row is one customer and one product; a promotion belongs to an
**order**. So a profit row can only carry a promotion by being shared out over
the promotions its own orders ran under, and that is honest only where a row's
orders mostly sit on one.

The run measures exactly that, per level, on the finest key the two files share
(portal group x product code):

| | |
|---|---|
| **on one** | the share of rows whose units sit on a single promotion |
| **units on the biggest** | the average share each row's biggest promotion holds |

High on both and a stack by promotion is near enough a measurement. Low and the
chart would be apportioning, which is worth knowing **before** it is built
rather than after.

`--division MX` asks the question of one division; `--month 2608` of one month.
Output goes to `docs/promo_levels.csv`, which is **not** committed - like every
other csv these tools write, it holds real customers and real revenue.

## The order export already knows

`26 DTC Aug` carries **`promotion_rule`** - the code the store itself applied -
and **`Voucher Code(s)`** - what the customer typed. Neither is a guess, so
both are used before anything is inferred. Three sources, in order of how much
they can be trusted, and every row says which one answered it:

| Source | |
|---|---|
| `rule` | the store's own promotion code, parsed into something readable |
| `voucher` | the order's voucher found in the plan's `Voucher_Code` |
| `plan` | the SKU, in a promotion whose window covers the order date, at a price near the one paid - **an inference** |

A rule like `AU_EPP_WEB_SP_14AUG26_09SEP26_PWP_S-SERIES-WATCH-30PCT` is pulled
apart on its dates: whatever sits before them says where it ran, whatever sits
after says what the offer was. The shape is read off the dates rather than off
fixed positions, because the positions vary. One cell can hold several rules,
comma-separated; all of them are kept.

## The plan

`MX_product` has no single promotion-name column, so the label is built from
`Nationwide_Campaign`, `DTC_Campaign2` and `Offer_Type` - whichever are filled.
Lines whose `Status` or `PUMI` reads cancelled, tentative, draft or rejected
are **left out**: nothing sold under a promotion that was never live.
`--keep-cancelled` keeps them, and cancelled orders, in.

Every price column the plan carries - `S.COM_Price`, `T1_Price` … `T3_Price`,
`EDU_Price`, `RRP` - is tried, nearest to what was paid. Which one won is
written on the row, so **`paid the T2_Price`** says which tier the customer was
on without the portal having to be mapped by hand.

### The two prices must be on the same basis

`AUD Revenue excl. GST` is a line total without tax; the plan quotes retail
prices per unit. So the amount is divided by the quantity and grossed up by
`--gst` (10 by default) before anything is compared. `--amount-is unit` turns
off the division.

The run prints the **median gap**. Near zero means the two agree; far from zero
means they do not, and every comparison is then wrong in the same direction:

```
price paid vs plan price, 1,361 comparison(s): median +2.43, from -277.64 to +129.88
a median far from zero means the two quote prices on different bases - try --gst or --amount-is
```

Check that before trusting the split.

## Reading the result

```
attributed 3,785 order line(s) (215 cancelled left out):
   2,130   56.3%  the store's own promotion rule
     250    6.6%  a voucher the plan lists
     335    8.9%  inferred from the plan - code, window, price
   1,070   28.3%  nothing fits
  of 467 line(s) the rule and the plan both answered for, the mechanic matches
  on 125 and differs on 342
  689 line(s) carry a rule whose own dates do not cover the order date
```

Two cross-checks, both chosen so they mean something:

- **The mechanic.** The rule and the plan name promotions in different
  vocabularies - a rule says `PWP`, the plan says `Black Friday / PWP` - so
  comparing the names would measure nothing. The mechanic is the part both
  spell, so that is what is compared.
- **The rule's own window.** A rule names the dates it runs between. An order
  dated outside them needs no plan to spot, and says something is wrong with
  one of the two files.

`why nothing fit` splits the misses into the three different answers they are -
no plan line for the product, nothing running that day, or a price no promotion
offers - because each wants something different done about it.

## Matching dirty data on purpose

The rules above are the strict ones. When the files are not yet clean, what
matters is knowing what each loosening is worth and what it costs, so the run
counts both rather than leaving it to be guessed at:

```
what looser matching would buy, on the lines nothing fits now:
  --stem 8                     1,204 more line(s) - the same model in another colour
  --window-slack 3               192 more line(s) - ordered that close to a window
  --window-slack 7               365 more line(s) - ordered that close to a window
  --price-tolerance 10           105 more line(s) - paid within 10% of a plan price
```

| Flag | What it loosens |
|---|---|
| `--stem N` | a product code matches on its first N characters, so the same model in another colour or capacity finds its plan line. Try 8 |
| `--window-slack DAYS` | an order this far outside a window still counts; the row records how many days out it was |
| `--price-tolerance PCT` | how far the price paid may sit from a plan price (3 by default) |
| `--agree PCT` | how much of a portal group's accounts must agree before a customer level is taken as settled (80 by default) |

Every one of them is a *looser* rule, not a better one. So nothing is hidden:

- The row's **`Matched by`** carries the whole chain - `code starts with
  SMS931B, in window give or take 4 day(s), paid the T2_Price` - and
  **`Days outside window`** is its own column.
- On the page, a plan match that needed a loosened rule is **its own colour**,
  counted apart as *Loosened rule*. A bar that is mostly yellow is held up by
  the loosening and will move when the data is cleaned; a bar that is mostly
  blue will not.

That way a loosening can be turned on to see the shape of the month, and read
back off afterwards.

## What comes out

| File | |
|---|---|
| `docs\promo_orders.csv` | one row per order line: source, promotion, the raw rule, the voucher, what the plan would have said, how it matched, which price column, and the gap |
| `docs\promo_summary.csv` | per source and promotion: order lines, units, amount |

Both are UTF-8 with a BOM, so Excel opens them without the import wizard.

The plan's answer is kept **on every row even when a rule won**, in `Plan says`
and `Plan matched by`. That is what makes the two comparable rather than one
overwriting the other.

## The page

```powershell
py tools\promo_match.py --html        # -> dashboard\promo_2608.html
```

One self-contained file with the profit chart's controls - the same cascading
selects, breadcrumb, **← Back** and **Bars by** - and three things on it:

- **How each line was attributed** - the KPI row and a daily stacked bar. The
  grey band is what nothing could answer for, and *its shape over the month* is
  the thing to look at: a flat grey band is a systematic gap, a spike is one
  day's promotion missing from the plan.
- **Revenue by offer**, biggest first. The page opens on **Offer Type** -
  Discount, PWP, GWP, Bundle - and clicking a bar opens it by **Offer Detail**,
  then on into Product Category. Each bar is *stacked by which source answered*,
  so a bar that is mostly blue needed no inference and a bar that is mostly
  green rests entirely on the SKU-window-price guess.

  Both sources land on the same two levels: the plan names an `Offer_Type` and
  an `Offer_Detail`, and a rule runs the same two together in its code, so the
  mechanic is read back out of it (`DISC` → Discount) rather than charting two
  vocabularies that cannot be compared.
- **Why nothing fit**, as a table, since each reason wants something different
  done about it.

### The customer half

The order export carries a **portal group**, not a payer - and its vocabulary
is not the customer master's `Portal Group` column. `S.COM` and `EPP` are
spelled in the master's **Type**, `EDU` and `Partnership` in its **Type2**, and
the master's own Portal Group holds different words again (`EPP External`,
`3PD`). Matching one named column against another misses almost everything.

So every value of every level is indexed as a possible spelling, and a lookup
returns **only what the accounts behind it agree on**. Asking for `EPP` settles
the Type, because every account spelled that way carries it; it leaves Type2 as
`(master does not say)`, because those accounts carry several. That is worth
more than a plausible guess, and it reads differently from
`(no customer match)`, which means the group was not found at all.

The build prints which column each group was found in and what it settled:

```
portal groups: 42,151 of 42,151 line(s) found their group in the customer master
  EPP        11,953 line(s)  <- Type; says type=EPP / channel=E-STORE
  EDU         8,952 line(s)  <- Type2; says type=EPP / portal=EPP External / type2=EDU
```

What comes back is the hierarchy the profit chart drills:

```
Channel -> Type -> Type2 -> Portal Group -> Portal -> Offer Type -> Offer Detail -> Product Category
```

**Portal** is the order file's own finer column - `samsung_benefits_au`,
`commbank_yello_au`, `au` - so it breaks a portal group down without inferring
anything. Where Type2 is unsettled because one portal group spans several of
them, Portal is usually the level that actually separates them.

A level the master cannot settle is explained rather than left blank:

```
EPP     11,953 line(s)  <- found in Type; settles type=EPP / channel=E-STORE
    type2 unsettled: EDU 46%, GOV 26%, Corporate 20% ...
```

That is the whole answer to "why is Type2 nearly empty": a single portal group
value cannot pick between four Type2s its accounts carry. `--agree` lowers the
bar (default 80%) if the commonest is good enough for the question being
asked.

A portal group whose accounts disagree on a level takes the value most of them
carry, and the disagreement is printed - it is a judgement, not a lookup, so it
is not made silently.

Rows are rolled up to one per source, per level value and per day - always
fewer than the order lines, usually far fewer - so the page stays small and the
filters and the drill work off sums.

### What it can cover

The plan only lists one division, so nothing outside it can be attributed at
all. The build prints the order export split by division, which is the ceiling
on what any of this can explain:

```
the order export by division - the plan only covers what it lists, so the rest
cannot be attributed at all:
  MX                     28,140 line(s)   66.8%
  TV & SD                 7,905 line(s)   18.8%
```

## When a guess is wrong

`--profile` prints every column of both files and then the columns it chose.
Each can be named directly: `--order-rule promotion_rule`, `--promo-name
DTC_Campaign1`, `--order-amount "AUD RRP"`, and so on. The columns decide every
number below them, so fix those first.

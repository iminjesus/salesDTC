# Which promotion did an order come in on?

```powershell
py tools\analyze_structure.py                 # everything in rawdata\ -> rawdata\sales.db
py tools\promo_match.py --profile             # describe both files, change nothing
py tools\promo_match.py                       # -> docs\promo_orders.csv, docs\promo_summary.csv
```

Two files: a promotion plan (`MX_product`), one row per product per promotion
with a window and usually a price, and the orders themselves (`26 DTC Aug`).
Neither says which order belongs to which promotion - that has to be inferred,
and the inference can be wrong, so nothing here is asserted quietly.

## Start with --profile

It prints every column of both files - what it holds, how full it is, how many
distinct values, three samples - and then the columns it would use:

```
columns chosen  (--flags override any of these):
  MX_product.csv     product code   'Model Code'
  MX_product.csv     starts         'Start Date'
  26 DTC Aug.csv     product code   'Model'
  26 DTC Aug.csv     price paid     'Unit Price'
```

Any of them can be named directly: `--order-sku Model`, `--promo-start "Valid
From"`, and so on. Get these right before reading any number below them.

## How a match is decided

Three tests, in order, and each one is recorded on the row:

1. **The code.** Exact first, then the same code with punctuation and case
   removed, then the longest plan code the order code *starts with*. A plan
   lists a model family, `SM-S931B`, where the order carries the code it was
   actually sold under, `SM-S931BZKAXSA`. That last rule is an inference, so it
   is written out as `code starts with SMS931B` rather than left to look like a
   match.
2. **The window.** A promotion that was not running on the order date cannot
   have sold it. Plan lines with no dates stay in the running - they are
   standing offers, not expired ones.
3. **The price.** Where both files carry one, the promotion whose price the
   order actually paid is the one it came in on. An order that paid **full
   price** did not come in on a promotion however neatly the code and dates
   line up, so it is rejected rather than credited with a discount that was
   never given. `--price-tolerance` sets how close is close enough (3% of the
   promotion price by default; `--price-tolerance 100` effectively turns the
   test off).

Where more than one promotion survives all three, the best is used and the row
says how many others also fit, in `Other fits`. Those are worth looking at: the
plan genuinely cannot tell them apart.

## Reading the result

```
attributed 940 order line(s):
       225   23.9%  one promotion fits
       237   25.2%  more than one fits - the best is used
       478   50.9%  none fits
  price paid vs promotion price, over 761 comparison(s): median +0.00 ...

why the rest did not match:
     299  the price paid is not a promotion price
     159  the plan has no line for this product
      20  no promotion was running on the order date
```

"None fits" is three different answers and each wants something different done
about it, so they are counted apart. The product codes the plan never mentions
are listed with their line counts, beside what the plan *is* keyed on - a
mismatch of code systems shows up there immediately.

**The median price gap is the one to check first.** Far from zero means the two
files quote prices on different bases - one including tax, or one per line
rather than per unit - and every comparison is then wrong in the same
direction. Fix that before trusting the split.

## What comes out

| File | |
|---|---|
| `docs\promo_orders.csv` | one row per order line: the promotion, **how** it was matched, the price gap, and how many other promotions also fit |
| `docs\promo_summary.csv` | per promotion: order lines, units, amount |

Both are UTF-8 with a BOM, so Excel opens them without the import wizard.

`Matched by` is the column to read when a number looks wrong. It carries the
whole chain - `code starts with SMS931B, in window, nearest price` - so a
result can always be traced back to the rule that produced it.

## The database

`tools\analyze_structure.py` loads **every** file in `rawdata\` into
`rawdata\sales.db`, one typed table each, named after the file:
`mx_product`, `26_dtc_aug`, `customer_2608`, `profit_2608_3`. Columns holding
amounts become `REAL` so SQL can sum them; codes stay `TEXT`, because a product
number with a leading zero is not a number. `column_map` keeps the original
header beside each column name.

So the same question can be asked in SQL, once the matching rules are settled:

```sql
SELECT promotion_name, COUNT(*) FROM "26_dtc_aug" o
JOIN mx_product p ON o.model LIKE p.model_code || '%'
GROUP BY 1;
```

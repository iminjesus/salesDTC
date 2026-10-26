# Cost of goods, online against offline — on the same models

```powershell
py tools\channel_cogs.py
py tools\channel_cogs.py --export profit_2609 --top 25 --out docs\channel_cogs.csv
```

Online shows a higher cost of goods than offline. That is two questions wearing
one number: online may be selling **a different basket** - more of the models
that were always thin - or **the same models may behave differently there**.
Only the second is about the channel, and only the second can be acted on.

So the export is read twice: once as it stands, and once over the models that
**both** channels actually sold.

## Three readings, three different questions

| | |
|---|---|
| `CoGS %` | cost of goods over net sales - the ratio the P&L shows |
| `CoGS/unit` | what the goods cost. The same model costs the same to make, so a gap here is **cost being loaded onto the channel** - freight, returns, units given away - and is not a price at all |
| `net/unit` | what the channel realised per unit. A gap here **is** a price, and has nothing to do with cost |

`deduct/gross` sits beside them because it explains most of the gap before
anything is sold: **offline pays its channel through sales deduction**, which is
a cost line, while **online takes its discount off the price**, which never
becomes a cost at all. Two channels at the same real discount therefore show
very different cost stacks, and cost of goods looks like most of the online one
simply because nothing else is in it.

## The cost stack, which is the other question

"Cost of goods is most of the cost online" is **not** the same question as
"cost of goods over net sales", and it has a different answer:

```
the cost stack, which is the other question
              cost of goods  sales deduction  CoGS share of the two
  online         12,502,165          554,197                  95.8%
  offline       154,190,110       47,541,857                  76.4%
```

Offline pays its channel through **sales deduction** - 19.5% of gross in that
run - and that is a cost line sitting beside cost of goods. Online takes its
discount **off the price**, where it never becomes a cost at all: 3.0%. Same
economics, very different stacks, and cost of goods is most of the online one
because nothing else is in it.

## The bridge

The gap on the common models is split the way a price/volume bridge is:

```
same models, both channels: online 62.0% vs offline 50.0%  (+12.0pp)
  which basket (mix)                     0.0pp   the same models weighted the way each channel sells them
  the models themselves (rate)          12.0pp   each model against itself, weighted as online sells
      what the goods cost                2.0pp   cost per unit, online against offline
      what they sold for                10.0pp   net sales per unit, online against offline
                                    --------
  the gap                               12.0pp
```

- **mix** holds each model's own ratio and moves the weights.
- **rate** holds the weights and moves the ratios, and splits again: a model's
  ratio is `cost per unit ÷ net per unit`, so it can only move because the goods
  cost more or because they sold for less. Each effect is read at the other
  side's level, which is what makes them add back to the whole.

The run then says which of the two it is, in those words, because the answer
decides where to look next: a **cost** gap is freight, returns, giveaways and
cost lines charged to one side only; a **price** gap is the channel mix and the
stacked offers - EPP, education, staff, always-on vouchers - and nothing in the
cost ledger will explain it.

## Returns

Credits for goods that came back are **left out by default** (`--returns`
keeps them): negative units against a cost that does not always follow them is
exactly the row that makes a per-unit figure meaningless. The run says what
went.

The cost columns are read by **the column's own sign**, decided once from
where its weight sits, rather than by taking each row's absolute value. Some
exports carry a cost as a negative number throughout; taking the absolute value
row by row read a credit - whose cost is reversed on purpose - as another cost,
and added it.

## Rows that are not prices

An export carries more than shelf sales. Credits, free-of-charge shipments,
samples and returns all arrive as a quantity with little or no revenue against
a full cost, and in a ratio they are not a small error:

```
1 model(s) left out of the bridge: cost of goods over net sales outside 20-150% on one side or the other
  24,900 of net sales between the two channels. They are not prices - credits, free goods, samples and returns read this way
    SMX930NZAAXSA      online     84% offline    2804%   net/unit    1,241 /       36   Galaxy Tab S11 Ultra
```

The bridge **divides by that price**, so one such model moved the price effect
by 29pp on a gap of 7. A model is bridged only where both sides land inside
`--band` (default `0.2 1.5`); what falls outside is counted and the biggest are
named, because "sold below cost" is a finding of its own rather than noise.

The same shape turns up in the headline as the **unplaced** row - units on a
customer the master does not have. They are in neither channel and are reported
rather than folded into one.

## One account, both sides

```
  64 account(s) the master spells on both sides of the business carry 1,234 unit(s) and 567,890 of net sales here.
    Which channel they landed in came from the first row of the master, not from the sale - so that much of the split is a coin toss.
```

`E-STORE_B2B` in one row of the master and `off-line` in another, under the
same Sold-To. The master fills each column from the first row that has
anything in it, which is right for a detail column and arbitrary for a channel:
the first row then decides which side **every** sale of that account lands on.
Worth knowing how much money is riding on it before reading anything else.

## The listing

One row per model, biggest mover first, with both sides' units, net per unit,
cost per unit and ratio, and what it contributes to the gap in percentage
points. `--out` writes every common model as a csv - that is the file to sort
when someone asks which models drive it.

```
  model                 units on/off net/unit on      off  cost/unit on      off  CoGS% on     off     pp  name
  SMA                    100/100             800    1,000           500      500       62%     50%   8.33  Galaxy ...
```

`--min-units N` leaves out a model that sold fewer than N on either side: one
unit each way is a rounding difference wearing a percentage.

## One model, month by month

```powershell
py tools\channel_cogs.py --model SM-F971BZGDATS
```

```
  month   channel      units  gross/unit  deduct/unit   net/unit  cost/unit   CoGS %
  202607  offline      1,000       1,900            0      1,900      1,280    67.4%
  202608  online         200       1,870          170      1,700      1,280    75.3%
  202608  offline        400       1,900            0      1,900      1,280    67.4%
  202609  online         500       1,804          164      1,640      1,280    78.0%
  202609  offline        300       1,900          300      1,600      1,280    80.0%
```

A month answers nothing on its own when the two channels buy at different
times. Offline takes a launch allocation and pays the launch dealer price;
online sells the same model for the next six months through whatever promotion
is live. And the money that brings the retailer's price down - price
protection, co-op, a retro credit - is often booked in a later month than the
sale it belongs to, and sometimes against the account rather than against the
model.

That is why **deduction per unit is printed beside the price**: a dealer price
that looks higher than the online one, with nothing in its deduction column,
is a price whose discount has not landed on that line yet. The channel total in
the headline carries it; the model does not.

## What it will not tell you

- **Coverage.** The run says what share of each channel's net sales the common
  models are. Where that is low, the like-for-like answer is about a corner of
  the business and the headline gap is mostly basket.
- **A customer the master cannot place** sits in neither channel; the units are
  counted and reported rather than folded into one.
- **Where a cost sits** is the export's decision, not this tool's. If outbound
  freight is in operating cost for one channel and in cost of goods for the
  other, the `CoGS/unit` gap is real but it is an accounting boundary rather
  than a cost the business incurred twice. The cost ledger decides that, and
  this only says which models carry it.

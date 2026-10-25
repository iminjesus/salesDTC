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

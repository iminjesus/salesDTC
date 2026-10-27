# What is actually in a file

```powershell
py tools\peek.py                     # every file in rawdata, with its size
py tools\peek.py target              # that file's columns, with letters
py tools\peek.py orders --rows 5
py tools\peek.py profit --find commission
```

Three questions in a row turned on a column nobody could name from memory -
which letter the paid commission sat in, what the order export calls its
dates, what a target file is keyed on - and each one cost a round trip. This
prints the file instead.

```
orders_2610.csv: text, 106 row(s), 7 column(s)
   col  header                       row 1                   row 2
     A  Customer Reference (Header)  AU261001-90001          AU261001-90002
     F  Goods Issue Date             01/10/2026              01/10/2026
     G  Created On                   01/10/2026              01/10/2026
  also matching 'orders': orders_2609.csv, orders_2608.csv
```

Down the page rather than across it: a row of forty columns wraps in a
terminal and stops lining up with its header, which is the one thing this is
for. The letters are there because a column usually arrives in a question as
one - "it's in AK" - and a letter is positional, so it is worth seeing which
header it lands on.

The name is a **prefix**, resolved the way every other tool resolves one, so
`target` finds `target_2610.csv` and the newest cut of a series wins. The run
names the other files that matched, so a stale cut being read instead is
visible rather than silent.

It also says which columns are **empty in every row**. A figure matched to a
column that holds nothing is worse than one matched to nothing at all: it
draws as zero and reads as a business finding.

`--dir` points it somewhere other than `rawdata`. It reads csv, xlsx and xlsb
through the same reader the tools use, so a file that peeks cleanly is a file
they can read.

# Vendored libraries

Copied here so a built dashboard opens with no internet connection — the page a
colleague receives has to work on its own.

| File | Version | Licence |
|---|---|---|
| `chart.umd.js` | Chart.js 4.5.1 | MIT |
| `chartjs-plugin-datalabels.min.js` | chartjs-plugin-datalabels 2.2.0 | MIT |

`build_dashboard.py` inlines both into the generated HTML. Pass `--cdn` to link
jsDelivr instead, which makes a ~220 KB smaller file that needs a connection.

# Shared price and scan verification

This change does not migrate, remove or rewrite prediction, learning, recovery,
PostgreSQL or private user datasets. Production execution is not performed by
these development tests.

## Paths and evidence

The worker and web server both use `veri_yollari.paths().public`. With
`BIST_DATA_DIR=/data`, the quote file is `/data/public/borsa_fiyatlari.json` and
its HTTP route is `/data/borsa_fiyatlari.json`. Without the variable, the retained
local location is `webapp/data/borsa_fiyatlari.json`.

`[QUOTE_DATA]` reports provider observations, coverage, current-session count,
missing, delayed, stale and invalid data. `/health` exposes an allowlisted
`tasks.quote_refresh.quote_data` summary, including failure cases. An empty
response produces `QUOTE_NO_DATA`, never evidence of a successful price fetch.
`LAST_SESSION` explicitly describes verified cached closes, not live delivery.
Delay counts refer to the age of the last observed trade; transport latency and
real-time licensing are not guaranteed. Anonymous TradingView data may be delayed.

Subscriptions are added in batches of at most 100 on one borsapy stream.
After-hours cold starts use existing borsapy daily history, at most 10 symbols
per round. Failed history requests are retried no sooner than one hour.
Only completed XIST sessions are eligible, including weekends, holidays and
half days. A missing prior session is not replaced by an older candle. Prices
and daily returns use the same provider record and its prior-session close.
The V2 quote-format marker requests one new closing scan when the retained
worker state only certifies the previous quote-format revision.

## Damaged public projections

`public_veri_guvenligi.py` admits only four live projection names. Reads are
bounded to 16 MiB. A malformed original is never deleted, renamed or overwritten.
Newly generated rows are written atomically to one `<name>.pending.json` view.
The existing HTTP route serves that validated view, and stock-detail automatic
levels can read it. Until a valid view exists the damaged original is not served.
A damaged pending view is also preserved and raises an error. Writes are
serialized across threads/processes and preserve newer price groups.

`PUBLIC_JSON_CORRUPT` remains visible in worker diagnostics. The pending view
is not proof that unique contents of the damaged original have been recovered.
Those contents require independent forensic recovery; there is no automatic
cleanup or completion claim. History/user/archive files are excluded from this
projection helper.

## Full scan

FULL_SCAN uses the KAP-verified equity universe. Individual provider failures
and unsupported symbols retain existing batch isolation/retry handling.
`[FULL_SCAN_DATA]` and the private `full_scan_coverage.json` expose attempted,
successful, verified/current/stale price, failed, unsupported and remaining
counts. `/health.full_scan_data` contains only allowlisted counters/timestamps.
`cycle_complete` means the iteration reached the last symbol, not that all
symbols succeeded. Valid rows and existing prediction recording remain intact
when the original public projection is malformed.

## Detailed interface and tests

The detailed dashboard from Git commit `1340358` is retained, including manual
levels/alarms, push controls, intraday signals, tomorrow plans, model performance,
market regime and sector views. Current-price spans across these views use one
shared quote reader. Frozen forecast prices, target/stop values and historical
performance remain separate. Quote refresh does not replace user forms.
An unavailable analysis JSON does not prevent independently verified quote data
from loading; cached verified prices survive temporary fetch failures.

Unit tests use temporary directories/mock providers and include an 888-record
history preservation fixture, malformed JSON, concurrency, all 631 symbols,
missing previous sessions, half days and honest health states. Real borsapy
experiments in isolated temporary directories covered 10 symbols: quote
projection and FULL_SCAN both completed 10/10 with verified prices. GENKM on
2026-10-13 was 7.45 versus the previous session's 7.50 (-0.67%). These experiments
are not a production audit or real-data certification of all 631 symbols.

Review and deploy separately. Keep any server-only interface customizations and
all production data; do not use reset/clean commands or automatically overwrite
an uncommitted server dashboard. After an authorized rollout, verify the actual
quote counters and full-scan coverage in logs/health, not only process status.

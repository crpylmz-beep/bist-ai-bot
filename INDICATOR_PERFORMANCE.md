# İndikatör Performansı V1 — Ölçüm Modu

Existing `sinyal_performansi.py` analysis is extended, not replaced. Old condition/signal_type/period API filters remain compatible. No candidate is consumed by TOP10, learning ±3, BASE/LEARNED, intraday scoring, Tomorrow Plan or a decision engine. `production_applied=false` is required in every new report and candidate.

## Prospective frozen evidence

Only NEW AI/prediction records, NEW Yarın TOP10 freeze records and NEW Günlük AL/SAT events receive `INDICATOR_FEATURES_V1` evidence. Existing capture inputs and original fields are preserved. There is no backfill. Actual closed technical values, criterion flags and final-decision votes are copied; indicators and votes are never recalculated. A numeric value alone does not imply active/confirmed. Unknown/missing states do not become failures. Unsupported individual votes (e.g. SMA20 without an actual individual confirmation) remain unknown.

Daily technical bars must be business-session closed (18:10 bar, knowledge at/after 18:15); 5m bar start + 5m must precede knowledge time. Technical knowledge, criterion capture/model creation and context creation/as-of cannot follow the prediction. Context capture uses existing frozen Market Regime/Sector Strength guards. Failed supplementary capture logs a sanitized source error and stores FEATURE_NOT_CAPTURED; the original signal still saves.

Six daily horizons: 1/3/5/10/20/60 trading sessions. Intraday: existing 30m/60m/120m/SEANS/D1/D3 results only (D1/D3 presented as 1/3 inside their separate family). No outcome engine, success formula or historical-price provider is added. Daily quality/Stats/excursion validation and intraday source/hash/outcome validation are reused. BUY/SELL and signal families are independent. Pending, unverified, ambiguous, future and conflicting outcomes never enter resolved denominators.

## Observational statistics / candidates

Each feature/family/direction/horizon has sample/eligible/pending counts, success/failure/neutral counts, directional and raw return, mean/median/best/worst, MFE/MAE when verified, payoff ratio, state groups, 20/50 recent samples, frozen regime/sector groups. Success rate is verified positive directional outcomes / eligible resolved outcomes, using existing success semantics. Baseline is the same frozen-feature cohort, family, side and horizon. With/without compares actual active vs explicitly inactive votes. Unknown is neither inactive nor a failure. These comparisons describe association, not causation or statistical significance.

Thresholds: <30 insufficient; 30 early; 100 usable; 300 strong sample. Confidence = 100*n/(n+100) × resolved maturity × (.75+.25*complete return/MFE/MAE fraction) × freshness (1 within90 days; .5 older). A handful of successes cannot create high confidence.

Candidate (bounded [-1,1]):

```
(.60 × success-rate difference + .25 × clipped-mean difference/20 + .15 × clipped-median difference/20)
× n/(n+100) × m/(m+100)
× min(with confidence, without confidence)/100
× (.5+.5*min(1,abs(with median)/max(1,abs(with clipped mean))))
× recent agreement (1 or .5)
```

Return clipping ±10% affects candidate sensitivity only; original outcome/return metrics are unchanged. Missing independent-horizon or at least two adequately sampled regime comparisons halves the candidate; conflicting horizons/regimes halve it too. Negative observed evidence produces negative candidates. STABLE requires both groups>=300, both confidence>=70, at least two concordant horizons and two concordant regimes. STABLE is still an unapplied candidate, never production approval. Model versions: INDICATOR_PERFORMANCE_V1 / INDICATOR_FEATURES_V1 / INDICATOR_WEIGHT_CANDIDATE_V1. Five fixed combinations, each with >=30 actually active samples, prevent combination explosion.

## Shared persistence / worker

`INDICATOR_PERFORMANCE_ENABLED` defaults true; false disables supplementary capture, registration/runtime scheduling and returns a disabled API response. Existing worker callback `indicator_performance` runs every900s, configurable by `INDICATOR_PERFORMANCE_INTERVAL_SECONDS`. It runs without market gating because it reads outcomes; no new process, prices or provider calls. Task failures retain scheduler retry/backoff and do not block other tasks.

Under `BIST_DATA_DIR=/data`:

- `/data/public/indicator_performance.json`: generated public summary/candidates (no user data).
- `/data/runtime/indicator_performance_state.json`: private derived projection cache, file signatures, integrity hashes, exclusions.
- `/data/runtime/indicator_performance/YYYY-MM-DD.json`: compact immutable final daily metrics/candidate archive after session close; no OHLC or raw forecasts.

Without env, existing path helpers retain local layout. Source prediction histories, outcome files, immutable TOP10 archives and user data are read only. Atomic writes and shared locks protect derived files. Each observation shares one compact feature vector across horizon outcomes; no raw price history is duplicated. Unchanged file signatures reuse projections, unchanged report does not write. Changed source/result pairs reproject; date/time gates revalidate future observations. Corrupt derived caches rebuild; source corruption remains logged/DEGRADED and is excluded from current results, not silently reused. No retention deletes unique records.

## API / UI

`/api/indicator-performance` serves V1 by default (`?family=ALL` also selects its general view). Filters: indicator (16 allowlisted identifiers), family, direction BUY/SELL, horizon. Invalid queries400; absent/corrupt/future cache503. Legacy condition/signal_type/period queries retain their old report. Native collapsed mobile home card “İndikatör Performansı” shows Turkish labels, backend statistics, filters, sample/confidence/warnings, context breakdowns and “Ölçüm Modu — Skorlara uygulanmıyor”. No frontend score calculation; all returned text is escaped. Production/Railway/volume verification is intentionally left to the user’s production workflow.

## Validation

96 new Python tests; 131 indicator tests including the 35 existing regressions. Full offline Python suite: 1,414 passed. 18 JavaScript/frontend smoke groups passed; new mobile/desktop indicator suite: 44 assertions. Syntax: 143 Python files and inline JavaScript; eight module imports and temporary-root `ana_motor.py --check` passed. Existing 136 function bodies outside the permitted capture/routing/registration hooks, and 11 protected engine modules, were verified unchanged. No Railway or volume operation was performed.

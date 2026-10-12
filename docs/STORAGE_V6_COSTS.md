# V6 capacity and cost review — no paid resources created

Date: 2026-10-08. The official pricing pages below were attempted from this environment but returned ProxyError. Consequently there is **no verified current price quote**, and the extra $10/month target is **not proven**. No provider is selected or provisioned. Do not treat remembered prices, promotional credits or free tiers as a confirmed production budget.

| Option | Workload/cost considerations | Current quote |
|---|---|---|
| Railway PostgreSQL | Continuous DB container CPU/RAM + persistent storage; close to existing app, but compute is not free just because the application has Hobby | Not verified |
| Neon | Managed PG; compute active while the 24/7 worker writes, hot storage + WAL/history + transfer/restore settings; do not assume permanent idle/free compute | Not verified |
| Supabase | Managed PG with plan minimum, included DB allowance and overage; compare minimum paid plan and restore/backup guarantees | Not verified |
| Cloudflare R2 | Archive-only, not the transactional DB; compressed object storage, multipart/readback API operations and restore/egress policy | Not verified |

Official sources to verify before creating resources:

- https://docs.railway.com/reference/pricing/plans
- https://neon.com/pricing
- https://supabase.com/pricing
- https://developers.cloudflare.com/r2/pricing/

## Separate hot PostgreSQL and compressed R2 capacity scenarios

GB here is decimal billing GB; actual PostgreSQL size is measured by `pg_database_size`, including tables/indexes. PostgreSQL raw JSON size alone is not a capacity quote. Backups/WAL/compute must be priced separately. R2 capacity below is **stored compressed bytes**, not uncompressed source bytes. Compression must be measured on representative source data, not guessed from synthetic repetitive fixtures.

Let `C` = monthly PG compute/base fee, `P` = PG $/GB-month, `Ip` = included PG GB, `W` = other PG backup/WAL/operation cost; `R` = R2 $/GB-month, `Ir` = included R2 GB, `A` = R2 operation/restore costs. All variables require official current verification.

| Capacity | PostgreSQL monthly estimate formula | R2 monthly estimate formula | Maximum combined storage unit cost if compute/operations were zero |
|---|---|---|---|
| 5 GB | C + max(0,5−Ip)×P + W | max(0,5−Ir)×R + A | $2.00/GB-month |
| 10 GB | C + max(0,10−Ip)×P + W | max(0,10−Ir)×R + A | $1.00/GB-month |
| 25 GB | C + max(0,25−Ip)×P + W | max(0,25−Ir)×R + A | $0.40/GB-month |
| 50 GB | C + max(0,50−Ip)×P + W | max(0,50−Ir)×R + A | $0.20/GB-month |
| 100 GB | C + max(0,100−Ip)×P + W | max(0,100−Ir)×R + A | $0.10/GB-month |

The last column is mathematical budget headroom, **not a provider price**. PG and R2 are separate choices: e.g. 5 GB hot PG + 25 GB compressed R2 is `C + max(0,5−Ip)P + W + max(0,25−Ir)R + A`. A plan must include both that value and the added costs of continuous connections, full readback verification, archive writes, backups and monitoring within $10.

## Safe decision gate

1. Obtain current official quotes and explicit monthly spending limits.
2. Measure a readonly source inventory and actual compressed size in streaming dry-run or a separately approved archive upload.
3. Run migration/shadow tests against the funded staging DB; measure indexes/WAL and daily growth before cutover.
4. Select only a combination with demonstrated headroom under $10. A free-tier capacity below the required hot-data size is not a solution.
5. Provisioning and production cutover need separate user authorization; this code does neither.

No claim is made that 100 GB PostgreSQL can fit the stated budget. Keeping frequently accessed records in PG and large verified byte archives in R2 provides separate accounting, but successful data retirement is a future reviewed step. V6 never deletes a source merely because it was uploaded.

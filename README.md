# Quack on Demand + plain SQL

One SQL file builds two tables in a DuckDB file, and [Quack on Demand](https://github.com/starlake-ai/quack-on-demand) (QoD) serves them over Arrow Flight SQL, with authentication and access control in front.

No framework is involved: if you can write the DuckDB file, QoD can serve it.

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- qod 0.15.1 or later: `./run.sh` runs it with `uvx qod@latest` and checks the version before doing anything
- macOS or Linux (on Windows, use WSL2)
- Ports 20900, 20901, 21900, 31338, 9494 and 25432 free on your machine

## Run it

```bash
git clone https://github.com/starlake-ai/qod-recipe-sql
cd qod-recipe-sql
./run.sh
```

The first run downloads QoD and its runtime, which takes a few minutes. Later runs take seconds. You should see:

```
plain SQL built customers_enriched and daily_revenue into out/warehouse.duckdb
starting Quack on Demand on out/warehouse.duckdb (state in out/.qod, log in out/qod.log)...
QoD serving default_recipe_sql on 127.0.0.1:31338 (tenant=default, pool=bi)
top 5 customers by lifetime value (via FlightSQL):
  customer_id | name         | order_count | lifetime_value
  ------------+--------------+-------------+---------------
  43          | Jun Nguyen   | 12          | 1741.00
  16          | Ben Martin   | 8           | 976.45
  3           | Ines Okafor  | 6           | 952.20
  7           | Ines Rossi   | 6           | 764.95
  42          | Ben Kowalski | 5           | 761.50
check OK: top 5 matches expected/, daily_revenue has 82 rows totalling 20662.20
```

followed by connection strings for your own tools.

## What just happened

1. `pipeline/pipeline.sql` read the three CSVs in `data/` and built `customers_enriched` (one row per customer, with order count and lifetime value) and `daily_revenue` (revenue per day) in `out/warehouse.duckdb`.
2. `uvx qod@latest serve out/warehouse.duckdb` started a gateway in front of that file. It created a tenant `default`, a database `default_recipe_sql` and a pool `bi`.
3. `query.py` connected over Arrow Flight SQL, as any client would, ran the top 5 query and checked the result against `expected/`.
4. The gateway is still running, so you can connect to it.

The tables did not move or change format: QoD serves the DuckDB file where it is.

## Connect your own tool

The gateway listens on 127.0.0.1 only, so use that address rather than `localhost`, which some clients resolve to IPv6 first. Log in as `admin` with the password `recipe-admin`, with tenant `default` and pool `bi`:

```
JDBC   jdbc:arrow-flight-sql://127.0.0.1:31338/?tenant=default&pool=bi&user=admin&superuser=true&useEncryption=true&disableCertificateVerification=true
DuckDB ATTACH 'quack:127.0.0.1:9494' AS qod (TYPE quack, TOKEN 'tenant=default&pool=bi&user=admin&password=recipe-admin&superuser=true');
```

The admin UI is at http://127.0.0.1:20900/ui/. More clients (DBeaver, Power BI, Tableau, ADBC, ODBC) are covered in [Connecting clients](https://docs.starlake.ai/qod/connecting/clients).

The password is published here on purpose: this gateway is a throwaway that only accepts connections from your own machine. Never reuse it for a gateway you keep.

## Stop and clean up

```bash
./run.sh stop   # stop the gateway
rm -rf out      # remove everything the recipe created
```

The recipe keeps all of its state in `out/`, including its own QoD control plane, so your own QoD install, its password and your `qod` CLI login are never touched. Running `./run.sh` again stops the previous gateway, rebuilds from scratch and serves again.

## Next steps

- Serve your own data the same way: `uvx qod@latest serve ./your.duckdb`
- Add users, roles, and row and column policies: [QoD documentation](https://docs.starlake.ai/qod/)
- The same recipe with another tool: [dbt](https://github.com/starlake-ai/qod-recipe-dbt), [Dagster](https://github.com/starlake-ai/qod-recipe-dagster), [dlt](https://github.com/starlake-ai/qod-recipe-dlt), [SQLMesh](https://github.com/starlake-ai/qod-recipe-sqlmesh), [Spark](https://github.com/starlake-ai/qod-recipe-spark)

## License

Apache 2.0

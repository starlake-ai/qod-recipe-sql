"""Run pipeline/pipeline.sql into out/warehouse.duckdb, then close the file so
QoD can attach it."""

from pathlib import Path

import duckdb

root = Path(__file__).resolve().parent.parent
con = duckdb.connect(str(root / "out" / "warehouse.duckdb"))
con.execute(f"SET file_search_path = '{root.as_posix()}'")
con.execute((root / "pipeline" / "pipeline.sql").read_text())
con.close()

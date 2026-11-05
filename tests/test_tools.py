import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mistralai import agents

import main

SAMPLE = """region,mois,ventes,quantite
Nord,janvier,120.5,10
Sud,janvier,80.0,8
Nord,février,200.0,16
Sud,février,150.25,12
Nord,mars,95.75,7
"""


def run_all() -> None:
    ctx = agents.ToolCallbackContext.local()

    loaded = main.load_csv(ctx, SAMPLE, file_name="ventes.csv")
    assert loaded["rows"] == 5, loaded
    assert loaded["columns"] == ["region", "mois", "ventes", "quantite"], loaded

    desc = main.describe_columns(ctx)
    assert desc["rows"] == 5 and len(desc["columns"]) == 4, desc
    ventes = next(c for c in desc["columns"] if c["column"] == "ventes")
    assert ventes["mean"] == (120.5 + 80.0 + 200.0 + 150.25 + 95.75) / 5, ventes

    filt = main.filter_rows(ctx, "region", "==", "Nord")
    assert filt["matched"] == 3 and filt["total"] == 5, filt
    filt2 = main.filter_rows(ctx, "ventes", ">", 100)
    assert filt2["matched"] == 3, filt2
    filt3 = main.filter_rows(ctx, "mois", "contains", "jan")
    assert filt3["matched"] == 2, filt3

    agg = main.aggregate_by_group(
        ctx,
        ["region"],
        [{"column": "ventes", "function": "sum"}, {"column": "quantite", "function": "mean"}],
    )
    assert agg["groups"] == 2, agg
    by_region = {r["region"]: r for r in agg["rows"]}
    assert abs(by_region["Nord"]["ventes__sum"] - 416.25) < 1e-9, agg
    assert abs(by_region["Sud"]["quantite__mean"] - 10.0) < 1e-9, agg

    try:
        main.filter_rows(ctx, "inconnue", "==", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown column should raise")

    print("all tool tests passed")


if __name__ == "__main__":
    run_all()

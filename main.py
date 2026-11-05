import io
import os
from typing import Any

import pandas as pd
from mistralai import agents

DRIVE_CONNECTOR_NAME = os.environ.get("DRIVE_CONNECTOR_NAME", "google_drive_mcp")

_DATASETS: dict[str, pd.DataFrame] = {}
_SOURCES: dict[str, str] = {}

_OPERATORS = ("==", "!=", ">", ">=", "<", "<=", "contains", "isin")
_AGG_FUNCS = ("sum", "mean", "median", "min", "max", "count", "nunique", "std")

INSTRUCTIONS = """Tu es un analyste de données conversationnel, en français.

L'utilisateur te donne un lien vers un fichier CSV dans son Google Drive, puis te pose des questions en langage naturel sur ces données.

Flux de travail obligatoire :
1. Quand l'utilisateur fournit un lien Google Drive, utilise le connecteur Google Drive pour localiser le fichier à partir du lien et lire son contenu, puis appelle l'outil client `load_csv` avec le contenu CSV complet et le nom du fichier.
2. Pour répondre à chaque question, utilise UNIQUEMENT les outils client disponibles : `load_csv`, `describe_columns`, `filter_rows`, `aggregate_by_group`. N'utilise jamais d'interpréteur de code et n'exécute aucun code arbitraire : tous les calculs passent par ces outils.
3. Cite toujours des chiffres réels issus des appels d'outils (jamais de chiffres inventés ou estimés). Indique les unités et le nombre de lignes concernées.
4. Si une question est ambiguë, pose une question de clarification avant de calculer.
5. La session conserve tout l'historique : le fichier chargé via `load_csv` reste en mémoire pour toute la conversation, tu n'as pas besoin que l'utilisateur te redonne le lien ni ne te réexplique le contexte des échanges précédents. Ne recharge le fichier que si l'utilisateur te donne explicitement un nouveau lien.
6. Réponds en français, de façon claire et structurée, avec les résultats chiffrés mis en évidence.
"""


def _session_key(ctx: agents.ToolCallbackContext) -> str:
    session = getattr(ctx, "session", None)
    return str(getattr(session, "id", None) or "default")


def _dataset(ctx: agents.ToolCallbackContext) -> pd.DataFrame:
    key = _session_key(ctx)
    if key not in _DATASETS:
        raise ValueError("Aucun fichier chargé dans cette session. Donne un lien Google Drive et charge le CSV avec load_csv d'abord.")
    return _DATASETS[key]


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (bool, str, int)) or value is None:
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return str(value)


@agents.tool
def load_csv(ctx: agents.ToolCallbackContext, /, csv_content: str, file_name: str = "data.csv", delimiter: str = ",") -> dict[str, Any]:
    """Charge le contenu d'un fichier CSV (texte complet) dans la session et le mémorise pour les questions suivantes. Retourne le nombre de lignes, de colonnes et la liste des colonnes."""
    df = pd.read_csv(io.StringIO(csv_content), delimiter=delimiter or ",", thousands=None)
    key = _session_key(ctx)
    _DATASETS[key] = df
    _SOURCES[key] = file_name
    return {
        "file": file_name,
        "rows": int(df.shape[0]),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
    }


@agents.tool
def describe_columns(ctx: agents.ToolCallbackContext, /) -> dict[str, Any]:
    """Décrit chaque colonne du fichier chargé : type, valeurs non nulles, valeurs distinctes, statistiques (min, max, moyenne, écart-type pour les nombres ; valeurs les plus fréquentes pour le texte)."""
    df = _dataset(ctx)
    columns = []
    for col in df.columns:
        series = df[col]
        entry: dict[str, Any] = {
            "column": str(col),
            "dtype": str(series.dtype),
            "non_null": int(series.notna().sum()),
            "null": int(series.isna().sum()),
            "distinct": int(series.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(series):
            entry.update({
                "min": _jsonable(series.min()),
                "max": _jsonable(series.max()),
                "mean": _jsonable(series.mean()),
                "std": _jsonable(series.std()),
            })
        else:
            entry["top_values"] = _jsonable(series.value_counts().head(5).to_dict())
        columns.append(entry)
    return {"file": _SOURCES.get(_session_key(ctx)), "rows": int(df.shape[0]), "columns": columns}


@agents.tool
def filter_rows(ctx: agents.ToolCallbackContext, /, column: str, operator: str, value: Any, limit: int = 25) -> dict[str, Any]:
    """Filtre les lignes du fichier chargé. operator ∈ ==, !=, >, >=, <, <=, contains (texte), isin (liste de valeurs). Retourne le nombre de lignes correspondantes et un aperçu."""
    df = _dataset(ctx)
    if column not in df.columns:
        raise ValueError(f"Colonne inconnue : {column!r}. Colonnes disponibles : {list(df.columns)}")
    if operator not in _OPERATORS:
        raise ValueError(f"Opérateur inconnu : {operator!r}. Utilise l'un de : {_OPERATORS}")
    series = df[column]
    if operator == "contains":
        mask = series.astype(str).str.contains(str(value), case=False, na=False)
    elif operator == "isin":
        values = value if isinstance(value, (list, tuple)) else [value]
        mask = series.isin(values)
    else:
        if pd.api.types.is_numeric_dtype(series):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"La colonne {column!r} est numérique, la valeur doit être un nombre.")
        elif pd.api.types.is_bool_dtype(series):
            value = str(value).lower() in ("true", "1", "yes", "oui")
        ops = {
            "==": series == value,
            "!=": series != value,
            ">": series > value,
            ">=": series >= value,
            "<": series < value,
            "<=": series <= value,
        }
        mask = ops[operator]
    filtered = df[mask]
    limit = max(1, min(int(limit), 100))
    return {
        "column": column,
        "operator": operator,
        "value": _jsonable(value),
        "matched": int(filtered.shape[0]),
        "total": int(df.shape[0]),
        "sample": _jsonable(filtered.head(limit).to_dict(orient="records")),
    }


@agents.tool
def aggregate_by_group(ctx: agents.ToolCallbackContext, /, group_by: list[str], aggregations: list[dict[str, str]], limit: int = 100) -> dict[str, Any]:
    """Calcule des agrégats par groupe. group_by : liste de colonnes de regroupement. aggregations : liste de {"column": <colonne>, "function": sum|mean|median|min|max|count|nunique|std}. Retourne un tableau de résultats, limité à `limit` groupes."""
    df = _dataset(ctx)
    if not isinstance(group_by, list) or not group_by:
        raise ValueError("group_by doit être une liste non vide de colonnes.")
    unknown = [c for c in group_by if c not in df.columns]
    if unknown:
        raise ValueError(f"Colonnes inconnues : {unknown}. Disponibles : {list(df.columns)}")
    if not isinstance(aggregations, list) or not aggregations:
        raise ValueError("aggregations doit être une liste non vide de {'column': ..., 'function': ...}.")
    named: dict[str, Any] = {}
    for spec in aggregations:
        column = spec.get("column")
        func = str(spec.get("function", "")).lower()
        if column not in df.columns:
            raise ValueError(f"Colonne inconnue : {column!r}. Disponibles : {list(df.columns)}")
        if func not in _AGG_FUNCS:
            raise ValueError(f"Fonction inconnue : {func!r}. Utilise l'une de : {_AGG_FUNCS}")
        named[f"{column}__{func}"] = (column, func)
    result = df.groupby(group_by, dropna=False).agg(**{k: pd.NamedAgg(column=v[0], aggfunc=v[1]) for k, v in named.items()}).reset_index()
    limit = max(1, min(int(limit), 500))
    return {
        "groups": int(result.shape[0]),
        "rows": _jsonable(result.head(limit).to_dict(orient="records")),
    }


agent = agents.Agent(
    model="mistral-large-4",
    name="csv-data-analyst",
    description="Analyste de données conversationnel : lit un CSV depuis Google Drive et répond en langage naturel avec des chiffres réels (charger, décrire, filtrer, agréger par groupe).",
    instructions=INSTRUCTIONS,
    tools=[load_csv, describe_columns, filter_rows, aggregate_by_group],
    connectors=[agents.connector(DRIVE_CONNECTOR_NAME)],
)

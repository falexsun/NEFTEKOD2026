"""Read-only diagram annotations; never grants control authority or units."""
from pathlib import Path
import yaml


def load_topology(config_dir: str) -> dict:
    path = Path(config_dir) / "process_topology.yaml"
    if not path.exists():
        return {"tags": {}, "sources": {}}
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def annotation(topology: dict, tag: str) -> dict | None:
    entry = topology.get("tags", {}).get(tag)
    if entry is None:
        return None
    return {
        **entry,
        "provenance": topology["provenance"],
        "source_file": topology["sources"][entry["diagram"]],
        "industrial_limits_confirmed": False,
    }

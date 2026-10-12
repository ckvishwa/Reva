from pathlib import Path


def test_packaged_planner_contracts_match_architecture_contracts():
    root = Path(__file__).resolve().parents[2]
    for name in ("planner-decision.schema.json", "capability-registry.v2.json"):
        assert (root / "reva_core" / "planner" / "contracts" / name).read_bytes() == (
            root / "docs" / "08_CONTRACTS" / name
        ).read_bytes()

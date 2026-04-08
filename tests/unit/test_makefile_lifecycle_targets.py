from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_PATH = ROOT / "Makefile"


def _target_recipe(makefile_text: str, target: str) -> str:
    lines = makefile_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == f"{target}:":
            recipe: list[str] = []
            for next_line in lines[idx + 1 :]:
                if next_line.startswith("\t"):
                    recipe.append(next_line)
                    continue
                if not next_line.strip():
                    continue
                break
            return "\n".join(recipe)
    raise AssertionError(f"target not found: {target}")


def test_lifecycle_makefile_targets_route_via_lifecycle_service():
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    validate_recipe = _target_recipe(makefile_text, "validate-index")
    promote_recipe = _target_recipe(makefile_text, "promote-index")
    rollback_recipe = _target_recipe(makefile_text, "rollback-index")

    for recipe in (validate_recipe, promote_recipe, rollback_recipe):
        assert "pipelines.minimal_slice.lifecycle_service" in recipe
        assert "build_system_actor('makefile')" in recipe
        assert "pipelines.minimal_slice.qdrant_index" not in recipe

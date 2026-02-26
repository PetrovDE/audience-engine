import json
from pathlib import Path
from typing import Dict


def export_approved(policy_result: Dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for row in policy_result["results"]:
            if row["decision"] == "approve":
                f.write(json.dumps(row) + "\n")
    return output_path


import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = PROJECT_ROOT / "data" / "knowledge.json"


with KNOWLEDGE_PATH.open("r", encoding="utf-8") as f:
    knowledge = json.load(f)


parts = knowledge["parts"]
drawings = knowledge["drawings"]


def find_part(name):
    for part in parts:
        if part["name"].lower() == name.lower():
            return part
    return None


def find_drawing(drawing_id):
    for drawing in drawings:
        if drawing["drawing_id"] == drawing_id:
            return drawing
    return None


checks = []


# 1. Verified BOM-backed part
part = find_part("Recoater mount block")
checks.append(
    (
        "Recoater Mount Block exists in BOM",
        part is not None,
    )
)

# 2. Verified drawing link
drawing = find_drawing("D-012")
checks.append(
    (
        "D-012 has verified link",
        drawing is not None
        and drawing["match_status"] == "verified",
    )
)

# 3. Build Plate drawing
drawing = find_drawing("D-026")
checks.append(
    (
        "D-026 Build Plate exists",
        drawing is not None
        and drawing["title"] == "Build Plate",
    )
)

# 4. Drawing-only part
drawing = find_drawing("D-025")
checks.append(
    (
        "D-025 is intentionally unmatched",
        drawing is not None
        and drawing["match_status"] == "unmatched",
    )
)

# 5. Ambiguous identity
drawing = find_drawing("D-014")
checks.append(
    (
        "D-014 remains unverified",
        drawing is not None
        and drawing["match_status"] == "unverified",
    )
)


passed = 0

for name, result in checks:
    status = "PASS" if result else "FAIL"
    print(f"{status}: {name}")

    if result:
        passed += 1


print()
print(f"{passed}/{len(checks)} checks passed")
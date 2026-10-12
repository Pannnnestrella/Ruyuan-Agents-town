"""Restore shared portraits from legacy templates and the original art definitions."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

from fetch_ruyuan_art import AGENTS_DIR, ART_DIR, IMAGES, TARGETS, TEMPLATE_DIR, build_portrait, fetch


# Template names are aliases, not the names of the six scenario characters.
TEMPLATE_ALIASES = {"如鸢密探·袁基": ("袁基",)}


def valid_portrait(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, SyntaxError):
        return False


def main() -> None:
    shared = Path(AGENTS_DIR)
    for template in sorted(Path(TEMPLATE_DIR).iterdir()):
        source = template / "portrait.png"
        if not valid_portrait(source):
            continue
        for name in (template.name, *TEMPLATE_ALIASES.get(template.name, ())):
            destination = shared / name / "portrait.png"
            if not valid_portrait(destination):
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            print(f"Template: {template.name} -> {name}")

    for name, (_, mood, _) in TARGETS.items():
        destination = shared / name / "portrait.png"
        if valid_portrait(destination):
            continue
        remote = next(path for path, identity in IMAGES.items() if identity == (name, mood))
        source = Path(ART_DIR) / name / f"{mood}.png"
        source.parent.mkdir(parents=True, exist_ok=True)
        fetch(remote, str(source))
        if not valid_portrait(source):
            raise RuntimeError(f"Invalid source portrait: {name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        build_portrait(str(source), str(destination))
        print(f"Restored: {name}")

    for name in (*TARGETS, "袁基"):
        if not valid_portrait(shared / name / "portrait.png"):
            raise RuntimeError(f"Missing portrait: {name}")
    print("All six scenario portraits are available.")


if __name__ == "__main__":
    main()

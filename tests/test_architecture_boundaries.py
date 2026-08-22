from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ROOT / "agents_town"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class ArchitectureBoundaryTests(unittest.TestCase):
    def assert_tree_does_not_import(self, owner: str, forbidden: tuple[str, ...]) -> None:
        violations = []
        for path in (PACKAGE_ROOT / owner).rglob("*.py"):
            for imported in imported_modules(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path.relative_to(ROOT)} -> {imported}")
        self.assertEqual([], violations)

    def test_interactive_does_not_import_legacy(self):
        self.assert_tree_does_not_import("interactive", ("agents_town.legacy",))

    def test_legacy_does_not_import_interactive(self):
        self.assert_tree_does_not_import("legacy", ("agents_town.interactive",))

    def test_common_does_not_import_applications(self):
        self.assert_tree_does_not_import(
            "common", ("agents_town.interactive", "agents_town.legacy")
        )

    def test_resources_have_single_owner(self):
        interactive = PACKAGE_ROOT / "interactive" / "resources"
        legacy = PACKAGE_ROOT / "legacy" / "resources"
        common = PACKAGE_ROOT / "common" / "resources"
        self.assertTrue((interactive / "scenarios" / "stormbound_inn" / "scenario.json").is_file())
        self.assertTrue((interactive / "worlds" / "guangling_inn" / "world.json").is_file())
        self.assertTrue((legacy / "prompts" / "base_desc.txt").is_file())
        self.assertTrue((legacy / "frontend" / "templates" / "index.html").is_file())
        self.assertTrue((common / "lore" / "README.md").is_file())
        self.assertFalse((ROOT / "frontend").exists())


if __name__ == "__main__":
    unittest.main()

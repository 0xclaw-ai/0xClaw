import ast
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "0xclaw" / "main.py"


def _load_reset_helpers() -> dict:
    source = MAIN_PATH.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(MAIN_PATH))
    target_names = {
        "HACKATHON_RUNTIME_PATHS",
        "WORKSPACE_RUNTIME_PATHS",
        "_reset_hackathon_outputs",
        "_reset_workspace_runtime_outputs",
    }
    selected = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            ids = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(name in target_names for name in ids):
                selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in target_names:
            selected.append(node)

    namespace = {"Path": Path, "shutil": shutil}
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(MAIN_PATH), "exec")
    exec(compiled, namespace)
    return namespace


class SafeResetTests(unittest.TestCase):
    def test_reset_only_clears_whitelisted_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            helpers = _load_reset_helpers()
            tmp_root = Path(tmp)
            workspace = tmp_root / "workspace"
            hackathon = workspace / "hackathon"
            hackathon.mkdir(parents=True)

            # Whitelisted outputs
            (hackathon / "context.json").write_text("{}", encoding="utf-8")
            (hackathon / "project").mkdir(parents=True)
            (hackathon / "project" / "main.py").write_text("print('ok')", encoding="utf-8")

            # Non-whitelisted should survive
            (hackathon / "keep_me.txt").write_text("keep", encoding="utf-8")
            (workspace / "KEEP.md").write_text("keep", encoding="utf-8")

            helpers["WORKSPACE"] = workspace
            helpers["HACKATHON_DIR"] = hackathon
            removed = helpers["_reset_hackathon_outputs"]() + helpers["_reset_workspace_runtime_outputs"]()

            self.assertTrue(removed)
            self.assertFalse((hackathon / "context.json").exists())
            self.assertFalse((hackathon / "project").exists())
            self.assertTrue((hackathon / "keep_me.txt").exists())
            self.assertTrue((workspace / "KEEP.md").exists())


if __name__ == "__main__":
    unittest.main()

"""read_vsdx — thin wrapper: the implementation lives in `lab.core.visio.read_vsdx` (installed with
`pip install -e .`). Kept so the skill stays self-contained for its users: `import read_vsdx` re-exports
the module and `python scripts/read_vsdx.py …` runs its CLI.
"""
from lab.core.visio import read_vsdx as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

if __name__ == "__main__":
    _impl.main()

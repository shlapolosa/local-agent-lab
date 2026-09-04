"""relrepair — thin wrapper: the implementation lives in `lab.core.archimate.relrepair` (installed with
`pip install -e .`). Kept so the skill stays self-contained for its users: `import relrepair` re-exports
the module and `python scripts/relrepair.py …` runs its CLI.
"""
from lab.core.archimate import relrepair as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

if __name__ == "__main__":
    _impl.main()

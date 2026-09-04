"""archimate_engine — thin wrapper: the implementation lives in `lab.core.archimate.engine` (installed with
`pip install -e .`). Kept so the skill stays self-contained for its users: `import archimate_engine` re-exports
the module (the engine has no CLI; it is a library).
"""
from lab.core.archimate import engine as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

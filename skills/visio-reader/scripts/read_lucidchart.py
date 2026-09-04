"""read_lucidchart — thin wrapper: the implementation lives in `lab.core.visio.read_lucidchart` (installed with
`pip install -e .`). Re-export for skill users (requires `pip install -e .`): `import read_lucidchart` gives the module
(the engine has no CLI; it is a library).
"""
from lab.core.visio import read_lucidchart as _impl

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

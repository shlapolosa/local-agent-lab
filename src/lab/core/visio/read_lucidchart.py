"""Lucidchart / Azure typed-stencil -> ArchiMate 3.1 type EVIDENCE for the Visio parser.

A Lucidchart-exported `.vsdx` names each icon's master with a stable stencil-family string
(captured as a shape's `universal_name` / `master`), e.g. `com.lucidchart.VirtualMachineAzure2021.109`
or `com.lucidchart.ExpressRouteDirectAzure2021.592`. Unlike hand-authored Visio, these lines carry
NO native `<Connects>` / BeginX-EndX and empty instance geometry, so GEOMETRIC connector recovery is
out of scope (spike-established). What IS reliable is the typed stencil: the master string names the
Azure resource kind, which maps deterministically to a best-guess ArchiMate 3.1 element type.

This module is pure data + string matching (no I/O, no egress). `read_vsdx.py` imports it and stamps
an additive per-shape `type_hint` (the mapped ArchiMate type, or None). Native Visio shapes whose
masters match none of these tokens get `type_hint=None` — behaviour there is unchanged.

The map is intentionally a simple ORDERED list of (token, ArchiMate type). Matching is
case/space/punctuation-insensitive (so `com.lucidchart.VirtualMachineAzure2021.109`, a bare
`VirtualMachine`, and a native `"Virtual Machine"` stencil all match the same token). First match
wins, so list more specific tokens before their substrings. Extend by adding a row.
"""
from lab.core.canon import squash   # the lab's ONE punctuation-squash normaliser


# (token, ArchiMate 3.1 type). token is matched, normalized, as a substring of the normalized
# master string. Order matters: earlier rows win, so put specific tokens above broader ones.
STENCIL_TYPE_MAP = [
    # --- compute -> Node (a computational resource that hosts/executes) ---
    ("VMScaleSets",        "Node"),
    ("VirtualMachine",     "Node"),
    ("Kubernetes",         "Node"),
    ("AKS",                "Node"),
    ("Bastion",            "Node"),
    ("Firewall",           "Node"),
    ("ApplicationGateway", "Node"),   # L7 gateway/appliance
    ("LoadBalancer",       "Node"),
    # --- application workloads -> ApplicationComponent ---
    ("AppService",         "ApplicationComponent"),
    ("WebApp",             "ApplicationComponent"),
    ("FunctionApps",       "ApplicationComponent"),   # serverless app (extra, clear)
    # --- platform / system software -> SystemSoftware ---
    ("KeyVault",           "SystemSoftware"),
    ("CacheRedis",         "SystemSoftware"),          # extra: managed cache runtime
    ("ApplicationInsights","SystemSoftware"),          # extra: observability/Monitor family
    ("LogAnalytics",       "SystemSoftware"),          # extra: observability/Monitor family
    ("Observability",      "SystemSoftware"),
    ("Monitor",            "SystemSoftware"),
    ("EventHubs",          "SystemSoftware"),           # extra: managed messaging runtime
    # --- data -> DataObject ---
    ("SqlDatabase",        "DataObject"),
    ("Database",           "DataObject"),
    # --- storage -> Artifact (a passive stored data element) ---
    ("StorageAccounts",    "Artifact"),
    ("Blob",               "Artifact"),
    ("Storage",            "Artifact"),
    # --- networking -> CommunicationNetwork ---
    ("ExpressRoute",       "CommunicationNetwork"),
    ("VirtualNetwork",     "CommunicationNetwork"),
    ("Subnet",             "CommunicationNetwork"),
    ("NetworkInterface",   "CommunicationNetwork"),     # extra: NIC, a network access point
    ("PrivateLink",        "CommunicationNetwork"),      # extra: private network path
]


# precompute normalized tokens once
_NORM_MAP = [(squash(tok), arch) for tok, arch in STENCIL_TYPE_MAP]


def is_lucidchart_master(master) -> bool:
    """True iff the master string is a Lucidchart-exported stencil (`com.lucidchart.*`)."""
    return isinstance(master, str) and "com.lucidchart." in master.lower()


def is_typed_stencil(master) -> bool:
    """True iff `master` is a TYPED cloud stencil we trust for type evidence.

    That means a Lucidchart export (`com.lucidchart.*`) or an Azure-branded master
    (e.g. Lucidchart's `...Azure2021`, or a native Microsoft Azure Visio stencil). This gate is
    deliberate: a broad token like `Database` or `Storage` would otherwise also fire on a GENERIC
    native Visio shape (e.g. Malaffi's `Database.70`), which is NOT a typed cloud stencil and must
    stay `type_hint=None`. Type evidence comes only from a recognizably typed stencil.
    """
    if not isinstance(master, str):
        return False
    low = master.lower()
    return "com.lucidchart." in low or "azure" in low


def _token_type(master) -> str | None:
    """Raw token lookup: the ArchiMate type for the first matching stencil token, else None."""
    if not isinstance(master, str) or not master:
        return None
    norm = squash(master)
    for norm_tok, arch in _NORM_MAP:
        if norm_tok in norm:
            return arch
    return None


def type_hint_for_master(master, in_lucidchart_file: bool = False) -> str | None:
    """Best-guess ArchiMate 3.1 type for a stencil master, else None.

    Type evidence is trusted only from a TYPED cloud stencil. A master qualifies when it is
    Azure-branded / Lucidchart itself (`is_typed_stencil`), OR when the whole file is a Lucidchart
    export (`in_lucidchart_file=True`) — inside such a file even bare child masters like
    `ExpressRoute` are genuine typed stencils. A generic native Visio shape (e.g. Malaffi's
    `Database.70`) matches neither and stays None, so native parsing is unchanged.
    """
    if not (in_lucidchart_file or is_typed_stencil(master)):
        return None
    return _token_type(master)

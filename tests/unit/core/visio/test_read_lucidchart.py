"""src/lab/core/visio/read_lucidchart — the LUCIDCHART VENDOR PROFILE: the stencil master ->
ArchiMate type_hint table (incl. the native `Database.70` negative), the shared `squash` normaliser,
and which masters name a line. The vendor-neutral endpoint geometry it feeds lives next door
(tests/unit/core/visio/test_geometry.py). Pure: no I/O, no vsdx.
Run: PYTHONPATH=src:tests .venv/bin/python -m pytest -q tests/unit/core/visio/test_read_lucidchart.py"""
from lab.core.canon import squash
from lab.core.visio import read_lucidchart as L

# (master, in_lucidchart_file) -> type_hint
TABLE = [
    ("com.lucidchart.VirtualMachineAzure2021.109", False, "Node"),
    ("com.lucidchart.ExpressRouteDirectAzure2021.592", False, "CommunicationNetwork"),
    ("com.lucidchart.VMScaleSetsAzure2021.3", False, "Node"),            # specific token wins over VirtualMachine
    ("com.lucidchart.SqlDatabaseAzure2021.12", False, "DataObject"),
    ("com.lucidchart.StorageAccountsAzure2021.7", False, "Artifact"),
    ("com.lucidchart.KeyVaultAzure2021.1", False, "SystemSoftware"),
    ("com.lucidchart.UnknownThingAzure2021.1", False, None),             # typed stencil, no token -> None
    ("Microsoft Azure SQL Database", False, "DataObject"),               # native Azure-branded Visio master
    ("ExpressRoute", True, "CommunicationNetwork"),                      # bare child master inside a Lucidchart file
    ("ExpressRoute", False, None),                                       # …but not trusted outside one
    ("Database.70", False, None),                                        # generic native Visio shape stays untyped
    ("Database.70", True, "DataObject"),                                 # inside a Lucidchart export it IS a typed stencil
    ("Process", True, None),
    ("", True, None),
    (None, True, None),
]


def test_type_hint_table():
    for master, in_lucid, expected in TABLE:
        got = L.type_hint_for_master(master, in_lucidchart_file=in_lucid)
        assert got == expected, (master, in_lucid, got, expected)


def test_gates():
    assert L.is_lucidchart_master("com.lucidchart.X") and not L.is_lucidchart_master("X") and not L.is_lucidchart_master(None)
    assert L.is_typed_stencil("Microsoft Azure Blob") and L.is_typed_stencil("COM.LUCIDCHART.y")
    assert not L.is_typed_stencil("Database.70") and not L.is_typed_stencil(7)


def test_normaliser_is_the_shared_one():
    assert L.squash is squash                                             # one normaliser, no local copy


def test_line_master_family_is_recognised_narrowly():
    assert L.is_line_master("com.lucidchart.Line.105") and L.is_line_master("COM.LUCIDCHART.LINE.7")
    assert not L.is_line_master("com.lucidchart.LineChart.9")      # a different family, not a connector
    assert not L.is_line_master("com.lucidchart.FreehandBlock.44")
    assert not L.is_line_master("Dynamic connector") and not L.is_line_master(None)


if __name__ == "__main__":
    for _n, _f in list(globals().items()):
        if _n.startswith("test_") and callable(_f):
            _f(); print("ok", _n)
    print("ALL TESTS PASSED")

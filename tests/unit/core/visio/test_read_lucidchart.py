"""src/lab/core/visio/read_lucidchart — stencil master -> ArchiMate type_hint table,
including the native `Database.70` negative, and the shared `squash` normaliser.
Run: .venv/bin/python tests/unit/core/visio/test_read_lucidchart.py   (also pytest-compatible)"""
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


if __name__ == "__main__":
    test_type_hint_table()
    test_gates()
    test_normaliser_is_the_shared_one()
    print("ALL TESTS PASSED")

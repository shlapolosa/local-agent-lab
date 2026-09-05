"""`./lab.sh clients` must render EVERY placeholder in EVERY committed client template.

WHY THIS BITES. A client template carries `${NAME}` placeholders that `render_clients()` substitutes
from `.env`. Two ways that silently fails, and both have happened:

  * the glob was `config/clients/*/settings.template.json`, so a client whose file is named anything
    else (the Power Automate flow definition) rendered NOTHING and nobody noticed — the README had to
    tell people to run `sed` by hand;
  * a placeholder added to a template with no matching `-e` in `render_clients` renders as the
    literal string `${NAME}`, which for an `audience` or a `tenant` means the client fails to
    authenticate with a value that looks almost right.

Neither shows up anywhere else: nothing imports these files and no other test reads them. So this
test reads `lab.sh` ITSELF and holds it to the templates on disk.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB_SH = os.path.join(ROOT, "lab.sh")
CLIENTS = os.path.join(ROOT, "config", "clients")


def _templates():
    for d, _dirs, files in os.walk(CLIENTS):
        for f in files:
            if f.endswith(".template.json"):
                yield os.path.join(d, f)


def _render_block() -> str:
    src = open(LAB_SH).read()
    start = src.index("render_clients()")
    return src[start:src.index("\n}", start)]


def test_there_is_at_least_one_template_to_render():
    assert list(_templates()), "no client templates found — the walk or the layout changed"


def test_the_glob_matches_every_committed_template():
    """Not `settings.template.json` — any `*.template.json`. A client is whatever needs the
    per-deployment values, not one blessed filename."""
    block = _render_block()
    glob = re.search(r"for tpl in (\S+); do", block)
    assert glob, "render_clients no longer loops over a glob"
    pattern = glob.group(1)
    assert pattern.endswith("*.template.json"), pattern
    import fnmatch
    for tpl in _templates():
        rel = os.path.relpath(tpl, ROOT)
        assert fnmatch.fnmatch(rel, pattern), f"{rel} is not matched by {pattern}"


def test_every_placeholder_in_every_template_is_substituted():
    """The invariant that actually matters: an unsubstituted `${NAME}` reaches the client verbatim."""
    substituted = set(re.findall(r'-e "s#\\\$\{([A-Z_]+)\}#', _render_block()))
    assert substituted, "render_clients no longer substitutes anything"
    for tpl in _templates():
        used = set(re.findall(r"\$\{([A-Z_]+)\}", open(tpl).read()))
        missing = used - substituted
        assert not missing, (f"{os.path.relpath(tpl, ROOT)} uses {sorted(missing)}, which "
                             "render_clients does not substitute — it would render literally")


def test_no_substituted_value_is_a_secret():
    """Rendered files are git-ignored, but they still sit on disk and get pasted around. Only
    addresses and PUBLIC identifiers may be rendered; a credential stays a <<PLACEHOLDER>> the person
    types into the client itself."""
    substituted = set(re.findall(r'-e "s#\\\$\{([A-Z_]+)\}#', _render_block()))
    banned = {n for n in substituted if re.search(r"SECRET|PASSWORD|_KEY$|TOKEN", n)}
    assert not banned, f"render_clients would write credentials into a rendered file: {sorted(banned)}"


@pytest.mark.parametrize("tpl", sorted(_templates()), ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_a_template_keeps_its_credential_as_a_designer_placeholder(tpl):
    """<<...>> is the 'you fill this in' marker. A template that had none would mean either no
    credential (fine) or a credential we are about to render (not fine — caught above)."""
    body = open(tpl).read()
    for m in re.finditer(r"<<([A-Z_]+)", body):
        assert not re.search(r"\$\{", m.group(0)), "a placeholder cannot be both forms"

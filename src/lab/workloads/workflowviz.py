"""Export a built Agent Framework workflow graph as Mermaid — for the review app's Runs board.

Wraps `agent_framework.WorkflowViz(workflow).to_mermaid()` (agent-framework 1.16.0:
`to_mermaid(include_internal_executors: bool = False) -> str`, alongside `to_digraph` and
`export(format=svg|png|pdf|dot)` which need graphviz and are not used here). Import-guarded:
a missing or changed API logs one line and returns None — a host must never fail because its
diagram could not be drawn.
"""
import logging

log = logging.getLogger("workflowviz")


def mermaid(workflow, include_internal_executors: bool = False) -> str | None:
    """Mermaid source (`flowchart TD …`) for a BUILT workflow (`WorkflowBuilder(...).build()`),
    or None if `workflow` is None / not a Workflow / the viz API is unavailable."""
    if workflow is None:
        return None
    try:
        from agent_framework import WorkflowViz
    except Exception as e:                                   # noqa: BLE001 — API moved/missing
        _note(f"agent_framework.WorkflowViz unavailable ({type(e).__name__}: {e}); no diagram")
        return None
    try:
        viz = WorkflowViz(workflow)
        out = viz.to_mermaid(include_internal_executors=include_internal_executors)
    except TypeError:
        try:                                                 # older signature without the kwarg
            out = WorkflowViz(workflow).to_mermaid()
        except Exception as e:                               # noqa: BLE001
            _note(f"WorkflowViz.to_mermaid failed ({type(e).__name__}: {e}); no diagram")
            return None
    except Exception as e:                                   # noqa: BLE001 — not a Workflow, etc.
        _note(f"WorkflowViz could not render {type(workflow).__name__} ({type(e).__name__}: {e}); no diagram")
        return None
    return out if isinstance(out, str) and out.strip() else None


def _note(msg):
    log.warning(msg)          # logging's last-resort handler already puts WARNINGs on stderr


if __name__ == "__main__":
    print(mermaid(None))

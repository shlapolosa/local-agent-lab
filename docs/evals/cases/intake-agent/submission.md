# Use case: an agent that runs the CAFÉ framework over submitted AI use cases

1.1 Problem

AI use cases arrive from business teams as prose. Assessing one properly means deriving a business capability match, a semantic check, a workflow decomposition, a risk classification, a control set and an architecture — work that takes an architect days and is not reproducible between architects. The consequence is that most submissions are assessed on judgement and precedent, comparability across designs is poor, and the expensive derivations are skipped under delivery pressure. Where they are skipped, the resulting system carries controls nobody derived.

1.2 Use case

A business team submits a use case. The solution screens it for feasibility, and where it passes, executes the CAFÉ process end to end to produce a composed architecture, a control requirement set, a costed model and a business case carrying a recommendation. An architect reviews; the business case determines whether the use case proceeds.

The outcome is a decision, not a design. The outcome is not the architecture. The architecture is an input to the decision — it is what makes the cost estimate real, because cost is the sum of the components the design switched on. The outcome is a business case with a recommendation of proceed, proceed with conditions, or defer, weighing quantified benefit against Year-1 investment. A design that is sound and does not repay its cost is a correct output of this solution and a decision not to build.

Why the risk profile matters. The exposure and influence classes are the design driver. This solution can do almost nothing harmful itself, and it determines what a system built next quarter will be required to do. Every control in section 7 follows from that asymmetry rather than from what the solution touches.
---- MODULE EvidenceLattice ----
EXTENDS Naturals
CONSTANTS None, Declarative, Static, Executed, NegativeControl, IndependentAttested
Rank == [None |-> 0, Declarative |-> 1, Static |-> 2, Executed |-> 3,
         NegativeControl |-> 4, IndependentAttested |-> 5]
Dominates(a,b) == Rank[a] >= Rank[b]
Bounded == \A e \in DOMAIN Rank : Rank[e] >= 0 /\ Rank[e] <= 5
====

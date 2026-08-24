--------------------------- MODULE BoundedPlasticity ---------------------------
EXTENDS Naturals, Reals, Sequences

CONSTANTS MinBudget, MaxBudget, MinTimeout, MaxTimeout, MaxSafety
ASSUME /\ MinBudget \in Nat
       /\ MaxBudget \in Nat
       /\ MinBudget <= MaxBudget
       /\ MinTimeout \in Nat
       /\ MaxTimeout \in Nat
       /\ MinTimeout <= MaxTimeout
       /\ MaxSafety \in Real
       /\ MaxSafety >= 0.0
       /\ MaxSafety <= 1.0

VARIABLES budget, timeout, score, coverage, support, cooldown, healthy, action
vars == <<budget, timeout, score, coverage, support, cooldown, healthy, action>>

Actions == {"noop", "tighten_safety", "reduce_work", "expand_recall"}

TypeOK == /\ budget \in MinBudget..MaxBudget
          /\ timeout \in MinTimeout..MaxTimeout
          /\ score \in Real /\ score >= 0.0 /\ score <= MaxSafety
          /\ coverage \in Real /\ coverage >= 0.0 /\ coverage <= MaxSafety
          /\ support \in Real /\ support >= 0.0 /\ support <= MaxSafety
          /\ cooldown \in Nat
          /\ healthy \in Nat
          /\ action \in Actions

Init == /\ budget = MinBudget
        /\ timeout = MinTimeout
        /\ score = 0.0
        /\ coverage = 0.0
        /\ support = 0.0
        /\ cooldown = 0
        /\ healthy = 0
        /\ action = "noop"

MonotoneSafety == /\ score' >= score
                   /\ coverage' >= coverage
                   /\ support' >= support

BoundedSafety == /\ score' \in Real /\ score' >= 0.0 /\ score' <= MaxSafety
                 /\ coverage' \in Real /\ coverage' >= 0.0 /\ coverage' <= MaxSafety
                 /\ support' \in Real /\ support' >= 0.0 /\ support' <= MaxSafety

BoundedResources == /\ budget' \in MinBudget..MaxBudget
                    /\ timeout' \in MinTimeout..MaxTimeout

Noop == /\ action' = "noop"
        /\ UNCHANGED <<budget, timeout, score, coverage, support>>

Tighten == /\ action' = "tighten_safety"
           /\ score' >= score
           /\ coverage' >= coverage
           /\ support' >= support
           /\ UNCHANGED <<budget, timeout>>

ReduceWork == /\ action' = "reduce_work"
              /\ budget' <= budget
              /\ timeout' <= timeout
              /\ UNCHANGED <<score, coverage, support>>

ExpandRecall == /\ action' = "expand_recall"
                /\ budget' >= budget
                /\ timeout' >= timeout
                /\ UNCHANGED <<score, coverage, support>>

Next == /\ BoundedResources
        /\ BoundedSafety
        /\ MonotoneSafety
        /\ (Noop \/ Tighten \/ ReduceWork \/ ExpandRecall)
        /\ cooldown' \in Nat
        /\ healthy' \in Nat

Safety == TypeOK
Spec == Init /\ [][Next]_vars
=============================================================================

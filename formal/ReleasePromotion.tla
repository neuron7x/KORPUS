---- MODULE ReleasePromotion ----
EXTENDS Naturals, FiniteSets
CONSTANTS Draft, Integrated, Verified, Candidate, Authorized, Withdrawn
CONSTANT MandatoryGates
VARIABLES stage, gatePass, exactSource, exactRelease, independentVerifier

Stages == {Draft, Integrated, Verified, Candidate, Authorized, Withdrawn}
AllGates == \A g \in MandatoryGates : gatePass[g] /\ exactSource[g] /\ exactRelease[g]

Init == stage = Draft
Next ==
    \/ /\ stage = Draft /\ stage' = Integrated
       /\ UNCHANGED <<gatePass, exactSource, exactRelease, independentVerifier>>
    \/ /\ stage = Integrated /\ AllGates /\ stage' = Verified
       /\ UNCHANGED <<gatePass, exactSource, exactRelease, independentVerifier>>
    \/ /\ stage = Verified /\ AllGates /\ stage' = Candidate
       /\ UNCHANGED <<gatePass, exactSource, exactRelease, independentVerifier>>
    \/ /\ stage = Candidate /\ AllGates /\ independentVerifier /\ stage' = Authorized
       /\ UNCHANGED <<gatePass, exactSource, exactRelease, independentVerifier>>
    \/ /\ stage # Withdrawn /\ stage' = Withdrawn
       /\ UNCHANGED <<gatePass, exactSource, exactRelease, independentVerifier>>

TypeOK == stage \in Stages
NoAuthorizationWithoutGates == stage = Authorized => AllGates /\ independentVerifier
NoReturnFromWithdrawn == stage = Withdrawn => ~ENABLED (stage' # Withdrawn)
====

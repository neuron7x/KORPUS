# KORPUS Frozen Evaluation Protocol

Version: 1.0

1. Freeze the evaluated source commit, dependency locks, dataset, fixtures, ranking configuration and this protocol before execution.
2. Compute SHA-256 for every bound artifact. A changed byte invalidates the calibration profile.
3. Separate retrieval metrics from selective-answering metrics.
4. Evaluate inaccessible-corpus noninterference, citation span integrity, temporal supersession, contradiction handling, prompt injection, deterministic replay and abstention.
5. Do not tune thresholds against the holdout after observing results. A new threshold requires a new profile identifier and a new evaluation run.
6. Record all failures. No manual suppression is permitted in a release report.
7. Production calibration requires an independently reviewed real-domain dataset; bundled synthetic fixtures are assurance tests only.

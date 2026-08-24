# Machine-readable handoff

- `current_state.json` — verified base state and SSOT order.
- `calibration_weights.json` — exact current code defaults and calibration status.
- `next_iterations.json/.csv` — ten planned engineering iterations.
- `next_integrations.json/.csv` — seven planned external integrations.
- `acceptance_gates.json` — merge and production blocking predicates.

Run `python3 scripts/verify_handoff_contract.py` after any change to these files or the corresponding code defaults.

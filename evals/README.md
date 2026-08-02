# Evaluation protocol

Maintain separate frozen and development sets. Questions are written or approved by
domain reviewers and include expected source versions, acceptable alternates, answer
requirements, access tier, risk class and expected abstention.

Measure retrieval Recall@k, precision, MRR and nDCG; then answer correctness,
claim-level faithfulness, citation precision/coverage, contradiction handling,
abstention, access leakage, latency and cost. LLM judges are calibrated against a
human-labeled subset and never serve as the only release gate.

Every production correction becomes a regression case after privacy review.


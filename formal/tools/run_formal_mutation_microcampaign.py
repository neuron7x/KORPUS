#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'apps/api/src/korpus/application'
TESTS=ROOT/'apps/api/tests'
MUTANTS=[
 ('AC01_cross_identity_dominance','assurance_calculus.py','if not _same_identity(left, right):\n        return False','if not _same_identity(left, right):\n        return True','test_assurance_calculus.py::test_stronger_same_identity_evidence_dominates_weaker'),
 ('AC02_conflict_must_fail','assurance_calculus.py','        status = "FAIL"','        status = "PASS"','test_assurance_calculus.py::test_conflicting_evidence_join_fails_closed'),
 ('AC03_no_execution_ceiling','assurance_calculus.py','if not evidence.executed:\n        return policy.ceiling_without_execution','if not evidence.executed:\n        return 100.0','test_assurance_calculus.py::test_unexecuted_evidence_caps_dimension_even_when_claimed_score_is_100'),
 ('AC04_stale_dimension_zero','assurance_calculus.py','if evidence.source_digest != source_digest or evidence.release != release:\n        return 0.0','if False and (evidence.source_digest != source_digest or evidence.release != release):\n        return 0.0','test_assurance_calculus.py::test_stale_dimension_evidence_contributes_zero'),
 ('AC05_no_score_compensation','assurance_calculus.py','production_authorized=not blockers,','production_authorized=True,','test_assurance_calculus.py::test_high_weighted_score_cannot_compensate_for_missing_mandatory_gate'),
 ('AC06_gate_release_binding','assurance_calculus.py','f"{prefix}.release_bound": evidence.release == release,','f"{prefix}.release_bound": True,','test_assurance_calculus.py::test_release_binding_is_required_even_for_independent_attestation'),
 ('RS01_sequential_only','release_state_machine.py','if expected != target:\n        return PromotionVerdict(False, target, ("release.non_sequential_transition",))','if False and expected != target:\n        return PromotionVerdict(False, target, ("release.non_sequential_transition",))','test_release_state_machine.py::test_promotion_must_be_sequential'),
 ('RS02_verifier_required','release_state_machine.py','if target >= ReleaseStage.VERIFIED and not verifier_subject:','if False and target >= ReleaseStage.VERIFIED and not verifier_subject:','test_release_state_machine.py::test_verified_requires_verifier_and_exact_source_bound_gate'),
 ('RS03_independent_verifier','release_state_machine.py','and verifier_subject == record.author_subject','and False and verifier_subject == record.author_subject','test_release_state_machine.py::test_production_authorization_requires_independent_verifier'),
 ('RS04_withdraw_terminal','release_state_machine.py','if record.stage == ReleaseStage.WITHDRAWN:\n        raise ValueError("release is already withdrawn")','if False and record.stage == ReleaseStage.WITHDRAWN:\n        raise ValueError("release is already withdrawn")','test_release_state_machine.py::test_withdrawal_is_the_only_general_safety_escape'),
]

def sha(path: Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
results=[]
for mid,filename,old,new,selector in MUTANTS:
    with tempfile.TemporaryDirectory(prefix='korpus-formal-mutant-') as tmp:
        base=Path(tmp)/'src'; shutil.copytree(ROOT/'apps/api/src',base)
        path=base/'korpus/application'/filename
        text=path.read_text()
        if old not in text: raise SystemExit(f'{mid}: mutation anchor missing')
        path.write_text(text.replace(old,new,1))
        env=os.environ.copy(); env['PYTHONPATH']=str(base)
        run=subprocess.run(['python3','-m','pytest','-q','-c','/dev/null',str(TESTS/selector.split('::')[0]),'-k',selector.split('::')[1]],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        results.append({'id':mid,'file':f'apps/api/src/korpus/application/{filename}','selector':selector,'killed':run.returncode!=0,'pytest_exit_code':run.returncode})
report={'schema':'korpus.formal-mutation-microcampaign.v1','source_files':{f'apps/api/src/korpus/application/{n}':sha(SRC/n) for n in {m[1] for m in MUTANTS}},'mutants':len(results),'killed':sum(r['killed'] for r in results),'survived':[r['id'] for r in results if not r['killed']],'results':results}
out=ROOT/'reports/CANONICAL_FORMAL_MUTATION_REPORT.json'; out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
raise SystemExit(0 if not report['survived'] else 1)

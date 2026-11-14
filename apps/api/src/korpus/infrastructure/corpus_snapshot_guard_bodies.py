"""Expected function bodies for the immutable snapshot guard contract."""

POSTGRES_FUNCTION_BODIES = {
    "korpus_bump_corpus_state_epoch": """
        BEGIN
          UPDATE public.corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1;
          RETURN NULL;
        END;
    """,
    "korpus_refuse_approved_evidence_mutation": """
        DECLARE
          locked_digest text;
        BEGIN
          IF TG_OP = 'INSERT' THEN
            SELECT evidence_digest INTO locked_digest
            FROM public.document_versions
            WHERE id = NEW.version_id
            FOR SHARE;
            IF locked_digest IS NOT NULL THEN
              RAISE EXCEPTION 'sealed evidence is immutable';
            END IF;
          ELSIF TG_OP = 'DELETE' THEN
            SELECT evidence_digest INTO locked_digest
            FROM public.document_versions
            WHERE id = OLD.version_id
            FOR SHARE;
            IF locked_digest IS NOT NULL THEN
              RAISE EXCEPTION 'sealed evidence is immutable';
            END IF;
          ELSE
            FOR locked_digest IN
              SELECT evidence_digest
              FROM public.document_versions
              WHERE id IN (OLD.version_id, NEW.version_id)
              ORDER BY id
              FOR SHARE
            LOOP
              IF locked_digest IS NOT NULL THEN
                RAISE EXCEPTION 'sealed evidence is immutable';
              END IF;
            END LOOP;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
    """,
    "korpus_refuse_approved_digest_mutation": """
        BEGIN
          IF OLD.evidence_digest IS NOT NULL
             AND NEW.evidence_digest IS DISTINCT FROM OLD.evidence_digest THEN
            RAISE EXCEPTION 'sealed evidence digest is immutable';
          END IF;
          RETURN NEW;
        END;
    """,
}

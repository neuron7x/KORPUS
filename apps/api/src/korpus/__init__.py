from korpus.release import RELEASE_VERSION as __version__

# The alias is a public runtime contract: korpus.main, korpus.application.answer_audit_envelope
# and the capability-gateway invocation context all read it. Under --strict an alias is not an
# export unless it is declared, so `from korpus import __version__` reported attr-defined while
# the attribute plainly existed. Declaring it is the statement, not a suppression.
__all__ = ["__version__"]

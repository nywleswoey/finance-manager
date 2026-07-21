"""Shared ledger conventions used by build_ledger.py and build_viewer.py."""

# Holdings.md label -> canonical SGX/exchange code used in transaction data.
# CWBU->SET: SGX counter renamed (Cromwell->Stoneweg).
ALIAS = {"QAF": "Q01", "CWBU": "SET", "C": "C52"}


def canon(t):
    return ALIAS.get(t, t)


# transfer-leg action predicates (both underscore and space spellings occur)
def is_transfer_out(a): return "transfer_out" in a or "transfer out" in a
def is_transfer_in(a):  return "transfer in" in a or a == "transfer_in"

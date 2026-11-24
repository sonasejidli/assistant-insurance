# Behavior recorded before implementing the benchmark

The existing source-authority layer runs after retrieval and evidence assembly when LEGAL_SOURCE_AUTHORITY is enabled. It compares a passage with the indexed document and a catalog pinned to document IDs, source versions where present, and exact indexed anchors. Source type and authority come from the catalog. A filename does not confer authority.

Temporal status uses a requested legal reference date and the dates or rule period attached to the anchored provision. It leaves undocumented effective periods unknown. The asserted contract and event dates are compared separately and are not verified case facts. The current layer has no claim-filing-date field. Its comparisons do not establish a legal entitlement.

Potential conflict detection compares cataloged issue, insurance type, person-group, rule family and rule windows. It does not choose a prevailing source. It has no separate missing-information list or general semantic conflict detector. Normative eligibility is a generation authorization boundary, not a legal conclusion. Context stays in the evidence package and can be quoted as context. In the opt-in path, only eligible normative markers can enter the structured legal-claim binding and judge.

The hardened verifier uses its own independent witness and scope logic. The source-authority layer has no authority to replace that gate or to promote asserted case dates to verified dates. The benchmark will test this boundary without changing either implementation. The 43-fixture verifier comparison was saved before benchmark implementation as .venv/authority-benchmark-verifier-before.json.

# Verified release readiness baseline

The working tree was already dirty. The pre-change status is recorded in `.venv/readiness-before-status.txt`. It includes existing changes to application code, Docker and Compose, corpus files, frontend, datasets, and tests. The pre-change suite passed 208/208.

`/ask` resolves context, plans parts, retrieves and assembles evidence, annotates authority and dates, generates and validates citations, then calls the outer release wrapper before FastAPI serialization. With release enabled, the wrapper binds the packed references to indexed sources, projects an exact-question witness and captured evidence into the hardened verifier, then reconstructs the response from witnessed fragments. Authority and release default off in code. The release flag activates authority while gated. The configured model, context window and token cap retain their existing defaults. Credentials are read through `OPENROUTER_API_KEY` or `EMBED_API_KEY`; Qdrant configuration uses `QDRANT_URL`, `QDRANT_PATH`, `QDRANT_API_KEY`, and `QDRANT_COLLECTION`.

| Historical artifact under .venv | SHA-256 |
|---|---|
| multipart-108-results.json | 2f4193c1212986bbbd7e9b32c1fdf360a98235d95e2ec8b37cd0bd25aceed13b |
| release-verifier-after.json | b323b62c159869b6b5464e658c5e70a467c2d48491b75c48f9936a61c84506f1 |
| release-authority-39.json | 0cfa8f37810046e1556f316f99126dddc8b782b4780452f5941b127f9c413b38 |
| verified-release-frozen-e2e.json | b2bab5952e9c063ff46f9507f8fa50061e3effb779441c375dda20288b543f70 |
| verified-release-audit-results.json | f55cba41ed4653b0ec1d8648a3c67566e214cf73305601f7b8ee209f1ee54231 |

The historical release comparison recorded 9 unsupported FULL responses ungated and 0 gated across 15 fixtures. The 43-case verifier and the release replay had byte-identical comparisons. The 39-case report retains T11 and C06 legacy expectation differences. The 15-case end-to-end artifact includes six source-derived and nine synthetic cases with expert review pending.

The retained 108-query retrieval baseline reported Recall@5 0.948, Recall@10 0.958, MRR@20 0.941 and nDCG@5 0.903. Its prior before/after analysis recorded 0/108 changes in final top-20 rankings. [Historical retrieval comparison](multipart_108_regression.md)

Inspection targets for adversarial validation are the narrow verifier exception list, the release and serialization calls outside that exception boundary, generated clarification based on capture ordering, and the exact-question witness guard.

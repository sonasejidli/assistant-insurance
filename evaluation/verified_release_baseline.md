# Observed release path

The ask route resolves and plans the question, retrieves and assembles evidence, optionally annotates authority and dates, and invokes the generator. Structured generation binds citations and uses its faithfulness judge. App/main.py then formats the generated text and records FULL or PARTIAL before returning the response. The hardened verifier runs only in offline evaluation, so its decision never reaches serialization.

In E2E-B06 the packed XML has empty article and clause attributes, while the frozen index uses null. In E2E-S04 the existing task-pattern splitter leaves two explicitly punctuated questions in one part. The release integration addresses these boundaries only when opted in.

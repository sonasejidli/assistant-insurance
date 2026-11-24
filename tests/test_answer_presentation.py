import unittest

from App import system, verified_release


QUESTION = "Könüllü tibbi sığortanı istədiyim vaxt ləğv edə bilərəmmi?"
PASSAGE_ID = "231c16e4-9889-521c-ae7e-54cd4aca3904"
SOURCE_TEXT = (
    "6.1.1. müvafiq icra hakimiyyəti orqanının müəyyən etdiyi orqanın (qurumun) müəyyən etdiyi "
    "qaydada könüllü tibbi sığorta müqaviləsi bağlamaq və ya onu ləğv etmək; [30]"
)
CLAIM = (
    "Sığortalı könüllü tibbi sığorta müqaviləsini səlahiyyətli orqanın müəyyən etdiyi qaydada ləğv edə bilər."
)


class AnswerPresentationTests(unittest.TestCase):
    def test_cited_azerbaijani_partial_starts_with_the_supported_point(self):
        hit = {"doc": "sığorts 4.pdf", "text": SOURCE_TEXT, "metadata": {"article": "6", "clause": "6.1.1"}}
        draft = system.PARTIAL_PREFIX + f"- {CLAIM} [S1]"
        validated = system.validate_generated_answer(draft, [hit], {0})
        self.assertEqual(validated, draft)
        reply = system.format_answer(validated, [hit], "az")
        self.assertEqual(reply["answer"], f"- {CLAIM} [S1]")
        self.assertEqual(reply["sources"][0]["clause"], "6.1.1")
        self.assertIsNone(system.validate_generated_answer(draft.replace("[S1]", "[S2]"), [hit], {0}))

    def test_partial_release_renders_an_already_verified_fragment_before_its_specific_limitation(self):
        # Isolate rendering from verification. This is a supplied, test-only verifier verdict.
        source = {"passage_id": PASSAGE_ID, "document_id": "test", "document_name": "sığorts 4.pdf",
                  "article": "6", "clause": "6.1.1", "page": None, "text": SOURCE_TEXT,
                  "law_name": "Tibbi sığorta haqqında"}
        claim = {"supported_fragment": CLAIM, "claim_text": CLAIM, "part": "Q1", "claim_id": "test-claim",
                 "status": "supported", "reason_code": "supported", "citation_valid": True, "witness": "test-witness",
                 "evidence": [{"valid": True, "marker": "S1", "source": source}]}
        verdict = {"verified_mode": "PARTIAL", "claims": [claim], "reason": "insufficient_scope",
                   "parts": {"Q1": {"complete": False, "independently_supported_fragments": [CLAIM]}}}
        authority = {"sources": [{"reference": source, "eligible_normative": True,
                                  "temporal_status": "reference_date_unspecified"}]}
        limitation = "Bu bənd ləğvin istənilən vaxt mümkün olduğunu təsdiqləmir."
        reply = verified_release.release(
            {}, "PARTIAL", verdict, authority, [], "az",
            trusted_notices=[{"code": "timing_not_established", "az": limitation, "en": ""}],
        )
        self.assertTrue(reply["answer"].startswith(f"{CLAIM} [S1]\n\n{limitation}"))
        self.assertEqual(reply["answer_mode"], "PARTIAL")
        self.assertEqual(reply["sources"][0]["passage_id"], PASSAGE_ID)
        self.assertNotIn("dəqiqləşdirə bilərsinizmi", reply["answer"])

    def test_actual_profile_and_insufficient_evidence_remain_fail_closed(self):
        profiles, _ = verified_release.configuration()
        self.assertNotIn(QUESTION, profiles)
        for mode in (None, "NOT_FOUND"):
            with self.subTest(mode=mode):
                result = {"verified_mode": mode, "claims": [], "reason": "generation_unavailable", "parts": {}}
                reply = verified_release.release({}, "NOT_FOUND", result, {}, [], "az")
                self.assertEqual(reply["answer_mode"], mode)
                self.assertTrue(reply["answer"].startswith(system.limited_answer("az")))
                self.assertEqual(reply["sources"], [])
                self.assertNotIn(CLAIM, reply["answer"])

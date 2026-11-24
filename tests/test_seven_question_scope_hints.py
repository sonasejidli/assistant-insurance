import unittest

from App.intent import classify_intent_rule


class SevenQuestionScopeHintTests(unittest.TestCase):
    def test_domain_signals_route_payment_questions(self):
        questions = (
            "Doğuma görə verilən birdəfəlik yardım anaya çatır?",
            "Kompensasiyadan imtina hansı səbəblərlə mümkündür?",
            "Hadisə müqavilə bitəndən bir gün sonra baş verib. Bildiriş vaxtı nəticəni dəyişirmi?",
            "Əlillik faizi artdıqda kompensasiya necə dəyişir?",
            "Xəstəlik pulu almaq üçün neçə ay işləmək lazımdır?",
            "İşdə yaralandığım halda kompensasiya almaq hüququm var?",
            "Peşə xəstəliyi dedikdə nə nəzərdə tutulur?",
            "Pese xestelikleri ne demekdir?",
            "Ağır və yüngül zədə üçün hansı faiz tətbiq olunur?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertEqual(classify_intent_rule(question), "insurance_question")

    def test_nearby_subjects_without_a_benefit_or_insurance_signal(self):
        questions = (
            "Yeni doğulan uşağı necə qeydiyyata alım?",
            "Əlillik zamanı funksiyaların pozulma faizi necə ölçülür?",
            "Yüngül və ağır yaralanma arasındakı fərq nədir?",
            "Müqavilə bitəndə cihazı necə qaytarım?",
            "Restoranda hansı yeməyə görə pul verilir?",
            "Mövsümi xəstəliklər necə yayılır?",
            "Sabah hava necə olacaq?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertIn(classify_intent_rule(question), {None, "out_of_scope"})

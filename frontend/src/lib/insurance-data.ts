export interface LegalSource {
  id: number;
  title: string;
  number: string;
  article: string;
  clause: string;
  page: number;
  version: string;
  date: string;
  relevance: number;
  category: string;
  insurance: string;
  language: string;
  text: string;
}
export const sources: LegalSource[] = [
  {
    id: 1,
    title: "İcbari sığortalar haqqında",
    number: "165-IVQ",
    article: "Maddə 15",
    clause: "15.1 – 15.3",
    page: 12,
    version: "2024",
    date: "2024-06-21",
    relevance: 96,
    category: "Qanun",
    insurance: "İcbari",
    language: "AZ",
    text: "Sığorta hadisəsi baş verdikdə, sığortalı və ya sığorta olunan hadisə barədə sığortaçıya mümkün olan ən qısa müddətdə məlumat verməlidir. Sığortaçı təqdim edilmiş sənədlər əsasında sığorta ödənişini həyata keçirir. [Sintetik nümayiş mətni.]",
  },
  {
    id: 2,
    title: "İcbari sığortalar haqqında",
    number: "165-IVQ",
    article: "Maddə 16",
    clause: "16.1",
    page: 13,
    version: "2024",
    date: "2024-06-21",
    relevance: 92,
    category: "Qanun",
    insurance: "İcbari",
    language: "AZ",
    text: "Sığorta ödənişinin verilməsi üçün sığorta hadisəsini təsdiqləyən sənədlər və zərərin məbləğini müəyyən edən məlumatlar təqdim edilir. [Sintetik nümayiş mətni.]",
  },
  {
    id: 3,
    title: "Sığorta fəaliyyəti haqqında",
    number: "519-IIIQ",
    article: "Maddə 58",
    clause: "58.1 – 58.2",
    page: 34,
    version: "2023",
    date: "2023-12-15",
    relevance: 87,
    category: "Qanun",
    insurance: "Ümumi",
    language: "AZ",
    text: "Sığortaçı sığortalının müraciətini araşdırır və sığorta müqaviləsinin şərtlərinə uyğun qərar qəbul edir. Qərar sığortalıya yazılı şəkildə təqdim olunur. [Sintetik nümayiş mətni.]",
  },
  {
    id: 4,
    title: "Könüllü avtomobil sığortası qaydaları",
    number: "Q-24",
    article: "Maddə 8",
    clause: "8.2",
    page: 7,
    version: "2024",
    date: "2024-02-10",
    relevance: 79,
    category: "Qaydalar",
    insurance: "Könüllü",
    language: "AZ",
    text: "Avtomobilə dəyən zərərin qiymətləndirilməsi müstəqil ekspert tərəfindən həyata keçirilə bilər. [Sintetik nümayiş mətni.]",
  },
];
export const initialQuestion =
  "İcbari sığorta üzrə sığorta hadisəsi baş verdikdə, sığortalının və sığortaçının əsas öhdəlikləri nələrdir?";
export const initialAnswer = `İcbari sığorta hadisəsi zamanı tərəflərin əsas öhdəlikləri **“İcbari sığortalar haqqında”** Qanunun müvafiq maddələri ilə tənzimlənir. Aşağıda əsas məqamları izah edirəm.

### 1. Sığortalının öhdəlikləri
- **Hadisə barədə məlumat vermək.** Sığortalı hadisə baş verdikdən sonra mümkün olan ən qısa müddətdə sığortaçıya məlumat verməlidir.
- **Zəruri sənədləri təqdim etmək.** Hadisəni təsdiq edən sənədlər və zərərin qiymətləndirilməsi üçün tələb olunan məlumatlar təqdim edilməlidir.
- **Zərərin artmasının qarşısını almaq.** Sığortalı əlavə zərərin qarşısını almaq üçün ağlabatan tədbirlər görməlidir.

### 2. Sığortaçının öhdəlikləri
- **Müraciəti araşdırmaq.** Sığortaçı hadisənin sığorta təminatına daxil olub-olmadığını müəyyən etməlidir.
- **Sığorta ödənişini həyata keçirmək.** Tələb olunan sənədlər təqdim edildikdən sonra müqavilənin şərtlərinə uyğun ödəniş edilməlidir.
- **Əsaslandırılmış qərar vermək.** Ödənişdən imtina edilərsə, səbəblər yazılı şəkildə izah olunmalıdır.

### Qısa xülasə
| Tərəf | Əsas öhdəlik | Hüquqi istinad |
| :--- | :--- | :--- |
| Sığortalı | Məlumat və sənədlərin təqdim edilməsi | Maddə 15, 15.1–15.3 |
| Sığortaçı | Araşdırma və sığorta ödənişi | Maddə 16, 16.1 |`;
export function filterSources(
  query: string,
  insurance = "all",
  category = "all",
  language = "all",
  version = "all",
) {
  const terms = query.toLocaleLowerCase("az").trim().split(/\s+/).filter(Boolean);
  return sources.filter(
    (s) =>
      (insurance === "all" || s.insurance === insurance) &&
      (category === "all" || s.category === category) &&
      (language === "all" || s.language === language) &&
      (version === "all" || s.version === version) &&
      terms.every((t) =>
        `${s.title} ${s.number} ${s.article} ${s.text}`.toLocaleLowerCase("az").includes(t),
      ),
  );
}
export function simulatedAnswer(query: string) {
  return /sığorta|ödəniş|hadisə|öhdəlik|165|maddə/i.test(query)
    ? initialAnswer
    : "Bu suala cavab vermək üçün mövcud nümayiş mənbələrində kifayət qədər hüquqi sübut tapılmadı. Müvafiq qanunu, maddəni və ya sığorta növünü dəqiqləşdirin. Hüquqi nəticə çıxarmaq üçün təsdiqlənmiş mənbə tələb olunur.";
}

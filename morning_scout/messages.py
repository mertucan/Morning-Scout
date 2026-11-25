"""User-facing text (notifications, e-mail, LLM instructions), per summary language.

Code and logs are in English; everything the *user* reads is localised here.
Add a new language by adding a key to :data:`MESSAGES` and :data:`PROMPTS`.
"""

from __future__ import annotations

MESSAGES: dict[str, dict[str, str]] = {
    "tr": {
        "title": "Morning Scout · {date}",
        "nothing_new": "Bugün yeni bir gelişme yok. ☕",
        "fallback_note": "_Yapay zekâ özeti oluşturulamadı; ham liste aşağıda._",
        "section_news": "Haberler",
        "section_search": "Web araması",
        "section_pages": "Değişen sayfalar",
        "read_more_in_mail": "… devamı e-postada.",
        "source": "Kaynak",
        "sources_heading": "Kaynaklar",
        "config_error": "⚠️ config.yaml okunamadı{line}. Gist'teki dosyayı kontrol et. Bugünkü özet gönderilmedi.",
        "config_error_line": " (satır {line})",
        "state_error": "⚠️ state.json okunamadı. Gist'teki dosyayı kontrol et veya içeriğini {} yap.",
        "footer": "Morning Scout tarafından otomatik oluşturuldu.",
        "token_expiry": "⚠️ **GitHub token'ının süresi {days} gün içinde doluyor ({date}).** GitHub → Settings → Developer settings → Fine-grained tokens → *Regenerate token*; ardından `GIST_TOKEN` secret'ını ve cron-job.org'daki token'ı güncelle.",
    },
    "en": {
        "title": "Morning Scout · {date}",
        "nothing_new": "Nothing new today. ☕",
        "fallback_note": "_The AI summary could not be generated; raw list below._",
        "section_news": "News",
        "section_search": "Web search",
        "section_pages": "Changed pages",
        "read_more_in_mail": "… more in the e-mail.",
        "source": "Source",
        "sources_heading": "Sources",
        "config_error": "⚠️ Could not read config.yaml{line}. Please check the file in your Gist. Today's digest was not sent.",
        "config_error_line": " (line {line})",
        "state_error": "⚠️ Could not read state.json. Check the file in your Gist or reset it to {}.",
        "footer": "Generated automatically by Morning Scout.",
        "token_expiry": "⚠️ **Your GitHub token expires in {days} days ({date}).** GitHub → Settings → Developer settings → Fine-grained tokens → *Regenerate token*, then update the `GIST_TOKEN` secret and the token in cron-job.org.",
    },
}

_PROMPT_TR = """Sen kişisel bir sabah araştırma asistanısın. Aşağıda, kullanıcının takip ettiği konular için bugün bulunan YENİ kaynaklar var; her kaynağın başında [S1], [S2] gibi bir numarası var. Bunlardan kısa, kolay okunur bir günlük özet hazırla.

Kurallar:
- YALNIZCA verilen kaynaklardaki bilgilere dayan. Kendi bilgini ekleme, tahmin yürütme, uydurma.
- Konulara göre grupla; "topic" olarak verilen konu adını aynen kullan.
- Her konuyu kısa maddelere böl. Her madde tek bir bilgi içersin ve 1-2 cümleyi geçmesin.
- Her maddenin "sources" alanına o bilgiyi içeren kaynakların numaralarını yaz (ör. ["S3", "S7"]). Yalnızca listede bulunan numaraları kullan; metnin içine numara, link veya URL yazma.
- Aynı olayı anlatan birden fazla kaynak varsa tek maddede birleştir.
- Konu bir soru içeriyorsa (ör. "başvuru açıldı mı?", "tarih açıklandı mı?") kaynaklarda net bir kanıt yoksa bunu ayrı bir maddede açıkça yaz (ör. "Kaynaklarda başvurunun açıldığına dair net bir bilgi yok."). Kanıt varsa ilgili kaynağı göster.
- "Sayfa değişikliği" kaynaklarında "+" eklenen, "-" silinen satırları gösterir. Bunlar takip edilen ilan sayfalarıdır: eklenen ilanları (kurum/şirket, pozisyon, son başvuru tarihi) madde madde yaz; sadece silinen ya da tarihi geçen ilanları ve menü/reklam gibi değişiklikleri atla. Bu kaynakları da bulundukları konunun altında yaz.
- Bir konunun veya sayfanın altında "Odak" yazıyorsa o kısım için YALNIZCA odağa uyan bilgileri yaz, uymayanları tamamen atla. Odağa uyan bir şey yoksa o konuyu ya da sayfayı hiç yazma. Odak SADECE altında yazdığı konu için geçerlidir; diğer konuları etkilemez, onları her zamanki gibi eksiksiz özetle.
- Tarihleri en üstte verilen bugünün tarihine göre değerlendir: süresi geçmemiş bir başvuruyu "yapılmıştır" diye geçmiş zamanla yazma. Son başvuru tarihi bugün, yarın ya da önümüzdeki 7 gün içindeyse maddenin başına "⏰ Son gün yarın:" veya "⏰ Son 5 gün:" gibi bir uyarı ekle. Süresi geçmiş ilanları ayrıca belirt ya da atla.
- Kaynağı olan her konuyu ayrı ayrı ele al; hiçbir konuyu atlayıp özeti tek konuya indirme.
- Konuyla ilgisiz, reklam veya tekrar niteliğindeki sonuçları atla. Bir konu için anlamlı bir şey kalmadıysa o konuyu hiç yazma.
- Türkçe yaz.
"""

_PROMPT_EN = """You are a personal morning research assistant. Below are NEW sources found today for the topics the user follows; each source is prefixed with an id such as [S1], [S2]. Prepare a short, easy-to-read daily digest from them.

Rules:
- Rely ONLY on the information in the sources. Do not add outside knowledge, guess or invent anything.
- Group by topic; use the given topic name verbatim as "topic".
- Split each topic into short bullets. Each bullet holds a single point in 1-2 sentences.
- Put the ids of the sources supporting a bullet in its "sources" field (e.g. ["S3", "S7"]). Only use ids from the list; never put ids, links or URLs in the text.
- Merge multiple sources about the same event into a single bullet.
- If a topic is a question (e.g. "are applications open?") and the sources contain no clear evidence, say so explicitly in its own bullet. If there is evidence, cite it.
- In "Page change" sources, "+" marks added and "-" removed lines. These are watched listing pages: list the added listings (organisation, position, deadline) as bullets; skip lines that were only removed or have expired, and menu/ad changes. Put them under the topic they are listed in.
- If a topic or page has a "Focus" line, include ONLY information matching that focus and leave everything else out. If nothing matches, omit that topic or page entirely. A focus applies ONLY to the topic it is listed under; summarise every other topic fully as usual.
- Judge dates against today's date given at the top: never describe an application period that is still open in the past tense. If a deadline is today, tomorrow or within the next 7 days, start the bullet with a warning such as "⏰ Last day tomorrow:" or "⏰ 5 days left:". Mark expired listings as such or skip them.
- Handle every topic that has sources separately; never collapse the digest into a single topic.
- Skip irrelevant, promotional or duplicate results. Omit topics with nothing meaningful left.
- {language_hint}
"""


def messages_for(language: str) -> dict[str, str]:
    """User-facing strings for ``language``; falls back to English."""
    return MESSAGES.get(language, MESSAGES["en"])


def system_prompt(language: str) -> str:
    """Summarisation instructions for the LLM, in the requested language."""
    source = messages_for(language)["source"]
    if language == "tr":
        return _PROMPT_TR.format(source=source)
    hint = "Write in English." if language == "en" else f"Write in the language '{language}'."
    return _PROMPT_EN.format(source=source, language_hint=hint)

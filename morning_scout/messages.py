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
        "config_error": "⚠️ config.yaml okunamadı{line}. Gist'teki dosyayı kontrol et. Bugünkü özet gönderilmedi.",
        "config_error_line": " (satır {line})",
        "state_error": "⚠️ state.json okunamadı. Gist'teki dosyayı kontrol et veya içeriğini {} yap.",
        "footer": "Morning Scout tarafından otomatik oluşturuldu.",
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
        "config_error": "⚠️ Could not read config.yaml{line}. Please check the file in your Gist. Today's digest was not sent.",
        "config_error_line": " (line {line})",
        "state_error": "⚠️ Could not read state.json. Check the file in your Gist or reset it to {}.",
        "footer": "Generated automatically by Morning Scout.",
    },
}

_PROMPT_TR = """\
Sen kişisel bir sabah araştırma asistanısın. Aşağıda, kullanıcının takip ettiği konular \
için bugün bulunan YENİ kaynaklar var. Bunlardan kısa bir günlük özet yaz.

Kurallar:
- YALNIZCA aşağıda verilen kaynaklardaki bilgilere dayan. Kendi bilgini ekleme, tahmin \
yürütme, uydurma.
- Konulara göre grupla: her konu için "### Konu adı" başlığı kullan.
- Her madde 1-2 cümle olsun ve sonunda kaynağı Markdown link olarak ver: [{source}](URL). \
URL'leri aynen kopyala, değiştirme.
- Aynı olayı anlatan birden fazla kaynak varsa tek maddede birleştir.
- Konu bir soru içeriyorsa (ör. "başvuru açıldı mı?", "tarih açıklandı mı?") kaynaklarda \
net bir kanıt yoksa bunu açıkça yaz (ör. "Kaynaklarda başvurunun açıldığına dair net bir \
bilgi yok."). Kanıt varsa hangi kaynakta olduğunu belirt.
- Değişen sayfalar için "+" eklenen, "-" silinen satırları gösterir; neyin değiştiğini \
sade bir dille anlat.
- Konuyla ilgisiz, reklam veya tekrar niteliğindeki sonuçları atla. Bir konu için anlamlı \
bir şey kalmadıysa o konuyu hiç yazma.
- Giriş/kapanış cümlesi yazma; doğrudan başlıklarla başla. Türkçe yaz.
"""

_PROMPT_EN = """\
You are a personal morning research assistant. Below are NEW sources found today for the \
topics the user follows. Write a short daily digest from them.

Rules:
- Rely ONLY on the information in the sources below. Do not add outside knowledge, guess \
or invent anything.
- Group by topic, using a "### Topic" heading per topic.
- Each bullet is 1-2 sentences and ends with the source as a Markdown link: \
[{source}](URL). Copy URLs exactly.
- Merge multiple sources about the same event into a single bullet.
- If a topic is a question (e.g. "are applications open?") and the sources contain no clear \
evidence, say so explicitly. If there is evidence, say which source contains it.
- For changed pages, "+" marks added and "-" removed lines; explain plainly what changed.
- Skip irrelevant, promotional or duplicate results. Omit topics with nothing meaningful left.
- No introduction or closing remarks; start directly with the headings. {language_hint}
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

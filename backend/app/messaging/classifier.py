"""Inbound reply classification and Zawgyi handling.

Keyword lists per language for the demo. An LLM classifier can replace
`KeywordClassifier` behind the same interface; it may classify, never write.
"""
from dataclasses import dataclass
from typing import Protocol

ZAWGYI_THRESHOLD = 0.9

LABELS = ("vulnerability", "complaint", "dispute", "stop", "already_paid", "cant_pay", "will_pay", "other")
PAUSING = {"vulnerability", "complaint", "dispute", "stop"}

# Checked in this order: safety first, then intent.
KEYWORDS: dict[str, dict[str, list[str]]] = {
    "en": {
        "vulnerability:death": ["died", "passed away", "funeral", "death in the family"],
        "vulnerability:illness": ["sick", "hospital", "illness", "surgery", "operation", "in hospital"],
        "vulnerability:disaster": ["flood", "fire", "storm", "earthquake", "fighting", "conflict", "displaced"],
        "vulnerability:job_loss": ["lost my job", "no work", "laid off", "factory closed", "business closed"],
        "vulnerability:migration": ["moved to", "thailand", "malaysia", "abroad", "migrat"],
        "complaint": ["complaint", "complain", "rude", "harass", "threaten"],
        "dispute": ["not my loan", "wrong amount", "don't owe", "do not owe", "already finished", "dispute"],
        "stop": ["stop", "unsubscribe", "don't message", "do not message"],
        "already_paid": ["already paid", "i paid", "paid yesterday", "have paid", "paid already"],
        "cant_pay": ["can't pay", "cannot pay", "cant pay", "can not pay", "unable to pay", "no money"],
        "will_pay": ["will pay", "i'll pay", "pay tomorrow", "pay next week", "pay on", "paying"],
    },
    "my": {
        "vulnerability:death": ["ဆုံးသွား", "သေဆုံး", "ဈာပန", "အသုဘ"],
        "vulnerability:illness": ["နေမကောင်း", "ဆေးရုံ", "ဖျား", "ခွဲစိတ်"],
        "vulnerability:disaster": ["ရေကြီး", "မီးလောင်", "မုန်တိုင်း", "ငလျင်", "တိုက်ပွဲ", "စစ်ဘေး"],
        "vulnerability:job_loss": ["အလုပ်ပြုတ်", "အလုပ်မရှိ", "စက်ရုံပိတ်", "ဆိုင်ပိတ်"],
        "vulnerability:migration": ["ထိုင်း", "မလေးရှား", "နိုင်ငံခြား", "ပြောင်းရွှေ့"],
        "complaint": ["တိုင်ကြား", "မကျေနပ်"],
        "dispute": ["ကျွန်မချေးငွေမဟုတ်", "ကျွန်တော့်ချေးငွေမဟုတ်", "မှားနေ", "ပမာဏမှား"],
        "stop": ["စာမပို့ပါနဲ့", "ရပ်ပါ", "မပို့ပါနဲ့"],
        "already_paid": ["ပေးပြီးပြီ", "ပေးခဲ့ပြီ", "သွင်းပြီးပြီ", "ဆပ်ပြီးပြီ"],
        "cant_pay": ["မပေးနိုင်", "ငွေမရှိ", "မတတ်နိုင်", "ပေးလို့မရ", "မဆပ်နိုင်"],
        "will_pay": ["ပေးမယ်", "ပေးပါမယ်", "ပေးပါ့မယ်", "ပေးချေပါမယ်", "ဆပ်ပါမယ်"],
    },
    "km": {
        "vulnerability:death": ["ស្លាប់", "បុណ្យសព"],
        "vulnerability:illness": ["ឈឺ", "មន្ទីរពេទ្យ", "វះកាត់"],
        "vulnerability:disaster": ["ទឹកជំនន់", "ភ្លើងឆេះ", "ព្យុះ"],
        "vulnerability:job_loss": ["បាត់បង់ការងារ", "អត់ការងារ", "រោងចក្របិទ"],
        "vulnerability:migration": ["ថៃ", "ម៉ាឡេស៊ី", "ចំណាកស្រុក", "ប្តូរទីលំនៅ"],
        "complaint": ["បណ្តឹង", "តវ៉ា"],
        "dispute": ["មិនមែនប្រាក់កម្ចីខ្ញុំ", "ចំនួនខុស"],
        "stop": ["ឈប់ផ្ញើ"],
        "already_paid": ["បង់រួចហើយ", "បានបង់ហើយ"],
        "cant_pay": ["មិនអាចបង់", "គ្មានលុយ", "អត់លុយ"],
        "will_pay": ["នឹងបង់", "ស្អែកបង់"],
    },
}


@dataclass
class Classification:
    label: str
    subtype: str | None
    matched: str | None
    language: str
    method: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class ReplyClassifier(Protocol):
    def classify(self, text: str, language: str) -> Classification: ...


class KeywordClassifier:
    method = "keywords-v1"

    def classify(self, text: str, language: str) -> Classification:
        lowered = text.lower()
        langs = [language, "en"] if language != "en" else ["en"]
        for lang in langs:
            for key, words in KEYWORDS.get(lang, {}).items():
                for w in words:
                    if w.lower() in lowered:
                        label, _, subtype = key.partition(":")
                        return Classification(label, subtype or None, w, lang, self.method)
        return Classification("other", None, None, language, self.method)


CLASSIFIER: ReplyClassifier = KeywordClassifier()


def normalise_burmese(text: str) -> tuple[str, dict]:
    """Detect Zawgyi (Google myanmar-tools) and convert to Unicode (ICU Zawgyi-my)."""
    info = {"zawgyi_probability": None, "converted": False}
    if not any("က" <= ch <= "႟" for ch in text):
        return text, info
    from myanmartools import ZawgyiDetector

    p = ZawgyiDetector().get_zawgyi_probability(text)
    info["zawgyi_probability"] = round(p, 3)
    if p < ZAWGYI_THRESHOLD:
        return text, info
    try:
        import icu

        converted = icu.Transliterator.createInstance("Zawgyi-my").transliterate(text)
        info["converted"] = True
        info["original"] = text
        return converted, info
    except ImportError:  # ICU missing: keep the text, flag it for a human
        info["conversion_unavailable"] = True
        return text, info

psynet_supported_locales = [
    "af",  # Afrikaans
    "am",  # Amharic
    "ar",  # Arabic
    "as",  # Assamese
    "az",  # Azerbaijani
    "be",  # Belarusian
    "bg",  # Bulgarian
    "bn",  # Bengali
    # "cnr",  # Montenegrin; no vocabulary test available
    "cs",  # Czech
    "da",  # Danish
    "de",  # German
    "doi",  # Dogri
    "el",  # Greek
    "en",  # English
    "es",  # Spanish
    "et",  # Estonian
    "fi",  # Finnish
    "fr",  # French
    "gu",  # Gujarati
    "he",  # Hebrew
    "hi",  # Hindi
    "hr",  # Croatian
    "hu",  # Hungarian
    "id",  # Indonesian
    "it",  # Italian
    "is",  # Icelandic
    "ja",  # Japanese
    "kk",  # Kazakh
    "km",  # Khmer
    "kn",  # Kannada
    "ko",  # Korean
    "kok",  # Konkani
    # "ks",  # Kashmiri; no vocabulary test available
    "ku",  # Kurdish
    "lb",  # Luxembourgish; no vocabulary test available
    "lo",  # Laotian
    "lt",  # Lithuanian
    "lv",  # Latvian
    "mai",  # Maithili
    "mni",  # Manipuri
    "mk",  # Macedonian
    "mr",  # Marathi
    "ms",  # Malay
    "mt",  # Maltese
    "my",  # Burmese
    "ne",  # Nepali
    "nl",  # Dutch
    "no",  # Norwegian in general but defaults to (Bokmål)
    "od",  # Odia
    "pa",  # Punjabi
    "pl",  # Polish
    "pt",  # Portuguese
    "ro",  # Romanian
    "ru",  # Russian
    "sa",  # Sanskrit
    "sat",  # Santali
    "si",  # Sinhala
    "sk",  # Slovak
    "sd",  # Sindhi
    "sl",  # Slovenian
    "sq",  # Albanian
    "sr",  # Serbian
    "st",  # Sotho/Sesotho
    "sv",  # Swedish
    "sw",  # Swahili
    "ta",  # Tamil
    "te",  # Telugu
    "th",  # Thai
    "tl",  # Filipino/Tagalog
    "tr",  # Turkish
    "uk",  # Ukrainian
    "ur",  # Urdu
    "uz",  # Uzbek
    "vi",  # Vietnamese
    "zu",  # Zulu
    "zh",  # Chinese
]


def get_known_languages(locale=None):
    """
    List compiled using the pycountry package v20.7.3 with

    ::

        sorted([(lang.alpha_2, lang.name) for lang in pycountry.languages
            if hasattr(lang, 'alpha_2')], key=lambda country: country[1])
    """
    from psynet.utils import get_translator, null_translator_with_context

    if locale is None:
        _p = null_translator_with_context
    else:
        _p = get_translator(context=True)

    return [
        ("ab", _p("language_name", "Abkhazian")),
        ("aa", _p("language_name", "Afar")),
        ("af", _p("language_name", "Afrikaans")),
        ("ak", _p("language_name", "Akan")),
        ("sq", _p("language_name", "Albanian")),
        ("am", _p("language_name", "Amharic")),
        ("ar", _p("language_name", "Arabic")),
        ("an", _p("language_name", "Aragonese")),
        ("hy", _p("language_name", "Armenian")),
        ("as", _p("language_name", "Assamese")),
        ("av", _p("language_name", "Avaric")),
        ("ae", _p("language_name", "Avestan")),
        ("ay", _p("language_name", "Aymara")),
        ("az", _p("language_name", "Azerbaijani")),
        ("bm", _p("language_name", "Bambara")),
        ("ba", _p("language_name", "Bashkir")),
        ("eu", _p("language_name", "Basque")),
        ("be", _p("language_name", "Belarusian")),
        ("bn", _p("language_name", "Bengali")),
        ("bi", _p("language_name", "Bislama")),
        ("bs", _p("language_name", "Bosnian")),
        ("br", _p("language_name", "Breton")),
        ("bg", _p("language_name", "Bulgarian")),
        ("my", _p("language_name", "Burmese")),
        ("ca", _p("language_name", "Catalan")),
        ("km", _p("language_name", "Central Khmer")),
        ("ch", _p("language_name", "Chamorro")),
        ("ce", _p("language_name", "Chechen")),
        ("zh", _p("language_name", "Chinese")),
        ("zh-cn", _p("language_name", "Chinese")),
        ("cu", _p("language_name", "Church Slavic")),
        ("cv", _p("language_name", "Chuvash")),
        ("kw", _p("language_name", "Cornish")),
        ("co", _p("language_name", "Corsican")),
        ("cr", _p("language_name", "Cree")),
        ("hr", _p("language_name", "Croatian")),
        ("ceb", _p("language_name", "Cebuano")),
        ("cs", _p("language_name", "Czech")),
        ("doi", _p("language_name", "Dogri")),
        ("da", _p("language_name", "Danish")),
        ("dv", _p("language_name", "Dhivehi")),
        ("nl", _p("language_name", "Dutch")),
        ("dz", _p("language_name", "Dzongkha")),
        ("en", _p("language_name", "English")),
        ("eo", _p("language_name", "Esperanto")),
        ("et", _p("language_name", "Estonian")),
        ("ee", _p("language_name", "Ewe")),
        ("fo", _p("language_name", "Faroese")),
        ("fj", _p("language_name", "Fijian")),
        ("fi", _p("language_name", "Finnish")),
        ("fr", _p("language_name", "French")),
        ("ff", _p("language_name", "Fulah")),
        ("gl", _p("language_name", "Galician")),
        ("lg", _p("language_name", "Ganda")),
        ("ka", _p("language_name", "Georgian")),
        ("de", _p("language_name", "German")),
        ("got", _p("language_name", "Gothic")),
        ("gn", _p("language_name", "Guarani")),
        ("gu", _p("language_name", "Gujarati")),
        ("ht", _p("language_name", "Haitian")),
        ("ha", _p("language_name", "Hausa")),
        ("haw", _p("language_name", "Hawaiian")),
        ("he", _p("language_name", "Hebrew")),
        ("hz", _p("language_name", "Herero")),
        ("hi", _p("language_name", "Hindi")),
        ("ho", _p("language_name", "Hiri Motu")),
        ("hmn", _p("language_name", "Hmong")),
        ("hu", _p("language_name", "Hungarian")),
        ("is", _p("language_name", "Icelandic")),
        ("io", _p("language_name", "Ido")),
        ("ig", _p("language_name", "Igbo")),
        ("id", _p("language_name", "Indonesian")),
        ("ia", _p("language_name", "Interlingua")),
        ("ie", _p("language_name", "Interlingue")),
        ("iu", _p("language_name", "Inuktitut")),
        ("ik", _p("language_name", "Inupiaq")),
        ("ga", _p("language_name", "Irish")),
        ("it", _p("language_name", "Italian")),
        ("ja", _p("language_name", "Japanese")),
        ("jv", _p("language_name", "Javanese")),
        ("jw", _p("language_name", "Javanese")),
        ("kl", _p("language_name", "Kalaallisut")),
        ("kn", _p("language_name", "Kannada")),
        ("kr", _p("language_name", "Kanuri")),
        ("ks", _p("language_name", "Kashmiri")),
        ("kk", _p("language_name", "Kazakh")),
        ("ki", _p("language_name", "Kikuyu")),
        ("rw", _p("language_name", "Kinyarwanda")),
        ("ky", _p("language_name", "Kirghiz")),
        ("kv", _p("language_name", "Komi")),
        ("kg", _p("language_name", "Kongo")),
        ("kok", _p("language_name", "Konkani")),
        ("ko", _p("language_name", "Korean")),
        ("kj", _p("language_name", "Kuanyama")),
        ("ku", _p("language_name", "Kurdish")),
        ("lo", _p("language_name", "Lao")),
        ("la", _p("language_name", "Latin")),
        ("lv", _p("language_name", "Latvian")),
        ("li", _p("language_name", "Limburgan")),
        ("ln", _p("language_name", "Lingala")),
        ("lt", _p("language_name", "Lithuanian")),
        ("lu", _p("language_name", "Luba-Katanga")),
        ("lb", _p("language_name", "Luxembourgish")),
        ("mk", _p("language_name", "Macedonian")),
        ("mai", _p("language_name", "Maithili")),
        ("mg", _p("language_name", "Malagasy")),
        ("ms", _p("language_name", "Malay")),
        ("ml", _p("language_name", "Malayalam")),
        ("mt", _p("language_name", "Maltese")),
        ("mni", _p("language_name", "Manipuri")),
        ("gv", _p("language_name", "Manx")),
        ("mi", _p("language_name", "Maori")),
        ("mr", _p("language_name", "Marathi")),
        ("mh", _p("language_name", "Marshallese")),
        ("el", _p("language_name", "Greek")),
        ("mn", _p("language_name", "Mongolian")),
        ("na", _p("language_name", "Nauru")),
        ("nv", _p("language_name", "Navajo")),
        ("ng", _p("language_name", "Ndonga")),
        ("ne", _p("language_name", "Nepali")),
        ("nd", _p("language_name", "North Ndebele")),
        ("se", _p("language_name", "Northern Sami")),
        ("no", _p("language_name", "Norwegian")),
        ("nb", _p("language_name", "Norwegian Bokmål")),
        ("nn", _p("language_name", "Norwegian Nynorsk")),
        ("ny", _p("language_name", "Nyanja")),
        ("oc", _p("language_name", "Occitan")),
        ("od", _p("language_name", "Odia")),
        ("oj", _p("language_name", "Ojibwa")),
        ("om", _p("language_name", "Oromo")),
        ("os", _p("language_name", "Ossetian")),
        ("pi", _p("language_name", "Pali")),
        ("pa", _p("language_name", "Panjabi")),
        ("fa", _p("language_name", "Persian")),
        ("pl", _p("language_name", "Polish")),
        ("pt", _p("language_name", "Portuguese")),
        ("ps", _p("language_name", "Pushto")),
        ("qu", _p("language_name", "Quechua")),
        ("ro", _p("language_name", "Romanian")),
        ("rm", _p("language_name", "Romansh")),
        ("rn", _p("language_name", "Rundi")),
        ("ru", _p("language_name", "Russian")),
        ("sm", _p("language_name", "Samoan")),
        ("sg", _p("language_name", "Sango")),
        ("sa", _p("language_name", "Sanskrit")),
        ("sc", _p("language_name", "Sardinian")),
        ("sat", _p("language_name", "Santali")),
        ("gd", _p("language_name", "Scottish Gaelic")),
        ("sr", _p("language_name", "Serbian")),
        ("sh", _p("language_name", "Serbo-Croatian")),
        ("sn", _p("language_name", "Shona")),
        ("ii", _p("language_name", "Sichuan Yi")),
        ("sd", _p("language_name", "Sindhi")),
        ("si", _p("language_name", "Sinhala")),
        ("sk", _p("language_name", "Slovak")),
        ("sl", _p("language_name", "Slovenian")),
        ("so", _p("language_name", "Somali")),
        ("nr", _p("language_name", "South Ndebele")),
        ("st", _p("language_name", "Southern Sotho")),
        ("es", _p("language_name", "Spanish")),
        ("su", _p("language_name", "Sundanese")),
        ("sw", _p("language_name", "Swahili")),
        ("ss", _p("language_name", "Swati")),
        ("sv", _p("language_name", "Swedish")),
        ("zh-tw", _p("language_name", "Taiwanese")),
        ("tl", _p("language_name", "Tagalog")),
        ("ty", _p("language_name", "Tahitian")),
        ("tg", _p("language_name", "Tajik")),
        ("ta", _p("language_name", "Tamil")),
        ("tt", _p("language_name", "Tatar")),
        ("te", _p("language_name", "Telugu")),
        ("th", _p("language_name", "Thai")),
        ("bo", _p("language_name", "Tibetan")),
        ("ti", _p("language_name", "Tigrinya")),
        ("to", _p("language_name", "Tonga")),
        ("ts", _p("language_name", "Tsonga")),
        ("tn", _p("language_name", "Tswana")),
        ("tr", _p("language_name", "Turkish")),
        ("tk", _p("language_name", "Turkmen")),
        ("tw", _p("language_name", "Twi")),
        ("ug", _p("language_name", "Uighur")),
        ("uk", _p("language_name", "Ukrainian")),
        ("ur", _p("language_name", "Urdu")),
        ("uz", _p("language_name", "Uzbek")),
        ("ve", _p("language_name", "Venda")),
        ("vi", _p("language_name", "Vietnamese")),
        ("vo", _p("language_name", "Volapük")),
        ("wa", _p("language_name", "Walloon")),
        ("cy", _p("language_name", "Welsh")),
        ("hyw", _p("language_name", "Western Armenian")),
        ("fy", _p("language_name", "Western Frisian")),
        ("wo", _p("language_name", "Wolof")),
        ("xh", _p("language_name", "Xhosa")),
        ("yi", _p("language_name", "Yiddish")),
        ("yo", _p("language_name", "Yoruba")),
        ("za", _p("language_name", "Zhuang")),
        ("zu", _p("language_name", "Zulu")),
    ]

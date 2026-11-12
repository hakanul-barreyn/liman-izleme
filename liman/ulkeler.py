"""Bayrak ve ülke adları: GFW'nin ISO3 kodları ve MMSI'nin ilk üç hanesi (MID) için Türkçe adlar."""
from __future__ import annotations

ISO3_AD = {
    "ALB": "Arnavutluk", "ARE": "BAE", "ATG": "Antigua ve Barbuda", "AZE": "Azerbaycan", "BEL": "Belçika",
    "BGR": "Bulgaristan", "BHR": "Bahreyn", "BHS": "Bahamalar", "BLZ": "Belize", "BOL": "Bolivya", "BRB": "Barbados",
    "CHE": "İsviçre", "CHN": "Çin", "CMR": "Kamerun", "COK": "Cook Adaları", "COM": "Komorlar", "CYP": "Kıbrıs",
    "DEU": "Almanya", "DJI": "Cibuti", "DMA": "Dominika", "DNK": "Danimarka", "DZA": "Cezayir", "EGY": "Mısır",
    "ESP": "İspanya", "FRA": "Fransa", "GAB": "Gabon", "GBR": "Birleşik Krallık", "GEO": "Gürcistan",
    "GIB": "Cebelitarık", "GNB": "Gine-Bissau", "GNQ": "Ekvator Ginesi", "GRC": "Yunanistan", "GUY": "Guyana",
    "HKG": "Hong Kong", "HND": "Honduras", "HRV": "Hırvatistan", "IMN": "Man Adası", "IND": "Hindistan",
    "IRN": "İran", "IRQ": "Irak", "ISR": "İsrail", "ITA": "İtalya", "JAM": "Jamaika", "JOR": "Ürdün",
    "JPN": "Japonya", "KAZ": "Kazakistan", "KHM": "Kamboçya", "KNA": "Saint Kitts ve Nevis", "KOR": "Güney Kore",
    "KWT": "Kuveyt", "LBN": "Lübnan", "LBR": "Liberya", "LBY": "Libya", "LCA": "Saint Lucia", "LUX": "Lüksemburg",
    "MAR": "Fas", "MDA": "Moldova", "MHL": "Marshall Adaları", "MLT": "Malta", "MNE": "Karadağ", "MNG": "Moğolistan",
    "NLD": "Hollanda", "NOR": "Norveç", "OMN": "Umman", "PAK": "Pakistan", "PAN": "Panama", "PLW": "Palau",
    "PRT": "Portekiz", "QAT": "Katar", "ROU": "Romanya", "RUS": "Rusya", "SAU": "Suudi Arabistan", "SGP": "Singapur",
    "SLE": "Sierra Leone", "STP": "São Tomé ve Príncipe", "SVN": "Slovenya", "SWE": "İsveç", "SYR": "Suriye",
    "TGO": "Togo", "TUN": "Tunus", "TUR": "Türkiye", "TUV": "Tuvalu", "TZA": "Tanzanya", "UKR": "Ukrayna",
    "USA": "ABD", "MYS": "Malezya", "VNM": "Vietnam", "URY": "Uruguay", "COL": "Kolombiya", "LKA": "Sri Lanka",
    "ZAF": "Güney Afrika", "BRA": "Brezilya", "ARG": "Arjantin", "MEX": "Meksika", "CAN": "Kanada", "IDN": "Endonezya",
    "THA": "Tayland", "TWN": "Tayvan", "PHL": "Filipinler", "BGD": "Bangladeş", "AUS": "Avustralya", "NGA": "Nijerya",
    "SEN": "Senegal", "CIV": "Fildişi Sahili", "GHA": "Gana", "KEN": "Kenya", "SDN": "Sudan", "YEM": "Yemen",
    "ERI": "Eritre", "FIN": "Finlandiya", "POL": "Polonya", "LVA": "Letonya", "LTU": "Litvanya", "EST": "Estonya",
    "IRL": "İrlanda", "ISL": "İzlanda", "PER": "Peru", "CHL": "Şili", "ECU": "Ekvador", "VEN": "Venezuela",
    "TTO": "Trinidad ve Tobago", "CUB": "Küba", "DOM": "Dominik Cumhuriyeti", "PRI": "Porto Riko", "VCT": "Saint Vincent ve Grenadinler", "VUT": "Vanuatu", "XXX": "X ülkesi", "YYY": "Y ülkesi",
}

# MMSI'nin ilk üç hanesi (Maritime Identification Digits) → ISO3; sık görülen bayraklar
MID_ISO3 = {
    "205": "BEL", "207": "BGR", "209": "CYP", "210": "CYP", "211": "DEU", "212": "CYP", "213": "GEO", "214": "MDA",
    "215": "MLT", "218": "DEU", "219": "DNK", "220": "DNK", "224": "ESP", "225": "ESP", "226": "FRA", "227": "FRA",
    "228": "FRA", "229": "MLT", "232": "GBR", "233": "GBR", "234": "GBR", "235": "GBR", "236": "GIB", "237": "GRC",
    "238": "HRV", "239": "GRC", "240": "GRC", "241": "GRC", "242": "MAR", "244": "NLD", "245": "NLD", "246": "NLD",
    "247": "ITA", "248": "MLT", "249": "MLT", "253": "LUX", "255": "PRT", "256": "MLT", "257": "NOR", "258": "NOR",
    "259": "NOR", "263": "PRT", "264": "ROU", "265": "SWE", "266": "SWE", "271": "TUR", "272": "UKR", "273": "RUS",
    "304": "ATG", "305": "ATG", "308": "BHS", "309": "BHS", "311": "BHS", "312": "BLZ", "314": "BRB", "325": "DMA",
    "334": "HND", "339": "JAM", "341": "KNA", "351": "PAN", "352": "PAN", "353": "PAN", "354": "PAN", "355": "PAN",
    "356": "PAN", "357": "PAN", "370": "PAN", "371": "PAN", "372": "PAN", "373": "PAN", "374": "PAN", "375": "VCT",
    "376": "VCT", "377": "VCT", "403": "SAU", "412": "CHN", "413": "CHN", "414": "CHN", "419": "IND", "422": "IRN",
    "423": "AZE", "428": "ISR", "431": "JPN", "436": "KAZ", "438": "JOR", "440": "KOR", "441": "KOR", "447": "KWT",
    "450": "LBN", "457": "MNG", "461": "OMN", "463": "PAK", "466": "QAT", "468": "SYR", "470": "ARE", "471": "ARE",
    "477": "HKG", "511": "PLW", "515": "KHM", "518": "COK", "538": "MHL", "563": "SGP", "564": "SGP", "565": "SGP",
    "566": "SGP", "572": "TUV", "576": "VUT", "577": "VUT", "605": "DZA", "613": "CMR", "616": "COM", "621": "DJI",
    "622": "EGY", "626": "GAB", "630": "GNB", "631": "GNQ", "636": "LBR", "637": "LBR", "642": "LBY", "667": "SLE",
    "668": "STP", "671": "TGO", "672": "TUN", "674": "TZA", "677": "TZA", "720": "BOL", "750": "GUY",
}


def ulke_adi(iso3: str | None) -> str:
    return ISO3_AD.get(iso3 or "", iso3 or "")


def bayrak(iso3: str | None = None, mmsi=None) -> str:
    """Geminin bayrağı: GFW'nin verdiği ISO3 kodu, yoksa MMSI'nin ilk üç hanesi."""
    if iso3:
        return ulke_adi(iso3)
    s = str(mmsi or "")
    return ulke_adi(MID_ISO3.get(s[:3])) if len(s) == 9 else ""

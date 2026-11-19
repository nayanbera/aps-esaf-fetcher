"""Country / US-state normalisation for the Statistics maps.

Countries are stored as ISO 3166-1 alpha-2 codes (the app's own country list, static/geo-data.js); names and
alpha-3 codes are accepted too.  The maps want alpha-3 codes (countries) and 2-letter codes (US states).
"""

from __future__ import annotations

import re
from pathlib import Path

_ISO3 = dict(p.split(":") for p in """
AF:AFG AX:ALA AL:ALB DZ:DZA AS:ASM AD:AND AO:AGO AI:AIA AQ:ATA AG:ATG AR:ARG AM:ARM AW:ABW AU:AUS AT:AUT AZ:AZE
BS:BHS BH:BHR BD:BGD BB:BRB BY:BLR BE:BEL BZ:BLZ BJ:BEN BM:BMU BT:BTN BO:BOL BQ:BES BA:BIH BW:BWA BV:BVT BR:BRA
IO:IOT BN:BRN BG:BGR BF:BFA BI:BDI CV:CPV KH:KHM CM:CMR CA:CAN KY:CYM CF:CAF TD:TCD CL:CHL CN:CHN CX:CXR CC:CCK
CO:COL KM:COM CG:COG CD:COD CK:COK CR:CRI CI:CIV HR:HRV CU:CUB CW:CUW CY:CYP CZ:CZE DK:DNK DJ:DJI DM:DMA DO:DOM
EC:ECU EG:EGY SV:SLV GQ:GNQ ER:ERI EE:EST SZ:SWZ ET:ETH FK:FLK FO:FRO FJ:FJI FI:FIN FR:FRA GF:GUF PF:PYF TF:ATF
GA:GAB GM:GMB GE:GEO DE:DEU GH:GHA GI:GIB GR:GRC GL:GRL GD:GRD GP:GLP GU:GUM GT:GTM GG:GGY GN:GIN GW:GNB GY:GUY
HT:HTI HM:HMD VA:VAT HN:HND HK:HKG HU:HUN IS:ISL IN:IND ID:IDN IR:IRN IQ:IRQ IE:IRL IM:IMN IL:ISR IT:ITA JM:JAM
JP:JPN JE:JEY JO:JOR KZ:KAZ KE:KEN KI:KIR KP:PRK KR:KOR KW:KWT KG:KGZ LA:LAO LV:LVA LB:LBN LS:LSO LR:LBR LY:LBY
LI:LIE LT:LTU LU:LUX MO:MAC MG:MDG MW:MWI MY:MYS MV:MDV ML:MLI MT:MLT MH:MHL MQ:MTQ MR:MRT MU:MUS YT:MYT MX:MEX
FM:FSM MD:MDA MC:MCO MN:MNG ME:MNE MS:MSR MA:MAR MZ:MOZ MM:MMR NA:NAM NR:NRU NP:NPL NL:NLD NC:NCL NZ:NZL NI:NIC
NE:NER NG:NGA NU:NIU NF:NFK MK:MKD MP:MNP NO:NOR OM:OMN PK:PAK PW:PLW PS:PSE PA:PAN PG:PNG PY:PRY PE:PER PH:PHL
PN:PCN PL:POL PT:PRT PR:PRI QA:QAT RE:REU RO:ROU RU:RUS RW:RWA BL:BLM SH:SHN KN:KNA LC:LCA MF:MAF PM:SPM VC:VCT
WS:WSM SM:SMR ST:STP SA:SAU SN:SEN RS:SRB SC:SYC SL:SLE SG:SGP SX:SXM SK:SVK SI:SVN SB:SLB SO:SOM ZA:ZAF GS:SGS
SS:SSD ES:ESP LK:LKA SD:SDN SR:SUR SJ:SJM SE:SWE CH:CHE SY:SYR TW:TWN TJ:TJK TZ:TZA TH:THA TL:TLS TG:TGO TK:TKL
TO:TON TT:TTO TN:TUN TR:TUR TM:TKM TC:TCA TV:TUV UG:UGA UA:UKR AE:ARE GB:GBR US:USA UM:UMI UY:URY UZ:UZB VU:VUT
VE:VEN VN:VNM VG:VGB VI:VIR WF:WLF EH:ESH YE:YEM ZM:ZMB ZW:ZWE XK:XKX
""".split())
_FROM3 = {v: k for k, v in _ISO3.items()}

# names as written in the app's country list, plus the usual alternatives
_NAMES: dict[str, str] = {}      # ISO2 -> display name
try:
    _src = (Path(__file__).resolve().parent.parent / "static" / "geo-data.js").read_text(encoding="utf-8")
    _block = _src.split("const GEO_COUNTRIES", 1)[1].split("];", 1)[0]      # the file also lists US states
    _NAMES = {c: n for c, n in re.findall(r'\["([A-Z]{2})","([^"]+)"\]', _block)}
except OSError:
    pass
_ALIASES = {"usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US", "america": "US",
            "uk": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "korea": "KR", "south korea": "KR",
            "republic of korea": "KR", "north korea": "KP", "russian federation": "RU", "czech republic": "CZ",
            "czechia": "CZ", "hong kong sar": "HK", "viet nam": "VN", "iran, islamic republic of": "IR",
            "taiwan, china": "TW", "p.r. china": "CN", "peoples republic of china": "CN", "the netherlands": "NL"}
_BY_NAME = {re.sub(r"[^a-z]", "", n.lower()): c for c, n in _NAMES.items()}
_BY_NAME.update({re.sub(r"[^a-z]", "", a): c for a, c in _ALIASES.items()})

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
_STATE_BY_NAME = {re.sub(r"[^a-z]", "", n.lower()): c for c, n in US_STATES.items()}


def iso2(value: str) -> str:
    """'US' / 'USA' / 'United States' / 'Korea (South)' -> 'US'; '' when not recognised."""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) == 2 and v.upper() in _ISO3:
        return v.upper()
    if len(v) == 3 and v.upper() in _FROM3:
        return _FROM3[v.upper()]
    return _BY_NAME.get(re.sub(r"[^a-z]", "", v.lower()), "")


def iso3(value: str) -> str:
    return _ISO3.get(iso2(value), "")


def country_name(code3: str) -> str:
    c = _FROM3.get(code3, "")
    return _NAMES.get(c, c)


def us_state(value: str) -> str:
    """'IL' / 'Illinois' -> 'IL'; '' when not a US state."""
    v = (value or "").strip()
    if len(v) == 2 and v.upper() in US_STATES:
        return v.upper()
    return _STATE_BY_NAME.get(re.sub(r"[^a-z]", "", v.lower()), "")

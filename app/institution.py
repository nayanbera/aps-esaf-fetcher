"""Institution, country, and state lookup from email domain.

Each entry: {"institution": str, "country": ISO-2, "state": US state abbr or ""}
Unknown domains return {"institution": "", "country": "", "state": ""}.
"""

from __future__ import annotations

_EMPTY: dict = {"institution": "", "country": "", "state": ""}

_DOMAIN_MAP: dict[str, dict] = {
    # ---------- DOE national laboratories ----------
    "anl.gov":           {"institution": "Argonne National Laboratory",              "country": "US", "state": "IL"},
    "ameslab.gov":       {"institution": "Ames National Laboratory",                 "country": "US", "state": "IA"},
    "bnl.gov":           {"institution": "Brookhaven National Laboratory",           "country": "US", "state": "NY"},
    "fnal.gov":          {"institution": "Fermi National Accelerator Laboratory",    "country": "US", "state": "IL"},
    "inl.gov":           {"institution": "Idaho National Laboratory",               "country": "US", "state": "ID"},
    "jlab.org":          {"institution": "Jefferson Lab",                            "country": "US", "state": "VA"},
    "lanl.gov":          {"institution": "Los Alamos National Laboratory",           "country": "US", "state": "NM"},
    "lbl.gov":           {"institution": "Lawrence Berkeley National Laboratory",    "country": "US", "state": "CA"},
    "llnl.gov":          {"institution": "Lawrence Livermore National Laboratory",   "country": "US", "state": "CA"},
    "nist.gov":          {"institution": "National Institute of Standards and Technology", "country": "US", "state": "MD"},
    "nih.gov":           {"institution": "National Institutes of Health",            "country": "US", "state": "MD"},
    "nrel.gov":          {"institution": "National Renewable Energy Laboratory",     "country": "US", "state": "CO"},
    "ornl.gov":          {"institution": "Oak Ridge National Laboratory",            "country": "US", "state": "TN"},
    "pnnl.gov":          {"institution": "Pacific Northwest National Laboratory",    "country": "US", "state": "WA"},
    "pppl.gov":          {"institution": "Princeton Plasma Physics Laboratory",      "country": "US", "state": "NJ"},
    "sandia.gov":        {"institution": "Sandia National Laboratories",             "country": "US", "state": "NM"},
    "slac.stanford.edu": {"institution": "SLAC National Accelerator Laboratory",     "country": "US", "state": "CA"},
    "sns.gov":           {"institution": "Spallation Neutron Source / ORNL",         "country": "US", "state": "TN"},
    # ---------- Canadian national labs ----------
    "cnl.ca":            {"institution": "Canadian Nuclear Laboratories",            "country": "CA", "state": ""},
    # ---------- European synchrotrons / labs ----------
    "esrf.eu":           {"institution": "European Synchrotron Radiation Facility",  "country": "FR", "state": ""},
    "diamond.ac.uk":     {"institution": "Diamond Light Source",                     "country": "GB", "state": ""},
    "desy.de":           {"institution": "DESY",                                     "country": "DE", "state": ""},
    "psi.ch":            {"institution": "Paul Scherrer Institut",                   "country": "CH", "state": ""},
    "maxiv.lu.se":       {"institution": "MAX IV Laboratory",                        "country": "SE", "state": ""},
    "helmholtz-berlin.de": {"institution": "Helmholtz-Zentrum Berlin",               "country": "DE", "state": ""},
    # ---------- US universities — Illinois ----------
    "uchicago.edu":      {"institution": "University of Chicago",                    "country": "US", "state": "IL"},
    "northwestern.edu":  {"institution": "Northwestern University",                  "country": "US", "state": "IL"},
    "uic.edu":           {"institution": "University of Illinois Chicago",           "country": "US", "state": "IL"},
    "illinois.edu":      {"institution": "University of Illinois Urbana-Champaign",  "country": "US", "state": "IL"},
    "iit.edu":           {"institution": "Illinois Institute of Technology",         "country": "US", "state": "IL"},
    # ---------- US universities — Midwest ----------
    "purdue.edu":        {"institution": "Purdue University",                        "country": "US", "state": "IN"},
    "iu.edu":            {"institution": "Indiana University",                       "country": "US", "state": "IN"},
    "nd.edu":            {"institution": "University of Notre Dame",                 "country": "US", "state": "IN"},
    "wisc.edu":          {"institution": "University of Wisconsin-Madison",          "country": "US", "state": "WI"},
    "marquette.edu":     {"institution": "Marquette University",                     "country": "US", "state": "WI"},
    "umich.edu":         {"institution": "University of Michigan",                   "country": "US", "state": "MI"},
    "msu.edu":           {"institution": "Michigan State University",                "country": "US", "state": "MI"},
    "wayne.edu":         {"institution": "Wayne State University",                   "country": "US", "state": "MI"},
    "osu.edu":           {"institution": "Ohio State University",                    "country": "US", "state": "OH"},
    "cwru.edu":          {"institution": "Case Western Reserve University",          "country": "US", "state": "OH"},
    "ohio.edu":          {"institution": "Ohio University",                          "country": "US", "state": "OH"},
    "uakron.edu":        {"institution": "University of Akron",                      "country": "US", "state": "OH"},
    "umn.edu":           {"institution": "University of Minnesota",                  "country": "US", "state": "MN"},
    "iastate.edu":       {"institution": "Iowa State University",                    "country": "US", "state": "IA"},
    "uiowa.edu":         {"institution": "University of Iowa",                       "country": "US", "state": "IA"},
    "unl.edu":           {"institution": "University of Nebraska-Lincoln",           "country": "US", "state": "NE"},
    "ku.edu":            {"institution": "University of Kansas",                     "country": "US", "state": "KS"},
    "ksu.edu":           {"institution": "Kansas State University",                  "country": "US", "state": "KS"},
    "ou.edu":            {"institution": "University of Oklahoma",                   "country": "US", "state": "OK"},
    "wustl.edu":         {"institution": "Washington University in St. Louis",       "country": "US", "state": "MO"},
    "missouri.edu":      {"institution": "University of Missouri",                   "country": "US", "state": "MO"},
    # ---------- US universities — East ----------
    "mit.edu":           {"institution": "Massachusetts Institute of Technology",    "country": "US", "state": "MA"},
    "harvard.edu":       {"institution": "Harvard University",                       "country": "US", "state": "MA"},
    "bu.edu":            {"institution": "Boston University",                        "country": "US", "state": "MA"},
    "neu.edu":           {"institution": "Northeastern University",                  "country": "US", "state": "MA"},
    "tufts.edu":         {"institution": "Tufts University",                         "country": "US", "state": "MA"},
    "yale.edu":          {"institution": "Yale University",                          "country": "US", "state": "CT"},
    "princeton.edu":     {"institution": "Princeton University",                     "country": "US", "state": "NJ"},
    "rutgers.edu":       {"institution": "Rutgers University",                       "country": "US", "state": "NJ"},
    "njit.edu":          {"institution": "New Jersey Institute of Technology",       "country": "US", "state": "NJ"},
    "columbia.edu":      {"institution": "Columbia University",                      "country": "US", "state": "NY"},
    "cornell.edu":       {"institution": "Cornell University",                       "country": "US", "state": "NY"},
    "rpi.edu":           {"institution": "Rensselaer Polytechnic Institute",         "country": "US", "state": "NY"},
    "albany.edu":        {"institution": "University at Albany, SUNY",               "country": "US", "state": "NY"},
    "rochester.edu":     {"institution": "University of Rochester",                  "country": "US", "state": "NY"},
    "upenn.edu":         {"institution": "University of Pennsylvania",               "country": "US", "state": "PA"},
    "pitt.edu":          {"institution": "University of Pittsburgh",                 "country": "US", "state": "PA"},
    "cmu.edu":           {"institution": "Carnegie Mellon University",               "country": "US", "state": "PA"},
    "psu.edu":           {"institution": "Pennsylvania State University",            "country": "US", "state": "PA"},
    "drexel.edu":        {"institution": "Drexel University",                        "country": "US", "state": "PA"},
    "temple.edu":        {"institution": "Temple University",                        "country": "US", "state": "PA"},
    "brown.edu":         {"institution": "Brown University",                         "country": "US", "state": "RI"},
    "jhu.edu":           {"institution": "Johns Hopkins University",                 "country": "US", "state": "MD"},
    "umd.edu":           {"institution": "University of Maryland",                   "country": "US", "state": "MD"},
    "gmu.edu":           {"institution": "George Mason University",                  "country": "US", "state": "VA"},
    "georgetown.edu":    {"institution": "Georgetown University",                    "country": "US", "state": "DC"},
    # ---------- US universities — South ----------
    "duke.edu":          {"institution": "Duke University",                          "country": "US", "state": "NC"},
    "unc.edu":           {"institution": "University of North Carolina at Chapel Hill", "country": "US", "state": "NC"},
    "ncsu.edu":          {"institution": "North Carolina State University",          "country": "US", "state": "NC"},
    "gatech.edu":        {"institution": "Georgia Institute of Technology",          "country": "US", "state": "GA"},
    "emory.edu":         {"institution": "Emory University",                         "country": "US", "state": "GA"},
    "vanderbilt.edu":    {"institution": "Vanderbilt University",                    "country": "US", "state": "TN"},
    "ufl.edu":           {"institution": "University of Florida",                    "country": "US", "state": "FL"},
    "umiami.edu":        {"institution": "University of Miami",                      "country": "US", "state": "FL"},
    "fsu.edu":           {"institution": "Florida State University",                 "country": "US", "state": "FL"},
    "usf.edu":           {"institution": "University of South Florida",              "country": "US", "state": "FL"},
    "lsu.edu":           {"institution": "Louisiana State University",               "country": "US", "state": "LA"},
    "tulane.edu":        {"institution": "Tulane University",                        "country": "US", "state": "LA"},
    "utexas.edu":        {"institution": "University of Texas at Austin",            "country": "US", "state": "TX"},
    "rice.edu":          {"institution": "Rice University",                          "country": "US", "state": "TX"},
    "tamu.edu":          {"institution": "Texas A&M University",                     "country": "US", "state": "TX"},
    "uta.edu":           {"institution": "University of Texas at Arlington",         "country": "US", "state": "TX"},
    # ---------- US universities — Southwest / Mountain ----------
    "asu.edu":           {"institution": "Arizona State University",                 "country": "US", "state": "AZ"},
    "arizona.edu":       {"institution": "University of Arizona",                    "country": "US", "state": "AZ"},
    "unm.edu":           {"institution": "University of New Mexico",                 "country": "US", "state": "NM"},
    "utah.edu":          {"institution": "University of Utah",                       "country": "US", "state": "UT"},
    "colorado.edu":      {"institution": "University of Colorado Boulder",           "country": "US", "state": "CO"},
    "colostate.edu":     {"institution": "Colorado State University",                "country": "US", "state": "CO"},
    "boisestate.edu":    {"institution": "Boise State University",                   "country": "US", "state": "ID"},
    "umt.edu":           {"institution": "University of Montana",                    "country": "US", "state": "MT"},
    "unr.edu":           {"institution": "University of Nevada, Reno",               "country": "US", "state": "NV"},
    "unlv.edu":          {"institution": "University of Nevada, Las Vegas",          "country": "US", "state": "NV"},
    # ---------- US universities — West ----------
    "caltech.edu":       {"institution": "California Institute of Technology",       "country": "US", "state": "CA"},
    "stanford.edu":      {"institution": "Stanford University",                      "country": "US", "state": "CA"},
    "berkeley.edu":      {"institution": "University of California, Berkeley",       "country": "US", "state": "CA"},
    "ucla.edu":          {"institution": "University of California, Los Angeles",    "country": "US", "state": "CA"},
    "ucsd.edu":          {"institution": "University of California, San Diego",      "country": "US", "state": "CA"},
    "ucsb.edu":          {"institution": "University of California, Santa Barbara",  "country": "US", "state": "CA"},
    "ucsf.edu":          {"institution": "University of California, San Francisco",  "country": "US", "state": "CA"},
    "ucdavis.edu":       {"institution": "University of California, Davis",          "country": "US", "state": "CA"},
    "ucr.edu":           {"institution": "University of California, Riverside",      "country": "US", "state": "CA"},
    "uci.edu":           {"institution": "University of California, Irvine",         "country": "US", "state": "CA"},
    "ucsc.edu":          {"institution": "University of California, Santa Cruz",     "country": "US", "state": "CA"},
    "usc.edu":           {"institution": "University of Southern California",        "country": "US", "state": "CA"},
    "uw.edu":            {"institution": "University of Washington",                 "country": "US", "state": "WA"},
    "wsu.edu":           {"institution": "Washington State University",              "country": "US", "state": "WA"},
    "uoregon.edu":       {"institution": "University of Oregon",                     "country": "US", "state": "OR"},
    "oregonstate.edu":   {"institution": "Oregon State University",                  "country": "US", "state": "OR"},
    "hawaii.edu":        {"institution": "University of Hawaii",                     "country": "US", "state": "HI"},
    # ---------- Canadian universities ----------
    "utoronto.ca":       {"institution": "University of Toronto",                    "country": "CA", "state": ""},
    "mcgill.ca":         {"institution": "McGill University",                        "country": "CA", "state": ""},
    "ubc.ca":            {"institution": "University of British Columbia",           "country": "CA", "state": ""},
    "ualberta.ca":       {"institution": "University of Alberta",                    "country": "CA", "state": ""},
    "uwaterloo.ca":      {"institution": "University of Waterloo",                   "country": "CA", "state": ""},
    "queensu.ca":        {"institution": "Queen's University",                       "country": "CA", "state": ""},
    "yorku.ca":          {"institution": "York University",                          "country": "CA", "state": ""},
    "concordia.ca":      {"institution": "Concordia University",                     "country": "CA", "state": ""},
    "umontreal.ca":      {"institution": "Université de Montréal",                   "country": "CA", "state": ""},
    "usask.ca":          {"institution": "University of Saskatchewan",               "country": "CA", "state": ""},
    # ---------- Chinese institutions ----------
    "sdu.edu.cn":        {"institution": "Shandong University",                      "country": "CN", "state": ""},
    # ---------- Industry ----------
    "dow.com":           {"institution": "Dow Chemical",                             "country": "US", "state": "MI"},
    "dupont.com":        {"institution": "DuPont",                                   "country": "US", "state": "DE"},
    "3m.com":            {"institution": "3M",                                       "country": "US", "state": "MN"},
    "abbott.com":        {"institution": "Abbott Laboratories",                      "country": "US", "state": "IL"},
    "pfizer.com":        {"institution": "Pfizer",                                   "country": "US", "state": "NY"},
    "merck.com":         {"institution": "Merck",                                    "country": "US", "state": "NJ"},
    "novartis.com":      {"institution": "Novartis",                                 "country": "CH", "state": ""},
    "bp.com":            {"institution": "BP",                                       "country": "GB", "state": ""},
    "exxonmobil.com":    {"institution": "ExxonMobil",                              "country": "US", "state": "TX"},
}


def lookup_by_email(email: str) -> dict:
    """Return institution, country, and state for an email address.

    Returns a dict with keys 'institution', 'country', 'state'.
    All values are empty strings for unknown/personal domains.
    Strips leading subdomains so mail.mit.edu resolves via mit.edu.
    """
    if not email or "@" not in email:
        return _EMPTY.copy()
    domain = email.split("@", 1)[1].lower().strip()
    while domain:
        entry = _DOMAIN_MAP.get(domain)
        if entry:
            return entry.copy()
        parts = domain.split(".", 1)
        if len(parts) < 2:
            break
        domain = parts[1]
    return _EMPTY.copy()

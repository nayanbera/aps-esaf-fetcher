"""Institution lookup from email domain.

Covers national labs, DOE facilities, and universities that regularly
use APS. Unknown domains return an empty string.
"""

from __future__ import annotations

# email-domain → institution display name
_DOMAIN_MAP: dict[str, str] = {
    # ---------- DOE national laboratories ----------
    "anl.gov":          "Argonne National Laboratory",
    "bnl.gov":          "Brookhaven National Laboratory",
    "fnal.gov":         "Fermi National Accelerator Laboratory",
    "jlab.org":         "Jefferson Lab",
    "lanl.gov":         "Los Alamos National Laboratory",
    "lbl.gov":          "Lawrence Berkeley National Laboratory",
    "llnl.gov":         "Lawrence Livermore National Laboratory",
    "nrel.gov":         "National Renewable Energy Laboratory",
    "ornl.gov":         "Oak Ridge National Laboratory",
    "pnnl.gov":         "Pacific Northwest National Laboratory",
    "pppl.gov":         "Princeton Plasma Physics Laboratory",
    "sandia.gov":       "Sandia National Laboratories",
    "slac.stanford.edu":"SLAC National Accelerator Laboratory",
    "sns.gov":          "Spallation Neutron Source",
    "inl.gov":          "Idaho National Laboratory",
    "nist.gov":         "National Institute of Standards and Technology",
    "nih.gov":          "National Institutes of Health",
    # ---------- Canadian national labs ----------
    "cnl.ca":           "Canadian Nuclear Laboratories",
    # ---------- European synchrotrons / labs ----------
    "esrf.eu":          "European Synchrotron Radiation Facility",
    "diamond.ac.uk":    "Diamond Light Source",
    "desy.de":          "DESY",
    "psi.ch":           "Paul Scherrer Institut",
    "maxiv.lu.se":      "MAX IV Laboratory",
    "helmholtz-berlin.de": "Helmholtz-Zentrum Berlin",
    # ---------- US universities (IL) ----------
    "uchicago.edu":     "University of Chicago",
    "northwestern.edu": "Northwestern University",
    "uic.edu":          "University of Illinois Chicago",
    "illinois.edu":     "University of Illinois Urbana-Champaign",
    "purdue.edu":       "Purdue University",
    "iu.edu":           "Indiana University",
    "nd.edu":           "University of Notre Dame",
    "wisc.edu":         "University of Wisconsin-Madison",
    # ---------- US universities (East) ----------
    "mit.edu":          "Massachusetts Institute of Technology",
    "harvard.edu":      "Harvard University",
    "yale.edu":         "Yale University",
    "princeton.edu":    "Princeton University",
    "columbia.edu":     "Columbia University",
    "cornell.edu":      "Cornell University",
    "upenn.edu":        "University of Pennsylvania",
    "brown.edu":        "Brown University",
    "bu.edu":           "Boston University",
    "neu.edu":          "Northeastern University",
    "tufts.edu":        "Tufts University",
    "rpi.edu":          "Rensselaer Polytechnic Institute",
    "jhu.edu":          "Johns Hopkins University",
    "umd.edu":          "University of Maryland",
    "gmu.edu":          "George Mason University",
    "georgetown.edu":   "Georgetown University",
    "duke.edu":         "Duke University",
    "unc.edu":          "University of North Carolina at Chapel Hill",
    "ncsu.edu":         "North Carolina State University",
    "gatech.edu":       "Georgia Institute of Technology",
    "emory.edu":        "Emory University",
    "ufl.edu":          "University of Florida",
    "umiami.edu":       "University of Miami",
    "fsu.edu":          "Florida State University",
    "usf.edu":          "University of South Florida",
    "pitt.edu":         "University of Pittsburgh",
    "cmu.edu":          "Carnegie Mellon University",
    "psu.edu":          "Pennsylvania State University",
    "drexel.edu":       "Drexel University",
    "temple.edu":       "Temple University",
    "rutgers.edu":      "Rutgers University",
    "njit.edu":         "New Jersey Institute of Technology",
    # ---------- US universities (Midwest) ----------
    "umich.edu":        "University of Michigan",
    "msu.edu":          "Michigan State University",
    "wayne.edu":        "Wayne State University",
    "osu.edu":          "Ohio State University",
    "cwru.edu":         "Case Western Reserve University",
    "umn.edu":          "University of Minnesota",
    "unl.edu":          "University of Nebraska-Lincoln",
    "ku.edu":           "University of Kansas",
    "ksu.edu":          "Kansas State University",
    "iastate.edu":      "Iowa State University",
    "uiowa.edu":        "University of Iowa",
    "wustl.edu":        "Washington University in St. Louis",
    "missouri.edu":     "University of Missouri",
    "tulane.edu":       "Tulane University",
    # ---------- US universities (South/Southwest) ----------
    "utexas.edu":       "University of Texas at Austin",
    "rice.edu":         "Rice University",
    "tamu.edu":         "Texas A&M University",
    "uta.edu":          "University of Texas at Arlington",
    "asu.edu":          "Arizona State University",
    "arizona.edu":      "University of Arizona",
    "unm.edu":          "University of New Mexico",
    "lsu.edu":          "Louisiana State University",
    "vanderbilt.edu":   "Vanderbilt University",
    # ---------- US universities (West) ----------
    "caltech.edu":      "California Institute of Technology",
    "stanford.edu":     "Stanford University",
    "berkeley.edu":     "University of California, Berkeley",
    "ucla.edu":         "University of California, Los Angeles",
    "ucsd.edu":         "University of California, San Diego",
    "ucsb.edu":         "University of California, Santa Barbara",
    "ucsf.edu":         "University of California, San Francisco",
    "ucdavis.edu":      "University of California, Davis",
    "ucr.edu":          "University of California, Riverside",
    "uci.edu":          "University of California, Irvine",
    "ucsc.edu":         "University of California, Santa Cruz",
    "uw.edu":           "University of Washington",
    "wsu.edu":          "Washington State University",
    "uoregon.edu":      "University of Oregon",
    "oregonstate.edu":  "Oregon State University",
    "utah.edu":         "University of Utah",
    "colorado.edu":     "University of Colorado Boulder",
    "colostate.edu":    "Colorado State University",
    "unr.edu":          "University of Nevada, Reno",
    "unlv.edu":         "University of Nevada, Las Vegas",
    "usc.edu":          "University of Southern California",
    # ---------- Canadian universities ----------
    "utoronto.ca":      "University of Toronto",
    "mcgill.ca":        "McGill University",
    "ubc.ca":           "University of British Columbia",
    "ualberta.ca":      "University of Alberta",
    "uwaterloo.ca":     "University of Waterloo",
    "queensu.ca":       "Queen's University",
    "yorku.ca":         "York University",
    # ---------- Additional US universities ----------
    "albany.edu":       "University at Albany, SUNY",
    "uakron.edu":       "University of Akron",
    "boisestate.edu":   "Boise State University",
    "hawaii.edu":       "University of Hawaii",
    "iit.edu":          "Illinois Institute of Technology",
    "marquette.edu":    "Marquette University",
    "ohio.edu":         "Ohio University",
    "ou.edu":           "University of Oklahoma",
    "rochester.edu":    "University of Rochester",
    "umt.edu":          "University of Montana",
    # ---------- Additional Canadian universities ----------
    "concordia.ca":     "Concordia University",
    "umontreal.ca":     "Université de Montréal",
    "usask.ca":         "University of Saskatchewan",
    # ---------- Chinese institutions ----------
    "sdu.edu.cn":       "Shandong University",
    # ---------- Additional national labs ----------
    "ameslab.gov":      "Ames National Laboratory",
    # ---------- Industry / other ----------
    "dow.com":          "Dow Chemical",
    "dupont.com":       "DuPont",
    "3m.com":           "3M",
    "abbott.com":       "Abbott Laboratories",
    "pfizer.com":       "Pfizer",
    "merck.com":        "Merck",
    "novartis.com":     "Novartis",
    "bp.com":           "BP",
    "exxonmobil.com":   "ExxonMobil",
}


def lookup_by_email(email: str) -> str:
    """Return the institution name for a given email address, or '' if unknown."""
    if not email or "@" not in email:
        return ""
    domain = email.split("@", 1)[1].lower().strip()
    # Try exact match first, then strip leading subdomains one at a time
    while domain:
        inst = _DOMAIN_MAP.get(domain)
        if inst:
            return inst
        # strip leftmost label: foo.bar.edu → bar.edu
        parts = domain.split(".", 1)
        if len(parts) < 2:
            break
        domain = parts[1]
    return ""

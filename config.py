"""
config.py — Configuration for the Email Automation Engine.
"""

import os

# ── SMTP — Zoho Mail ──
SMTP_SERVER = "smtp.zoho.in"
SMTP_PORT = 587
SMTP_USE_TLS = True
DAILY_SEND_LIMIT = 500

# ── Fail-Fast ──
CONSECUTIVE_FAIL_THRESHOLD = 3
SMTP_TIMEOUT = 30
SMTP_RETRY_ATTEMPTS = 1

# ── Email Verification — MyEmailVerifier API ──
# Add as many API keys as you want (100 free/day each)
# Keys rotate automatically, using 90% of each limit
VERIFY_API_KEYS = [
    "6e9b414cc4751fdf32f7e53f35ede703",
    # "YOUR_API_KEY_2",
]
VERIFY_LIMIT_PER_KEY = 90
VERIFY_API_URL = "https://client.myemailverifier.com/verifier/validate_single"

# ── Paths ──
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

# ── Disposable Domains ──
DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net",
    "guerrillamail.org", "guerrillamail.de", "grr.la", "guerrillamailblock.com",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "throwaway.email",
    "throwaway.com", "yopmail.com", "yopmail.fr", "yopmail.net",
    "sharklasers.com", "guerrillamail.info", "spam4.me", "trashmail.com",
    "trashmail.me", "trashmail.net", "trashmail.org", "trashmail.io",
    "10minutemail.com", "10minutemail.net", "minutemail.com",
    "dispostable.com", "maildrop.cc", "mailnesia.com", "mailcatch.com",
    "tempail.com", "fakeinbox.com", "fakemail.net", "tempr.email",
    "discard.email", "discardmail.com", "discardmail.de",
    "emailondeck.com", "33mail.com", "getnada.com", "nada.email",
    "anonbox.net", "mytemp.email", "mohmal.com", "burnermail.io",
    "inboxbear.com", "mailsac.com", "harakirimail.com",
    "jetable.org", "spamgourmet.com", "spamfree24.org",
    "binkmail.com", "spaml.com", "uggsrock.com", "clrmail.com",
    "crazymailing.com", "deadaddress.com", "despammed.com",
    "devnullmail.com", "dontreg.com", "e4ward.com", "emailigo.de",
    "emailmiser.com", "emailsensei.com", "emailtemporario.com.br",
    "ephemail.net", "etranquil.com", "etranquil.net", "etranquil.org",
    "evopo.com", "explodemail.com", "filzmail.com", "fixmail.tk",
    "flyspam.com", "get2mail.fr", "getonemail.com", "getonemail.net",
    "girlsundertheinfluence.com", "gishpuppy.com", "goemailgo.com",
    "great-host.in", "greensloth.com", "haltospam.com",
    "hotpop.com", "ichimail.com", "imails.info", "incognitomail.com",
    "incognitomail.net", "incognitomail.org", "insorg-mail.info",
    "ipoo.org", "irish2me.com", "iwi.net", "jetable.com",
    "jetable.fr.nf", "jetable.net",
    "kasmail.com", "koszmail.pl", "kurzepost.de", "lawlita.com",
    "letthemeatspam.com", "lhsdv.com", "lifebyfood.com",
    "link2mail.net", "litedrop.com", "lookugly.com", "lopl.co.cc",
    "lortemail.dk", "lovemeleaveme.com", "lr78.com",
    "maileater.com", "mailexpire.com", "mailforspam.com",
    "mailin8r.com", "mailinator.net", "mailinator.org",
    "mailinator2.com", "mailincubator.com", "mailismagic.com",
    "mailme.ir", "mailme.lv", "mailmetrash.com", "mailmoat.com",
    "mailnull.com", "mailshell.com", "mailsiphon.com",
    "mailslite.com", "mailzilla.com", "mailzilla.org",
}

"""
Project-wide settings for the GRC tool: installed modules, database, security,
time zone and date format.

Secret values (SECRET_KEY, DEBUG) are not stored here; they are read from the
local `.env` file by `config/env.py`. See `.env.example` for what is needed.

Django settings reference: https://docs.djangoproject.com/en/6.1/ref/settings/
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import load_env_file, read_bool

# The project folder (the one containing manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent

load_env_file(BASE_DIR / ".env")


# --- Security --------------------------------------------------------------

# The secret key protects login sessions and form-forgery (CSRF) tokens.
# Refuse to start without one, rather than silently using a weak default.
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY is missing. Copy .env.example to .env and fill it in."
    )

# DEBUG shows detailed error pages. Useful on your own Mac, but it reveals
# internal details, so it defaults to off and must be off for any shared use.
DEBUG = read_bool("DEBUG", default=False)

# The app only answers requests addressed to this Mac itself.
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]


# --- Installed modules ("apps") --------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Our own modules
    "accounts",
    "risks",
    "controls",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Every page requires login unless explicitly marked otherwise (only the
    # login page is). Secure by default: a new page cannot be left open by
    # accident.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Project-wide templates (shared layout, login page) live in templates/.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database --------------------------------------------------------------

# Named grc.db (not Django's default db.sqlite3) so the `*.db` rule in
# .gitignore keeps it, and any real risk data in it, out of git.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "grc.db",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- User accounts and passwords -------------------------------------------

# Use our own user-account table (accounts.User) instead of Django's fixed
# one. This must be in place before the first migration; switching later
# means rebuilding the database.
AUTH_USER_MODEL = "accounts.User"

# Where to send people to log in, and where they land after logging in or out.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "risks:risk_list"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Language, time zone and date format -----------------------------------

# British English gives day-month-year dates, e.g. "5 Oct 2026" on screen,
# and accepts dates typed as 05/10/2026 in forms.
LANGUAGE_CODE = "en-gb"

TIME_ZONE = "Europe/Amsterdam"

USE_I18N = True

# Times are stored in UTC in the database and shown in Amsterdam time.
USE_TZ = True


# --- Static files (CSS) ----------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]


# --- Email -----------------------------------------------------------------

# Emails are printed in Terminal instead of being sent.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}

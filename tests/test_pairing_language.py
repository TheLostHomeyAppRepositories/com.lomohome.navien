"""Pairing and repair speak the reader's language.

The App Store review that prompted this found the pair and repair views shipping
Korean-only text. Fixing the markup is only half of it: both views print strings the
Python side hands back — `check_session`'s `reason`, and whatever a failed `login`
raises — so a translated view in front of a Korean-only handler still shows Korean.

These tests fence both halves, and the reason English has to be the *default* rather
than a fallback nobody reaches: `compat.ui_language` answers 'en' when Homey's Python
i18n is all we have, and the views answer 'en' when they cannot read a language either.
"""

import asyncio
import json
from pathlib import Path

import pytest

from navien_lib import i18n, pairing
from navien_lib.const import SETTING_PASSWORD, SETTING_UI_LANGUAGE, SETTING_USERNAME
from navien_lib.navien.api import NavienAuthError

ROOT = Path(__file__).resolve().parents[1]
VIEWS = sorted(ROOT.glob("drivers/*/pair/start.html")) + sorted(
    ROOT.glob("drivers/*/repair/reconnect.html")
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Session:
    """Collects the handlers `pairing.install*` registers."""

    def __init__(self):
        self.handlers = {}

    def set_handler(self, name, fn):
        self.handlers[name] = fn


class _Driver:
    def __init__(self, homey):
        self.homey = homey
        self.logs = []

    def log(self, *parts):
        self.logs.append(" ".join(str(p) for p in parts))


def _pair(make_homey, language="ko", **settings):
    driver = _Driver(make_homey(settings=settings, language=language))
    session = _Session()
    pairing.install(driver, session, build_devices=None)
    return driver, session


def _repair(make_homey, **settings):
    driver = _Driver(make_homey(settings=settings))
    session = _Session()
    pairing.install_repair(driver, session)
    return driver, session


# --- the handlers -------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "ko"])
def test_check_session_answers_in_the_language_the_view_reported(make_homey, language):
    """The view is the only one who knows: Homey's Python i18n reports the app's language."""
    _driver, session = _pair(make_homey)
    result = _run(session.handlers["check_session"]({"language": language}))

    assert result["ready"] is False
    assert result["reason"] == i18n.translate("error.no_credentials", language)
    # Not the same sentence in both languages — otherwise this test proves nothing.
    assert i18n.translate("error.no_credentials", "en") != i18n.translate(
        "error.no_credentials", "ko")


@pytest.mark.parametrize(
    "deliver",
    [
        lambda body: ((body,), {}),                  # positional
        lambda body: ((), {"data": body}),           # named — same parameter
        lambda body: ((None,), {"body": body}),      # wrapped in body=
        lambda body: ((), body),                     # flattened into kwargs
    ],
    ids=["positional", "data-named", "body-kwarg", "flattened"],
)
def test_the_language_survives_every_body_delivery_shape(make_homey, deliver):
    """The pair view's body carries nothing but the language.

    `_payload` used to look only for credentials, so a build that wrapped the body would
    hand back an empty dict and the report would vanish silently.
    """
    _driver, session = _pair(make_homey, language="ko")
    args, kwargs = deliver({"language": "en"})
    result = _run(session.handlers["check_session"](*args, **kwargs))

    assert result["reason"] == i18n.translate("error.no_credentials", "en")


def test_a_reported_language_is_remembered_for_the_device_messages(make_homey):
    """Pairing is often the first webview opened, so it is where the language comes from.

    Without this the device-side text would sit in English until the settings page
    happened to be visited.
    """
    driver, session = _pair(make_homey)
    _run(session.handlers["check_session"]({"language": "ko"}))

    assert driver.homey.settings.values[SETTING_UI_LANGUAGE] == "ko"


def test_a_view_that_reports_nothing_falls_back_to_the_stored_language(make_homey):
    _driver, session = _pair(make_homey, **{SETTING_UI_LANGUAGE: "ko"})
    result = _run(session.handlers["check_session"]({}))

    assert result["reason"] == i18n.translate("error.no_credentials", "ko")


@pytest.mark.parametrize("accessor", ["en", "ko"])
def test_with_no_report_and_nothing_stored_the_homey_accessor_decides(make_homey, accessor):
    """Last resort in `compat.ui_language`.

    On this firmware that accessor answers 'en' whatever the user set (docs/PORTING.md) —
    which is why the views report instead of relying on it, and why an app that reaches
    this branch lands on English rather than Korean.
    """
    _driver, session = _pair(make_homey, language=accessor)
    result = _run(session.handlers["check_session"]({}))

    assert result["reason"] == i18n.translate("error.no_credentials", accessor)
    if accessor == "en":
        assert result["reason"].isascii()


def test_a_ready_account_says_nothing_at_all(make_homey):
    _driver, session = _pair(
        make_homey, **{SETTING_USERNAME: "u", SETTING_PASSWORD: "p"})
    result = _run(session.handlers["check_session"]({"language": "en"}))

    assert result == {"ready": True, "reason": ""}


@pytest.mark.parametrize("language", ["en", "ko"])
def test_repair_rejects_a_blank_form_in_the_readers_language(make_homey, language):
    _driver, session = _repair(make_homey)
    with pytest.raises(Exception) as caught:
        _run(session.handlers["login"]({"username": "", "password": "", "language": language}))

    assert str(caught.value) == i18n.translate("error.need_both", language)


# --- the errors raised deeper down --------------------------------------------


@pytest.mark.parametrize("language", ["en", "ko"])
def test_an_auth_error_is_translated_from_its_key(language):
    """`navien/api.py` has no `homey` import, so it tags rather than translates."""
    exc = NavienAuthError("아이디 또는 비밀번호가 올바르지 않습니다.", "error.bad_credentials")

    assert pairing._auth_text(exc, language) == i18n.translate(
        "error.bad_credentials", language)


def test_an_auth_error_carrying_no_key_still_says_something():
    """Better a message in the wrong language than an empty red box."""
    exc = NavienAuthError("something went sideways")

    assert pairing._auth_text(exc, "en") == "something went sideways"


def test_an_untranslatable_key_falls_back_to_the_errors_own_text():
    exc = NavienAuthError("원문", "error.no_such_key_anywhere")

    assert pairing._auth_text(exc, "en") == "원문"


def test_the_signin_detail_survives_translation():
    exc = NavienAuthError("secured-sign-in 실패: nope", "error.signin_failed", detail="nope")

    assert "nope" in pairing._auth_text(exc, "en")
    assert pairing._auth_text(exc, "en").startswith("Sign-in was refused")


# --- the views themselves ------------------------------------------------------


def test_every_driver_ships_all_six_views():
    assert len(VIEWS) == 6, [str(p.relative_to(ROOT)) for p in VIEWS]


@pytest.mark.parametrize("path", VIEWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_markup_a_reviewer_sees_is_english(path):
    """Everything before `<script>` renders before any language is resolved.

    That is what the App Store reviewer opened, and it is what an English Homey shows if
    `getLanguage()` is unavailable — so the raw markup carries the English text and the
    Korean lives only in the `ko:` table.
    """
    text = path.read_text("utf-8")
    markup = text.split("<script", 1)[0]

    assert not any("가" <= ch <= "힣" for ch in markup), path.name
    assert 'data-i18n="' in markup


@pytest.mark.parametrize("path", VIEWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_each_view_defaults_to_english_and_reports_its_language(path):
    text = path.read_text("utf-8")

    assert 'var LANG = "en";' in text
    assert "en: {" in text and "ko: {" in text
    # The handler is told what was *resolved* — never the English default, which the app
    # would store as the user's language (0.6.5 did, and every status label went English).
    assert "language: REPORTED" in text and "language: LANG" not in text


LANGUAGE_VIEWS = VIEWS + [ROOT / "settings" / "index.html"]


@pytest.mark.parametrize("path", LANGUAGE_VIEWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_each_view_waits_for_the_language_promise(path):
    """`getLanguage()` returns a Promise on current Homey builds.

    Read as a string it became "[o" (pair views → English) or failed the type test (settings
    → its Korean default), and each reported that guess as the user's language.
    """
    text = path.read_text("utf-8")
    assert "typeof maybe.then" in text
    assert "H.language" in text or "ref.language" in text
    assert "getLanguage() ||" not in text
    assert 'typeof l === "string"' not in text


@pytest.mark.parametrize("path", VIEWS, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_data_i18n_key_is_missing_from_either_table(path):
    text = path.read_text("utf-8")
    keys = set(__import__("re").findall(r'data-i18n="([^"]+)"', text))

    for key in keys:
        assert f"{key}:" in text.split("en: {", 1)[1].split("ko: {", 1)[0], (path.name, key)
        assert f"{key}:" in text.split("ko: {", 1)[1], (path.name, key)


# --- the locale files ----------------------------------------------------------


def test_both_locales_carry_the_same_keys():
    """A key present in one file only silently falls back and looks like a bug elsewhere."""

    def flatten(node, prefix=""):
        out = set()
        for key, value in node.items():
            path = f"{prefix}{key}"
            out |= flatten(value, f"{path}.") if isinstance(value, dict) else {path}
        return out

    en = flatten(json.loads((ROOT / "locales/en.json").read_text("utf-8")))
    ko = flatten(json.loads((ROOT / "locales/ko.json").read_text("utf-8")))

    assert en == ko


def test_the_english_locale_is_actually_english():
    text = (ROOT / "locales/en.json").read_text("utf-8")

    assert not any("가" <= ch <= "힣" for ch in text)


# --- the language picker in the app settings -----------------------------------


def _root_api():
    import importlib.util
    spec = importlib.util.spec_from_file_location("navien_root_api", ROOT / "api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("pick", ["ko", "en"])
def test_a_picked_language_beats_whatever_was_detected(make_homey, pick):
    """A misdetection (0.6.5 stored "en" for Korean users) must be overridable by hand."""
    from navien_lib import compat
    other = "en" if pick == "ko" else "ko"
    homey = make_homey(settings={SETTING_UI_LANGUAGE: other})
    api = _root_api()

    res = _run(api.set_language(homey, body={"choice": pick}))
    assert res["language"] == pick and res["language_choice"] == pick
    # A later detection report is still remembered, but does not override the pick.
    _run(api.set_language(homey, body={"language": other}))
    assert _run(compat.ui_language(homey)) == pick


def test_auto_goes_back_to_detection(make_homey):
    from navien_lib import compat
    homey = make_homey(settings={SETTING_UI_LANGUAGE: "ko"})
    api = _root_api()
    _run(api.set_language(homey, body={"choice": "en"}))
    _run(api.set_language(homey, body={"choice": "auto"}))
    assert _run(compat.ui_language(homey)) == "ko"
    assert _run(api.get_status(homey))["language_choice"] == "auto"


def test_an_unknown_choice_is_ignored(make_homey):
    from navien_lib import compat
    homey = make_homey(settings={SETTING_UI_LANGUAGE: "ko"})
    _run(_root_api().set_language(homey, body={"choice": "fr"}))
    assert _run(compat.ui_language(homey)) == "ko"

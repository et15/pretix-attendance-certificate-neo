# Development notes for Claude

## pretix plugin quality checklist

Every change to this plugin must keep it compliant with the official pretix
"Plugin quality checklist":
https://docs.pretix.eu/dev/development/api/quality.html
(source: https://github.com/pretix/pretix/blob/master/doc/development/api/quality.rst).
Before finishing a feature or fix, go through the items that the change touches.
If the upstream checklist changes, it wins over this copy.

### A. Meta
1. Clearly licensed; license file and package metadata agree.
2. Unambiguous name, description and author metadata (`apps.py` `PretixPluginMeta`, `pyproject.toml`).
3. Clear versioning scheme; latest version stays compatible with the latest stable pretix (`compatibility` in `PretixPluginMeta`).
4. Packaged with standard Python packaging tools.
5. External dependencies are declared (`pyproject.toml` `dependencies`).
6. A contact address for security issues is provided.

### B. Isolation
1. Signal `dispatch_uid`s are prefixed with the plugin name.
2. Templates and static files live in `templates/<package>/` and `static/<package>/`.
3. Settings-store keys are prefixed with the plugin name.
4. User-session keys are prefixed with the plugin name.
5. Registered URLs are unlikely to clash with other plugins or future core URLs.

### C. Security
1. Important actions are logged (`log_action`) and a `logentry_display` receiver renders every action type used.
2. All views require appropriate permissions and use `event_urls` / `event_patterns` where appropriate.
3. Customer session data uses the cart session system where appropriate.
4. Payment providers: no card numbers stored; refunds are notified via webhook; webhooks are signature-verified or not trusted (data re-fetched from the API).

### D. Privacy
1. Store no personal data that the plugin does not need.
2. Personal data saved to the database gets a data shredder that offers it for download and then removes it (including log entries).

### E. Internationalization
1. All user-facing strings (Python, templates, JS) are wrapped in gettext calls.
2. No hardcoded languages, time zones, date or time formats (use Django `date_format` / event timezone).
3. Installing the plugin compiles `.po` to `.mo` files.

### F. Functionality
1. New models, or settings that reference model ids, are handled in `event_copy_data` / `item_copy_data` receivers.
2. Payment providers: webhook-like confirmation if not instant; refunds if possible; external refunds/overpayments create an external refund.
3. Checkout steps are tested together with the pretix widget.

### G. Code quality
1. isort and flake8 style is enforced (here via ruff with the `I`, `E`, `W` and `F` rules: `ruff format --check . && ruff check .`).
2. Unit tests for important business logic.
3. Functional tests for important interface parts.
4. Tests that permission checks work.
5. CI checks tests and style.

### H. Specific to pretix.eu (only if hosted there)
1. pretix.eu data reports cover the data stored by this plugin.
2. pretix.eu generated privacy statements include this plugin if needed.

## Known gaps against the checklist (audit 2026-10-28)

Remove an entry once it is fixed.

- A6: no security contact (only a GitHub noreply address).
- B1/B5: nav `dispatch_uid`s (`certificate_of_attendance_nav*`), URL paths and the `Event.attendance_certificate_layouts` related_name are the same as in the original pythonitalia plugin, so the two cannot be installed side by side as the README claims.
- B3: settings key `attendance_certificate_self_service` is not prefixed with the plugin name.
- C1: template toggle/assign are not logged; the log display for `...sent.attendee` looks up `OrderPosition` by `id` but `positionid` is stored.
- D2: no data shredder for the recipient/subject/message stored in `...sent.attendee` log entries.
- E1: default mail subject/text in `models.py` are untranslated English literals; `de` catalog is nearly empty.
- G4: several mutating views lack permission-denial tests.

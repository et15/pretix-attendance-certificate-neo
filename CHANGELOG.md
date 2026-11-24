## v1.1.0 (2026-11-24)

### Feat

- start copied templates deactivated and check names on activation
- keep template names unique per event; copy replaces the original
- copy organizer certificate templates to an event

### Fix

- show template lists before certificate assignments

## v1.0.1 (2026-10-23)

### Fix

- **fork**: show the plugin as Attendance Certificate Neo in the plugin list

## v1.0.0 (2026-10-23)

### Fork

- **Fix**: keep the plugin event-level under its translated name
- **Fix**: give cached certificate files a timezone-aware expiry
- **Refactor**: rename package to pretix_attendance_certificate_neo

### Certificate download

- **Fix**: show an error message instead of a 500 when downloading a certificate without a layout

### Sending to single attendees

- **Fix**: fall back to the order email when sending certificates to attendees

### Organizer-wide templates

- **Feat**: allow certificate layouts to be organizer-wide, not just per event
- **Feat**: add organizer-level management of certificate templates
- **Feat**: let events activate organizer-wide templates and keep their own
- **Feat**: let the download pick between multiple active templates
- **Feat**: let the single-attendee send pick between multiple templates
- **Feat**: let the bulk sendmail form pick between multiple templates
- **Feat**: add an icon to the organizer-level certificate templates nav entry
- **Feat**: let organizer-wide templates be edited and show where they are used
- **Fix**: show the template name instead of the object repr in choice widgets
- **Fix**: stop creating a "Default" template for every event

### Email text per template

- **Feat**: make the single-attendee certificate email subject and text configurable
- **Feat**: move the certificate email subject and text onto each template
- **Feat**: add a "use this template's email text" button to the bulk sendmail form
- **Feat**: show pretix' own placeholder list in the template form help text
- **Feat**: validate placeholders in the event template subject and text
- **Feat**: link template names to the designer, add design and mail text buttons for organizer templates in events
- **Feat**: prefill the bulk send form with the template's email text when there is only one
- **Fix**: don't fail with a 500 on the send page when the static manifest lacks the new JS
- **Fix**: make the template email placeholder help text accurate
- **Fix**: name {name_given_name} in the placeholder help text, with a heads-up
- **Refactor**: move the "use this template's email text" handler to a static file
- **Refactor**: reuse pretix' FormPlaceholderMixin for event template placeholders

### Event copy

- **Feat**: copy event-owned templates and their activations on event copy

### Check-in lists

- **Feat**: tie templates to check-in lists

### Self-service download

- **Feat**: add customer self-service certificate download

### Translations

- **Feat**: add German (informal) translation

### Digital signature

- **Feat**: digitally sign certificates of attendance (PAdES)

### Markdown text

- **Feat**: support Markdown in the free text of certificate text fields
- **Feat**: set code in a monospace pretix font if there is one
- **Feat**: support ++underline++ in the certificate text
- **Fix**: draw list bullets on the first line of an item

## v0.1.16 (2026-08-06)

Last release (0.1.16 on PyPI) of
[pythonitalia/pretix-plugin-attendance-certificate](https://github.com/pythonitalia/pretix-plugin-attendance-certificate),
which this plugin is forked from. Summary of its history from October 2022 to
August 2026, by Marco Acierno / Python Italia:

### Original plugin

- **Feat**: certificate layouts per event, designed in pretix' PDF layout editor, with an empty default layout
- **Feat**: send certificates by email through pretix' bulk sendmail, with email history entries
- **Feat**: log entry texts for certificate emails and layout changes
- **Feat**: buttons to download and send the certificate on each order position
- **Fix**: migration, django.urls import and plugin app config for newer pretix
- **Fix**: log entry display signal, error when no certificate layout exists, HTML of the position buttons

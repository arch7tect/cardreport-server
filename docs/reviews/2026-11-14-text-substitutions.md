# Text substitution integration review

The server delegates text substitution to CardReport 0.9 using existing template
registration and report binding. No second interpreter, new endpoint, database
migration or data transport is introduced. Source expressions remain stored;
actual typed values are substituted only when a report is bound.

Restricted read-only Claude review inspected both repositories and found no
blocking integration issue. It confirmed key-only one-row references, stored/listed
source titles, sanitized errors and original/normalized data preservation. It
requested version/dependency alignment at release and concrete read-only validation
steps for stored templates; both are part of the release change.

Daily fixtures cover JSON/YAML definitions, JSON/YAML datasets and typed CSV input.
Integration tests check registration, stored source, list title and located rejection.
Container tests exercise both PDF engines and HTML. The browser workflow uploads
CSV, previews substituted text and verifies original-file bytes. Documentation
binds every bundled template/data fixture, including the daily CSV.

The dependency range is >=0.9.0,<0.10 with an exact public-PyPI lock. Upgrade API and
workers together; use the documented compatibility check for literal Jinja delimiters
in older templates. No change to sanitized terminal job error details is claimed.

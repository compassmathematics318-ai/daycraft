# Daily work blocks, rooms and grouped map activities

Task definitions add `min_sessions_per_day` (default 1, nonnegative safe integer)
and nullable `max_sessions_per_day` (unlimited by default; positive safe integer,
at least the minimum). Weekly overrides and copied assignments retain these
settings. These fields count actual daily work blocks, including separate split
chunks, not completed logical sessions. Travel, breaks and skipped work do not
count. Completed, started and locked work counts toward that day's maximum.

The maximum is hard for generated and manually edited schedules. The minimum is
conditional and soft: zero work is always allowed; days with some work may report
a shortfall. It does not require daily recurrence or invent completion credit.
Weekly targets still count full logical sessions and remain soft. Limits group
by canonical task definition identity, across all internal logical-session units.
The weekly adapter supplies metadata-only `_daily_task_limits` entries even when
there are no new candidates, so protected work remains subject to validation.

Map presentation groups reusable definitions, weekly assignments and actual
occurrences/work chunks by stable underlying activity/task identity per saved
place. Each activity entry retains its dated children for schedule summaries and
editing. Different IDs with identical names remain different activities. Nearby
marker grouping does not merge saved-place identity. No source records are
deleted to change the presentation.

Room is optional contextual metadata attached to selected physical locations in
forms. Building identity comes from the saved place; redundant Building inputs
are removed. Existing stored building and room values remain intact on migration.
Changing or clearing a location clears its editable room context explicitly;
untouched historical records retain their original values.

Ownership: backend owns schemas/services/migration/map aggregation; scheduling
owns scheduler.py, weekly_scheduler.py and calendar_scheduler.py; frontend owns
frontend; independent QA owns e2e and review tests; lead owns data audit,
integration and final executed verification in PROGRESS.md.

Task management tabs are separate from effective scheduling workload. Every Week
manages recurring definitions; Week Specific manages only explicit/copied weekly
assignments. Materializing recurring progress or overriding one week does not
move a recurring task into Week Specific. Weekly summaries and optimization
continue using the complete combined workload. Recurring cards expose Adjust
selected week for exceptions and skips; Task Library retains reusable definitions.

# Universal locations and travel

This extends the existing Leaflet, saved-location entities, calendar, task and
OR-Tools services. Saved place IDs stay stable. Migration 0006 adds a nullable
JSON `occurrences.location_override`; existing rows and payloads are retained.

The repaired geocoding pipeline, structured failure responses, provider settings
and verified launcher-connectivity diagnosis are documented in
[SEARCH_REPAIR.md](SEARCH_REPAIR.md). This repair requires no migration.

Map entries now group definitions and dated occurrences by stable underlying
activity/task ID within each saved place; see [DAILY_BLOCKS_CONTRACT.md](DAILY_BLOCKS_CONTRACT.md).
Room metadata is optional per activity, weekly override or occurrence. Forms show
Room Number only for a selected physical place and use the place's identity
instead of a separate Building input. Existing saved building metadata is retained.

## Shared policy

Activities, classes, task definitions and planner blocks carry `location_id` and
`location_mode`: `unspecified`, `remote`, `preferred`, or `required`. Old records
with an ID infer required; without an ID they infer unspecified. Explicit remote
and unspecified policies have no physical ID. Preferred and required policies
must reference a saved place. Unknown is never implicitly remote.

Occurrences accept nullable `location_override:{location_id,location_mode}`;
null inherits the definition. Weekly task overrides use the same policy fields.
Planner blocks use `location_override:true` for an explicitly changed session.
Locked/started historical work retains its recorded location. Place changes
invalidate affected planning assumptions rather than deleting historical work.

Saved locations add address, building, room, floor, entrance and aliases. Search
returns suggestions for user confirmation; no result is selected automatically.
Public geocoding is explicitly submitted, cached and rate-limited, never called
on every keystroke. Saved matches are local. The geocoder and walking router
remain configurable with timeouts, attribution and labeled estimate fallback.

## Home and map

Settings add optional `home_location_id`, independent `start_at_home` and
`end_at_home` switches (both default false), optional paired `map_center_lat` and
`map_center_lon`, and `map_default_region`. Merely saving home does not request
routes. Home/default map centering does not assert a daily physical destination.
The existing `default_location_id` remains stored for compatibility; it does not
silently supply missing destinations or require trips at the day boundaries.

`GET /api/location-overview?week_start=YYYY-MM-DD` returns the containing Sunday
week and grouped saved places with references. Definitions have no invented
times; dated occurrences and actual saved task blocks have real timestamps.
`GET /api/location-search?query=...` searches saved place metadata locally.
Reference edit targets link to owning activities, tasks, occurrences or plans.

## Optimization

The CP-SAT chronological circuit includes physical-position variables. Required
venues constrain position; flexible nodes may relocate when a real travel interval
fits before them.
Unknown venues do not claim remote attendance: the result explicitly reports
that their travel coverage cannot be verified, while still preventing them from
erasing travel between known venues. Preferred tasks may use another suitable
feasible venue with a soft preference penalty. Candidates come from matching
verified capabilities and confirmed access, or explicit activity-specific user
confirmations. See [SEMANTIC_LOCATIONS.md](SEMANTIC_LOCATIONS.md) and
[VENUE_INTEGRITY.md](VENUE_INTEGRITY.md). Generated blocks retain the
requested `location_id` and expose `resolved_location_id` separately.

Home departure and return are separate optional arcs bounded by waking/sleeping
hours. Route time and configured buffer are hard transition requirements and
are displayed as travel blocks, excluded from productive work. The five-minute
grid conservatively reserves at least five minutes for different known IDs even
if a callback/manual route reports zero; identical location IDs need no walk.

## Ownership and verification

Backend owns schemas, calendar persistence, API integration and overview;
geospatial owns travel.py; scheduling owns scheduler.py, weekly_scheduler.py and
calendar_scheduler.py; frontend owns frontend; independent QA owns e2e and
review regressions. Lead owns this contract, data audits and final integration.
Actually executed test results and limitations are recorded in PROGRESS.md.

Alias and provider references: https://uwaterloo.ca/plant-operations/floor-plans,
https://operations.osmfoundation.org/policies/nominatim/, and
https://nominatim.org/release-docs/latest/api/Search/.

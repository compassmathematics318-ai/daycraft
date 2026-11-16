# Location search repair and scheduled-day controls

The 2026-11-11 regression was reproduced against the running application:
`Student Life Centre` returned HTTP 503 in approximately 1.16 seconds, while
`QNC Waterloo` returned cached results in approximately 78 milliseconds.
The former generic error conflated network, HTTP, parsing and coordinate errors.

Direct restricted-process provider requests failed immediately with ConnectError;
the same providers returned HTTP 200 with approved network access. Restarting the
normal launcher with network access, before changing the geocoding backend,
made the identical Student Life Centre request return HTTP 200 with the Waterloo
building at 43.4719722, -80.5452128. Evidence is recorded in
`test-results/search-repair-network-restart.json`. The old launcher had inherited
the agent test environment's outbound-network restriction; cached QNC results
masked the failure. The Windows double-click launcher itself was not rewritten.

Operationally, do not leave the user's live server running as a child of a
network-restricted test process. Use the normal launcher in an approved runtime
context when public provider access is required. Keep isolated test databases
and deterministic provider stubs separate from live verification. Do not add
self-elevation or permission workarounds to application code.

The replacement search pipeline keeps explicit user submission, local saved-place
reuse, validated provider coordinates, source attribution and user confirmation.
Aliases represent names, not invented coordinates. Context improves relevance
without restricting searches to the current region. Independent provider fallback
and distinct failure statuses are covered by backend and browser tests. No data
migration is required.

`POST /api/geocode` still accepts `{query}`. Success returns
`{results,status,message,context,diagnostics}`; `status` is `ok` or `no_results`.
Failure returns a structured object in `detail`, with `status` equal to
`rate_limited`, `timeout`, `unavailable`, `invalid_response`,
`configuration_error` or `invalid_query`. Invalid query responses use HTTP 422;
provider failures use HTTP 503. Each candidate carries validated coordinates,
provenance and confirmation metadata; saved candidates include `location_id`
for reuse. Empty results are not classified as a service outage.

`GEOCODER_URL` selects the Nominatim-compatible primary endpoint;
`GEOCODER_FALLBACK_URL` selects the Photon-compatible fallback (empty disables
it). Calls are submitted explicitly, serialized per provider, limited to three
attempts per search and use an eight-second request timeout. Successful provider
results cache for thirty days, empty results for five minutes, failures never.
The existing walking-route request timeout and route behavior are unchanged.

Task API field names and optimizer semantics remain unchanged. UI labels are
`Minimum work blocks on a scheduled day` and
`Maximum work blocks on a scheduled day`. Zero blocks is valid on an unscheduled
day. The minimum remains conditional and soft; the maximum remains hard. Daily
counts include individual split chunks; weekly counts retain logical-session
completion accounting. Independent solver review found no behavioral defect.

Final executed checks, live search evidence and limitations are recorded in
`PROGRESS.md` after integration.

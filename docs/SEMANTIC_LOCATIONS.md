# Suitability before venue optimization

This contract supersedes the preferred-place whitelist-only policy documented in
the initial venue-integrity repair. Required locations remain hard destinations.
Preferred locations retain a positive objective bonus, while supported suitable
alternatives may be considered without a separate opt-in. A singleton candidate
set means that no other suitable venue is supported by current evidence; it does
not change the activity's location meaning to required.

## Evidence and structured fields

Activity/task/weekly/occurrence location settings include optional
`location_requirements: string[]`. These are a user's declaration of the complete
venue needs. Empty needs permit conservative deterministic inference from activity
text and contextual project information. Specialized, conditional or ambiguous
needs require clarification. No LLM is used.

Saved places include `verified_capabilities: string[]`,
`access_confirmed: boolean` and `verification_notes: string`. Capabilities and
access are user confirmations, not guesses from a building name, map position or
search result. Presets are generic and custom tags are supported. Empty defaults
preserve existing places without inventing facts or authorizations.

Automatic preferred alternatives need every identified capability and confirmed
access. Existing explicitly confirmed alternative IDs remain meaningful activity
specific evidence, subject to known requirements. Nearby places are never
admitted just for convenience. The selected primary place remains the user's
chosen venue; missing capability tags do not erase that association.

`location_suitability` is server-derived evidence, with requirements, source,
confidence, candidate IDs, candidate evidence, and any limitation. API clients
cannot grant themselves candidate locations by sending this field. Generation and
manual validation rebuild it from authoritative definitions, weekly overrides,
occurrences and saved places. Protected history keeps its original evidence.
Location or activity changes invalidate affected plans; future unstarted work is
revalidated. Historical records are not rewritten.

## Feasibility and optimization

CP-SAT operates only within the suitability candidate set. Required places are
singletons regardless of candidate metadata. Actual venue IDs drive all travel
arcs, manual validation and exports. The configured preference remains separate
from the recorded actual venue. Primary preference has a positive objective
weight; priority, deadline, work-hour and session constraints remain intact.

Remote and unspecified nodes do not establish a mandatory destination. Physical
position may change before them only through a feasible, reserved travel interval.
Unknown locations remain labeled unknown, and remote physical positions are
explicitly assumptions. The solver must not force a flexible meal to stay at the
previous activity's destination when a real walking interval can precede it.

The previous equality between a flexible node's position and its predecessor's
position blocked feasible mornings: lunch ending at a fixed class's start forced
all preceding work to share that class venue. The corrected circuit allows walking
before lunch. Independent validation checks the same gap and routes.

## Controlled evidence and limits

`test-results/semantic-location/actual-solver-inputs.json` captures the actual
November 13 task/day inputs and route matrix from a private database copy. The
preserved solver starts its first work at 14:35, with lunch at noon. With identical
inputs, the corrected solver starts at 08:00, retains 315 productive minutes, and
passes independent validation. Both report OPTIMAL. Hours, priorities, seed and
solver limits were unchanged; no universal 08:00 rule was added.

Capability verification is local user knowledge. Daycraft does not verify current
opening hours, bookings or facility availability through an external service.
Inference is deliberately conservative and English rule based; explicit custom
requirements support other activities and regions. Routing-provider failure still
uses labeled estimates. Final executed tests and actual-data checks are recorded
in PROGRESS.md.

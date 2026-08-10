# MoySklad Counterparty Phone Linking Design

## Goal

When a local user confirms their email, reuse a counterparty that was created in MoySklad in advance when exactly one counterparty has the same normalized phone number. Create a new counterparty when no match or more than one match exists.

## Existing behavior

`UserManager.on_after_register()` requests email verification. MoySklad work happens later in `UserManager.on_after_verify()`: an already linked user is left unchanged; otherwise the backend always creates a counterparty and then stores its `id` and `meta` on the local user.

The frontend registration form sends Russian phone numbers as `+7 (999) 999-99-99`. Counterparties created manually in MoySklad may use other common representations of the same number.

## Agreed behavior

- Linking remains in `on_after_verify()`. Registration itself does not contact MoySklad.
- An already linked local user is not searched or created again.
- The supported common phone representations listed below are treated as equivalent, and formatting is ignored when locally comparing returned candidates.
- Russian prefixes `8`, `7`, and `+7` are equivalent for the same ten-digit national number.
- Exactly one normalized match is linked without changing that counterparty's name, email, description, phone, or other MoySklad fields.
- No normalized matches cause creation through the existing counterparty payload and naming convention.
- More than one normalized match also causes creation of a new counterparty. The backend does not choose an arbitrary existing match.
- MoySklad lookup failures and malformed lookup responses are errors, not "no match" results. The backend must not create a counterparty after a failed lookup.
- No database migration or frontend contract change is required.

## Phone normalization and search variants

A focused pure module owns normalization and candidate generation. Normalization removes every non-digit character. Ten digits are treated as a Russian national number and prefixed with `7`; eleven digits beginning with `8` are rewritten to begin with `7`; eleven digits beginning with `7` remain unchanged. Other digit strings retain their digits-only value so comparison remains deterministic.

For a Russian normalized number `7AAABBBCCDD`, the lookup includes the original input and a deduplicated set of common MoySklad representations:

- `+7 (AAA) BBB-CC-DD`
- `+7 AAA BBB-CC-DD`
- `+7 AAA BBB CC DD`
- `+7AAABBBCCDD`
- `7AAABBBCCDD`
- `8 (AAA) BBB-CC-DD`
- `8 AAA BBB-CC-DD`
- `8AAABBBCCDD`

For other numbers, the lookup includes the original input and digits-only form. Candidate generation does not scan every counterparty and does not attempt to enumerate arbitrary punctuation combinations.

MoySklad supports filtering a counterparty collection by `phone`, and repeated equality conditions for one field are interpreted as OR conditions. The repository sends the complete filter as a URL query parameter so `+`, spaces, parentheses, and other characters are encoded correctly. See the [MoySklad JSON API filtering documentation](https://dev.moysklad.ru/doc/api/remap/1.2/).

The server-side filter is only a candidate reduction step. Every returned row is normalized again locally. A row is a match only when its normalized `phone` equals the requested normalized phone.

## Component boundaries

### Phone helper

The pure helper module exposes normalization and search-variant generation. It has no FastAPI, database, network, or settings dependency and can be tested directly.

### Counterparty repository

`CounterpartyRepository` owns the encoded MoySklad GET request for phone candidates. It returns the response `rows` and raises on HTTP failures or invalid collection structure. Existing generic repository query behavior remains unchanged to avoid affecting other integrations that currently append pagination and expansion fragments to their filter strings.

### Counterparty manager

`CounterpartyManager` owns the match-or-create decision. Given the existing `CounterpartyCreate` payload, it:

1. generates phone candidates;
2. requests candidate rows from the repository;
3. normalizes and validates matching rows;
4. returns the existing counterparty when exactly one normalized match exists;
5. otherwise creates and returns a new counterparty.

The result also identifies whether the counterparty was linked or created so the caller can choose the correct notification text. A sole normalized match must contain a usable `id` and `meta`; a matching row without these fields is a malformed response and must raise instead of triggering creation.

### User verification hook

`UserManager.on_after_verify()` continues to build the current counterparty payload and delegates resolution to `CounterpartyManager`. It stores the returned `id` and `meta` on the local user before attempting the Telegram group notification.

The notification distinguishes linking an existing counterparty from creating a new one. Telegram remains a side effect: a notification failure is logged and does not undo or report failure for an already persisted MoySklad link. Existing behavior for a user that already has `moysklad_counterparty_id` remains unchanged.

## Data flow

1. The user confirms their email.
2. The hook exits through the existing path if the local user is already linked.
3. The hook constructs the existing `CounterpartyCreate` payload.
4. The manager normalizes the phone and searches MoySklad using common exact representations.
5. The manager normalizes returned phone values and counts exact normalized matches.
6. One match is reused; zero or multiple matches cause a new counterparty to be created.
7. The local user is updated with the selected counterparty `id` and `meta`.
8. The backend attempts the corresponding Telegram notification.

## Error handling

- Authentication, timeout, transport, non-success HTTP, JSON decoding, and invalid collection errors during lookup propagate. Creation is not attempted.
- A malformed matching counterparty without a usable `id` or `meta` raises. Creation is not attempted.
- A create failure propagates and leaves the local link unchanged.
- A local user update failure propagates and can leave a newly created external counterparty unlinked. Automatic reconciliation of that pre-existing failure mode is outside this change.
- Telegram failure after persistence is logged without clearing the link or converting the verification result into a retryable counterparty operation.
- Search and tests never contact production services without an explicitly approved integration run.

## Testing

Tests use fakes or patched HTTP calls only and cover:

- equivalent normalization of `+7 (999) 123-45-67`, `79991234567`, and `8 999 123 45 67`;
- deterministic handling of non-Russian or unusual digit strings;
- the deduplicated common search representations;
- correct query parameter encoding for `+`, spaces, parentheses, and dashes;
- repository HTTP errors and malformed collection responses;
- one normalized match returning the existing counterparty without a create call;
- zero normalized matches creating a counterparty;
- multiple normalized matches creating a new counterparty;
- filtered false positives being rejected by normalized local comparison;
- a malformed sole match raising without creation;
- lookup failure raising without creation;
- the verification hook persisting the returned `id` and `meta`;
- distinct linked-versus-created notification text;
- Telegram running after persistence and not undoing the link on failure;
- the existing early return for an already linked user.

After implementation, run the focused tests and the repository-required `scripts/check.ps1`. Because there is no API contract change, the frontend check is not required.

## Out of scope

- Linking before email verification.
- Updating manually maintained MoySklad counterparty fields from registration data.
- Merging duplicate MoySklad counterparties.
- Scanning or paginating the complete counterparty collection.
- Adding a database uniqueness constraint for phone numbers.
- Changing the registration form or public API schemas.

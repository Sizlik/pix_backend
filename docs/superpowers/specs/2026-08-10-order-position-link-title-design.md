# Order Position Link Title Design

## Context

The frontend currently detects HTTP and HTTPS URLs in the `Позиция` column on both the new-order page and the existing-order page. It renders the URL as a clickable link, but the visible text remains the raw URL. The browser cannot reliably read the HTML of arbitrary third-party pages because of cross-origin restrictions, so title resolution must happen through the backend.

## Goals

1. Replace the visible URL in a position with the remote page's HTML `<title>` when it can be resolved.
2. Preserve the original URL as the link destination.
3. Support the position table on both the new-order page and the existing-order page.
4. Open position links in a new browser tab without giving the destination access to the originating window.
5. Keep the raw URL as a clickable fallback whenever title resolution fails.
6. Support arbitrary public HTTP and HTTPS pages without allowing the backend to access private or local network resources.

## Non-goals

- Persisting page titles in PostgreSQL, MoySklad, or order payloads.
- Keeping titles synchronized after an order has been created.
- Rendering Open Graph metadata, descriptions, images, or rich link previews.
- Executing JavaScript on the remote page to discover a client-rendered title.
- Guaranteeing a title for pages that require authentication, reject automated clients, or return non-HTML content.

## User-visible Behavior

The shared position renderer preserves ordinary text and recognizes HTTP or HTTPS URLs within it. A URL is immediately rendered as a clickable link using the URL itself as its initial label. The renderer requests the page title in the background and replaces only that URL's label when a non-empty title is returned.

Links use `target="_blank"` and `rel="noopener noreferrer"`. If the request is rejected, times out, returns an error, returns non-HTML content, or produces no usable `<title>`, the link remains usable and continues to display the original URL. Title lookup failures do not display a toast and do not block order creation or order viewing.

Although the expected position normally contains one URL, the renderer supports multiple URLs in the same position independently. Surrounding text and punctuation remain visible and are not included in the link destination.

## Architecture

### Frontend

A shared React component owns position-text parsing, title loading, fallback behavior, and anchor security attributes. Both existing `positionCell` renderers delegate to this component instead of duplicating URL detection.

The API client in `src/routes/routes.tsx` exposes a typed title-lookup function. It calls the backend without toast notifications. Exact URLs are deduplicated in the browser for the lifetime of the loaded application so that repeated positions do not trigger duplicate requests. The cache stores both resolved titles and fallback results; it is not persisted between browser sessions.

### Backend

The backend exposes an authenticated endpoint under the existing `/api_v1` prefix:

```text
POST /api_v1/link-preview/title
Authorization: <existing bearer token>
Content-Type: application/json

{"url": "https://example.com/product"}
```

Successful lookup:

```json
{"title": "Example product"}
```

Unavailable or missing title:

```json
{"title": null}
```

Malformed or disallowed URLs return a validation error. Upstream availability failures are normalized to `200` with a null title because the raw URL is the specified fallback and the lookup is optional UI enrichment.

The route handles transport and authentication only. A manager coordinates validation and title extraction, while a dedicated external-service repository performs the HTTP request. This preserves the existing route → dependency → manager → repository boundary.

## URL and Network Safety

The title endpoint is an SSRF boundary. Before opening a connection, it must:

- accept only absolute `http` and `https` URLs;
- reject URLs containing embedded usernames or passwords;
- resolve the destination hostname and reject the request if any resolved address is loopback, private, link-local, multicast, reserved, unspecified, or otherwise non-global;
- connect only to a validated public address while preserving the original hostname for the HTTP `Host` header and TLS certificate validation;
- apply the same validation and address pinning to every redirect target;
- limit redirect count, connection/read duration, and downloaded response bytes;
- accept only HTML/XHTML response content for title extraction;
- avoid returning upstream response bodies, network details, or internal addresses to the caller.

Redirects to local or private destinations are rejected even when the initial URL is public. DNS resolution and connection behavior must not leave a time-of-check/time-of-use gap that permits DNS rebinding.

## Title Extraction

The response is decoded using its declared character encoding when available, with a safe fallback for invalid or absent declarations. Extraction reads only the HTML `<title>` element; it does not execute scripts. HTML entities are decoded, internal whitespace is collapsed, and leading/trailing whitespace is removed.

An empty result is treated as no title. The returned title is length-limited before it reaches the browser so a remote page cannot create an unbounded grid cell or API response. The exact timeout, byte limit, redirect limit, and title-length limit are centralized constants covered by tests rather than configurable deployment settings because they are safety invariants for this endpoint.

## Error Handling

- Invalid request shape or a disallowed destination: validation response; frontend keeps the URL.
- DNS, TLS, connection, timeout, redirect, decoding, or upstream HTTP failure: `{ "title": null }`.
- Non-HTML response or missing/empty `<title>`: `{ "title": null }`.
- Frontend cancellation during navigation or component unmount: no user-visible error.

No credentials, URL contents, upstream response body, or low-level exception details are logged or returned. In particular, query strings are not placed in route paths or server-generated error messages.

## Testing

Backend tests cover:

- title extraction, entity decoding, whitespace normalization, and length limiting;
- missing titles and non-HTML responses;
- rejection of non-HTTP schemes, credential-bearing URLs, localhost, and every non-global IP class;
- redirect revalidation and public-to-private redirect rejection;
- timeout, response-size, redirect-count, and upstream-error fallback behavior;
- the authenticated endpoint response contract without contacting the internet.

Frontend tests cover:

- preservation of ordinary position text;
- replacement of a URL label with the returned title;
- raw-URL fallback for null and failed responses;
- multiple links and surrounding punctuation;
- `target="_blank"` and `rel="noopener noreferrer"`;
- use of the same renderer on the new-order and existing-order tables.

All tests use mocked/local transports. Project checks must not contact arbitrary external pages.

## Acceptance Criteria

1. A public HTML URL entered as a new-order position initially appears as a link and then displays its `<title>` when available.
2. The same behavior appears for positions in an existing order.
3. Clicking the displayed title opens the original URL in a new tab.
4. A failed or unavailable title lookup leaves the original URL visible and clickable without an error toast.
5. Ordinary non-link position text is unchanged.
6. Duplicate exact URLs are looked up no more than once per loaded browser session.
7. Private/local destinations and redirects to them are rejected without making a connection to the rejected address.
8. Backend and frontend checks pass without making live third-party network requests.

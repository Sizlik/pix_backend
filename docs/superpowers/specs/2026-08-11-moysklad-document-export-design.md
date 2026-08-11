# MoySklad Document Export Design

## Goal

Restore reliable PDF downloads for customer orders, purchase orders, and outgoing invoices while keeping the existing authenticated Pix API endpoints unchanged.

The implementation must follow the current MoySklad JSON API contract, must never return a MoySklad JSON error as a PDF, and must trigger a browser download without relying on a popup window.

## Current behavior and root cause

The three export managers fetch the first embedded MoySklad template and call the shared `MoySkladRepository.export` method. That repository method uses the `link` keyword both to build the request URL and as part of the JSON body. The resulting payload contains an undocumented field:

```json
{
  "link": "<document-id>/export",
  "template": { "...": "..." },
  "extension": "pdf"
}
```

MoySklad's documented request body contains only `template` and `extension`. MoySklad responds to a successful print request with HTTP 303 and a `Location` header that points to the temporary generated file. The official Java SDK likewise models only `template`, `templates`, and `extension`, follows the export response to the file, and rejects non-successful responses before saving bytes.

The current Pix repository returns `response.content` without checking the upstream status or final media. A stricter MoySklad validation error is therefore returned by Pix with `application/pdf`, hiding the real integration failure. On the frontend, the response is always wrapped as a PDF and assigned to a popup opened after the asynchronous request. Popup blocking can make `window.open()` return `null`, which produces an additional browser error and is not a true download flow.

Authoritative references:

- [MoySklad document printing contract](https://github.com/moysklad/api-remap-1.2-doc/blob/pre_release/md/documents/_print.md)
- [MoySklad official SDK export endpoint](https://github.com/moysklad/java-remap-1.2-sdk/blob/master/src/main/java/ru/moysklad/remap_1_2/clients/endpoints/ExportEndpoint.java)
- [MoySklad official SDK export request model](https://github.com/moysklad/java-remap-1.2-sdk/blob/master/src/main/java/ru/moysklad/remap_1_2/entities/ExportRequest.java)

## Chosen approach

Repair the complete existing proxy flow rather than exposing MoySklad's temporary URL to the browser.

The backend will construct a contract-accurate request, follow the documented redirect with bounded network timeouts, verify the final response, and proxy verified PDF bytes through the existing endpoints. The frontend will save the returned blob with an anchor download and revoke its object URL after use.

This keeps MoySklad credentials and temporary download URLs server-side, avoids CORS dependencies, preserves the current frontend API contract, and fixes both the integration error and popup failure.

## Backend design

### Repository boundary

`MoySkladRepository.export` will receive the export path separately from the request payload. Its interface will make it impossible for URL-only data to be serialized accidentally.

For a single PDF export it will:

1. POST to `entity/{type}/{document-id}/export` using a JSON body containing exactly `template` and `extension`.
2. Allow the HTTP client to follow MoySklad's documented 303 redirect to the temporary file.
3. Apply bounded connect/read timeouts to both the export request and redirected download.
4. Reject upstream non-2xx responses with the existing HTTP client error mechanism.
5. Require non-empty PDF content with a valid PDF signature before returning bytes.

The current MoySklad documentation mentions a possible HTTP 202 status but does not define a stable polling response contract and says that mode will be implemented later. The implementation will not invent an undocumented polling protocol. A 202 response without final PDF bytes will fail validation as a controlled upstream export error, with its status and safe response metadata logged for diagnosis.

### Manager and route behavior

The customer-order, purchase-order, and outgoing-invoice managers will continue selecting the first embedded template and requesting PDF output. Their externally visible behavior and endpoint paths remain unchanged.

The routes will return verified bytes with:

- `Content-Type: application/pdf`;
- `Content-Disposition: attachment` and a deterministic ASCII filename: `customer-order-<id>.pdf`, `purchase-order-<id>.pdf`, or `invoice-out-<id>.pdf`.

MoySklad HTTP failures, timeouts, missing redirects, empty bodies, and non-PDF responses will be mapped to a safe HTTP 502 response. The client will receive a stable message that document generation failed; credentials, upstream bodies, and temporary URLs will not be exposed. Logs may include the document type, upstream status, and failure category, but not authorization data or the temporary file URL.

No request in unit or application tests will contact a real MoySklad account.

## Frontend design

`ExportEndpoint` will remain an authenticated blob request to the existing Pix endpoint.

A focused download helper will:

1. create an object URL from the received PDF blob;
2. create a temporary anchor whose `download` value uses the same endpoint-specific `<document-type>-<id>.pdf` convention;
3. click and remove the anchor;
4. revoke the object URL after the browser has consumed it.

Both document lists on the order page will use the same helper. The asynchronous `window.open()` path and non-null assertion will be removed. A failed request will use the page's existing user-facing error mechanism and will not create or download a fake PDF.

## Data flow

1. The authenticated user selects a document on the order page.
2. The frontend requests the existing Pix export endpoint with `responseType: "blob"`.
3. The route asks the appropriate manager for the PDF.
4. The manager obtains an embedded template and supplies the document ID, template, and `pdf` extension to the repository.
5. The repository sends the exact MoySklad export body and follows the documented redirect.
6. The repository validates the successful final PDF and returns its bytes.
7. Pix responds with attachment headers.
8. The frontend downloads the blob and releases the object URL.

Any failure before step 6 becomes a normal error response rather than PDF bytes.

## Error behavior

| Condition | Pix result | Browser result |
| --- | --- | --- |
| MoySklad returns the documented redirect and valid PDF | 200 PDF attachment | File downloads |
| MoySklad returns 4xx or 5xx | 502 safe integration error | Error shown; no file |
| MoySklad times out or the redirect cannot be downloaded | 502 safe integration error | Error shown; retry remains possible |
| MoySklad returns 202 without final PDF bytes | 502 safe integration error and diagnostic log | Error shown; no empty file |
| MoySklad returns empty or non-PDF content | 502 safe integration error | Error shown; no fake PDF |
| Browser blocks popups | Not applicable | Download still works because no popup is used |

## Alternatives considered

### Backend-only payload correction

Removing `link` from the JSON would address the likely new MoySklad validation failure, but it would retain silent error-to-PDF conversion and the popup-dependent frontend. It is too narrow for a reliable document-download fix.

### Return the MoySklad temporary URL to the frontend

This reduces proxy work but exposes a short-lived, unauthenticated file URL, depends on browser access to another origin, and changes the Pix response contract. The server-side proxy is safer and more stable.

### Implement speculative HTTP 202 polling

The current printing documentation does not define the polling state payload or terminal transitions. Implementing assumptions now could hang requests or fetch an unintended URL. The design instead fails 202 safely and records enough metadata to add polling when MoySklad publishes a complete contract.

## Testing and verification

Backend tests will prove:

- the export URL contains the document path while the JSON body contains only `template` and `extension`;
- a documented redirect ending in a valid PDF returns the file bytes;
- non-2xx, timeout, 202, empty, and non-PDF responses are rejected;
- all three route variants return PDF attachment headers on success;
- upstream failures are mapped to a safe error response without leaking the MoySklad response body or URL.

Frontend tests will prove:

- the export API is requested as a blob;
- the common helper creates an anchor download with the expected filename;
- the helper removes the anchor and revokes the object URL;
- both order-page document actions use the helper;
- a failed export does not call the download helper and produces visible error feedback.

After the final edits, run `scripts/check.ps1` in the backend and `npm.cmd run check` in the frontend because both sides of the existing export contract are affected. Preserve all pre-existing generated-bytecode changes in the backend worktree and do not contact production integrations during verification.

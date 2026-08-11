# Order Creation Idempotency Design

## Goal

Prevent one logical checkout attempt from creating duplicate MoySklad products or customer orders, including when two requests arrive concurrently or a client retries after an uncertain network result. A later intentional checkout with the same address and items must still create a new order.

Reject checkout requests that contain no valid order positions.

## Current behavior and root cause

The frontend has an in-component `submittingRef` guard, but `POST /api_v1/orders` has no server-side identity for a checkout attempt. Every accepted request independently creates MoySklad products, creates a customer order, marks the address as used, and sends a notification. Parallel or retried HTTP requests can therefore create duplicate external entities.

`CheckoutOrderCreate.order_items` is currently an unconstrained list, so an empty array reaches the order-creation use case and can produce an empty customer order.

## Chosen approach

Use one client-generated idempotency key per logical checkout attempt, Redis coordination in the backend, and deterministic MoySklad `syncId` values as an external safety net.

MoySklad documents `syncId` specifically for retry-safe entity creation: a repeated create request with the same `syncId` returns the existing entity rather than creating another one. See [MoySklad JSON API 1.2: Назначение поля syncId](https://dev.moysklad.ru/doc/api/remap/1.2/#obschie-svedeniq-naznachenie-polq-syncid).

This approach avoids a database migration while covering multiple backend workers, concurrent requests, process interruption, and an uncertain external response.

## API contract

`POST /api_v1/orders` requires an `Idempotency-Key` header containing a UUID.

The key identifies an attempt, not the cart contents:

- retries of the same attempt reuse the same key;
- changing the address or any order item starts a new attempt with a new key;
- after a successful checkout, the key is discarded;
- a later intentional order always uses a new key, even when its contents are identical.

The backend scopes the key to the authenticated user. It also computes a SHA-256 fingerprint from a canonical representation of `address_id` and the ordered `order_items` fields (`link`, `count`, and `comment`). Reusing a key with a different fingerprint returns HTTP 409 with:

```json
{
  "detail": {
    "code": "idempotency_key_reused",
    "message": "Idempotency key was already used for another order"
  }
}
```

If the original request is still running, a duplicate waits for a bounded interval. If it is still incomplete when that interval expires, the backend returns HTTP 409 with code `order_creation_in_progress`. Retrying with the same key is safe and eventually returns the original order.

If Redis coordination is unavailable, the backend returns HTTP 503 before creating products or an order. The frontend retains the cart and idempotency key so the same attempt can be retried.

## Checkout validation

Checkout-specific request validation requires:

- at least one `order_items` entry;
- a non-blank `link` after trimming whitespace;
- `count` greater than zero.

Invalid payloads return FastAPI's HTTP 422 response before the order-creation manager or any external integration is called. The validation is scoped to checkout so unrelated legacy integration contracts do not change accidentally.

## Frontend attempt lifecycle

The new-order page derives a canonical fingerprint from the selected address and submitted item data. A small checkout-attempt helper stores `{ key, fingerprint }` in browser storage.

When submitting:

1. Reuse the stored key if its fingerprint matches the current payload.
2. Otherwise generate a new UUID with `crypto.randomUUID()` and store it with the new fingerprint.
3. Send it as `Idempotency-Key` through `CreateOrder`.
4. On success, clear both the cart and checkout-attempt record.
5. On any failure, keep both so a retry or page reload uses the same key.

The existing `submittingRef` and disabled button remain as immediate UI feedback, but correctness does not depend on them.

## Backend components and data flow

### Route

The orders route validates the UUID header and passes it to `OrderCreationManager.create`. Transport-specific validation and HTTP error mapping remain in the route layer.

### Idempotency coordinator

A Redis-backed coordinator is injected into `OrderCreationManager`. Its records are scoped by authenticated user ID and idempotency key and contain the request fingerprint, processing state, and completed order response.

The coordinator provides three outcomes:

- `acquired`: this request owns the attempt and may execute the workflow;
- `completed`: return the cached order without external calls or secondary effects;
- `conflict`: the key belongs to a different fingerprint.

Processing ownership uses a bounded Redis lease so a crashed worker cannot leave the attempt permanently stuck. Completed results remain cached for 24 hours, which covers browser retries and reloads without unbounded Redis growth.

### MoySklad identities

The backend never sends the raw client key as a global MoySklad identity. It derives UUIDv5 values from a fixed application namespace plus the authenticated user ID and idempotency key:

- one `syncId` for the customer order;
- one `syncId` for each generated product, additionally namespaced by its stable item index.

The same attempt therefore produces the same external identities, while the same client key used by another user cannot expose or reuse the first user's order.

The product and customer-order creation payloads include these `syncId` values. If a worker stops after MoySklad creates an entity but before Redis stores completion, a later retry repeats the create calls with the same identities and receives the existing entities.

### Completion and secondary effects

After MoySklad returns the customer order, the owning request stores the completed response in Redis before performing best-effort address preference and Telegram notification work. Duplicate requests then return the stored response and do not repeat these secondary effects.

Address marking and notification retain their existing non-fatal behavior. A failure in either does not turn an externally created order into a retryable checkout failure.

## Failure behavior

| Condition | Result |
| --- | --- |
| Empty or invalid positions | 422; no manager or external calls |
| Missing or malformed idempotency key | 422; no manager or external calls |
| Same user, key, and fingerprint after completion | Return the original order |
| Same user and key with a different fingerprint | 409 `idempotency_key_reused` |
| Same attempt still processing beyond the wait limit | 409 `order_creation_in_progress` |
| Redis unavailable before ownership is acquired | 503; no external calls |
| MoySklad fails before an order exists | Preserve retryable attempt; retry with the same key |
| Worker stops after a MoySklad create | Lease expires; retry resumes with the same MoySklad `syncId` values |
| Address preference or Telegram notification fails | Return the created order; log the secondary failure |

## Alternatives considered

### Redis payload fingerprint without a client key

Hashing user, address, and items for a short time window requires no frontend contract change, but it can merge two intentional identical orders made close together. Its correctness also depends on an arbitrary time window, so it does not match the agreed semantics.

### PostgreSQL idempotency table

A durable local table provides longer retention and auditability, but requires a model and reviewed Alembic migration. MoySklad `syncId` is still needed to close the transaction gap between external creation and the local commit. This extra persistence is not justified for the current duplicate-submit problem.

### MoySklad `syncId` without Redis coordination

This prevents duplicate external entities but lets concurrent requests repeat notification and address side effects. It also cannot reject a reused key with a changed payload cleanly. Redis adds the needed single-owner and response-replay behavior.

## Testing and verification

Backend tests will prove:

- checkout schema and API reject an empty list, blank link, and non-positive count;
- the route rejects a missing or malformed UUID header and passes a valid key to the manager;
- concurrent calls for the same user, key, and fingerprint execute the external workflow once and return the same order;
- a completed retry makes no product, order, address-mark, or notification call;
- the same key with another payload returns the explicit conflict;
- different keys create separate orders even for identical payloads;
- derived product and customer-order `syncId` values are stable for a retry, distinct per position, different across attempts and users, and present in MoySklad payloads;
- Redis failure happens before external changes;
- a resumed attempt after lease loss remains externally idempotent.

Frontend tests will prove:

- the attempt helper reuses a key for an unchanged failed checkout;
- it creates a new key when the address or item data changes;
- a successful checkout clears the stored attempt;
- `CreateOrder` sends the header supplied by the page.

After the final edits, run the backend `scripts/check.ps1` and the frontend `npm.cmd run check` because the request contract changes in both repositories.

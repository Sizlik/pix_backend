# Order Currency Display Design

## Goal

Display every customer-order amount on the site in the same currency as the
corresponding MoySklad customer order. The UI must show an unambiguous ISO 4217
code, for example `1 250,00 USD`, without converting the amount.

## Scope

The change covers:

- the total amount in the authenticated user's order list;
- the total amount in the organization order list;
- the unit price and line total for every position on the order detail page;
- order detail data returned after a successful customer edit.

The change does not alter order creation, order editing, payment and transaction
amounts, account balances, exchange-rate calculations, exported MoySklad
documents, or the currency configured in MoySklad.

## Source of Truth

MoySklad remains the source of truth for both the numeric order amounts and the
document currency. A customer order exposes its currency through
`rate.currency`. The backend requests that related currency with `expand` and
extracts the currency entity's `isoCode`.

No currency conversion is performed. Existing MoySklad monetary integer values
continue to be converted to display units by dividing by 100.

## Backend Design

`CustomerOrderManager` continues to own MoySklad customer-order retrieval. Its
single-order and order-list queries will expand `rate.currency` in addition to
their existing expansions.

Before a customer order leaves the manager boundary, the manager adds one
application-owned field:

```json
{
  "currency_code": "USD"
}
```

The field is derived only from `order.rate.currency.isoCode`. It is optional in
the response so an incomplete upstream payload does not turn an otherwise
readable order into a server error. The manager does not expose a second
currency lookup endpoint and does not make one request per order.

All paths that obtain customer orders through `get_order_by_id` or
`get_orders_by_user` receive the same enrichment. This includes personal order
routes, organization order routes, and the updated order returned after a
successful edit.

The existing raw MoySklad response fields remain unchanged to avoid breaking
current consumers.

## Frontend Design

The order API types gain an optional `currency_code` field. Order grid row types
carry that code beside their numeric amounts.

A small pure money-formatting helper accepts an amount in display units and an
optional ISO code. With a valid code it produces a Russian-locale value with two
decimal places and the ISO code, such as `1 250,00 USD`. If the code is absent or
invalid, it returns the formatted number without inventing a currency.

The helper is used by:

- the total column in `/dashboard/orders`;
- the amount columns in `/dashboard/organization`;
- the unit-price and line-total columns in `/dashboard/orders/[id]`.

The order detail page stores the current order currency alongside its other
order state. The same code is used for every position because MoySklad defines
the currency at the document level. Newly staged zero-price positions use that
same display currency.

## Data Flow

1. The browser requests an order or order list from the FastAPI API.
2. `CustomerOrderManager` requests the MoySklad customer order with
   `rate.currency` expanded.
3. The manager reads `rate.currency.isoCode` and adds `currency_code` to the
   returned order.
4. The route preserves its current response shape and returns the enriched
   order.
5. The frontend converts MoySklad monetary values from hundredths and formats
   them with the order's ISO code.

## Error Handling

- A missing `rate`, `currency`, or `isoCode` does not fail the order request.
- The backend omits or sets no `currency_code` when the upstream currency is
  incomplete.
- The frontend displays the localized numeric amount without a currency code in
  that case.
- The frontend never assumes RUB, USD, or another fallback currency.
- Existing MoySklad request errors retain their current behavior.

## Testing

Backend unit tests will verify that:

- the order-list query requests `rate.currency` expansion;
- the single-order query requests `rate.currency` expansion;
- a valid expanded currency becomes `currency_code`;
- incomplete currency data leaves the order readable without a fabricated code.

Frontend unit tests will verify that:

- USD, EUR, PLN, and another valid ISO code format correctly;
- a missing or malformed code cannot throw and does not add a currency;
- order-position rows retain their numeric values while the page uses the
  document-level currency for presentation.

The final verification is the backend `scripts/check.ps1` and frontend
`npm.cmd run check`, followed by a focused browser smoke of an order list and
order detail containing at least two different currencies when test data is
available.

## Acceptance Criteria

- Two orders with different MoySklad currencies display different ISO codes on
  the site.
- The numeric total, unit price, and line total remain equal to the corresponding
  MoySklad values after conversion from hundredths.
- Personal and organization order lists use each row's own currency.
- The order detail uses its order's currency for all position prices and sums.
- Missing currency metadata never causes a page or API failure and never causes
  an incorrect currency label.

## Reference

- MoySklad JSON API 1.2 documents `rate.currency` on operations and supports
  replacing linked metadata with expanded objects through `expand`:
  <https://dev.moysklad.ru/doc/api/remap/1.2/>.

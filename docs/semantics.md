# ReplayLab v1 semantics

The implementation specification is normative. This is the shorter operational guide.

A session trades one instrument, `SIM`. Self-trading is allowed. A single owner
sequences admitted unique commands from 1 through signed int64 maximum. The next
sequence becomes null after exhaustion; cached retries remain available.

Prices and quantities are decimal strings in JSON, between 1 and 1,000,000,000.
IDs are case-sensitive ASCII `[A-Za-z0-9_-]{1,64}`. An order belongs to
`(client_id, order_id)` within a session. Once accepted, this identity is never
reusable, even after a fill or cancellation. A rejected new order reserves only
its request identity, not its order identity.

Buys consume the cheapest eligible asks; sells consume the highest eligible
bids. The resting limit sets the execution price. Equal-price orders execute in
acceptance-sequence order. A partially filled resting order keeps its position.
Incoming residuals join the tail. Cancellation removes the whole remaining
quantity and emits one `cancelled` event, with no trade.

Every accepted order maintains:

```
original_quantity = filled_quantity + cancelled_quantity + remaining_quantity
```

Business rejection precedence is instrument, reused order identity, then order
record capacity for new orders; instrument then active order for cancellation.
Business rejections consume a sequence and retain their original response.
Malformed inputs consume neither. Request lookup precedes request capacity and
sequence exhaustion. An identical retry returns the original sequence, result
and events with `duplicate: true`; a changed payload returns an unsequenced
`IDEMPOTENCY_CONFLICT`. Repeated event delivery is not repeated execution.

The default limits are 100,000 accepted lifecycle records, 200,000 unique requests
and 16,384 bytes per line excluding LF. The hard ceilings are 1,000,000 orders and
2,000,000 requests, with orders no greater than requests. No cache eviction occurs.
Memory retains the entire finite session, not just active orders.

The golden walkthrough finishes with an empty book, three order records, six
cached requests, next sequence 7, two unique trades totaling 12 units, and one
cancellation of 5 units. The two retry responses repeat those original events.

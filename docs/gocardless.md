# GoCardless Bank Account Data

How this project talks to the GoCardless Bank Account Data API (formerly
Nordigen), and how to inspect and repair the connections that feed `raw/`.

## Explanation

### Why connections are the source of truth

Which accounts exist, which bank each belongs to, and which are stale are all
answerable from the API. Do not mirror that into a document or a constant. The
first version of `renew_connections.py` hardcoded the two institutions that
happened to need renewing when it was written; a quarter later it silently
targeted the wrong banks while the one that had actually expired went unnoticed
for a day. Anything derived from the API should be re-derived, not remembered.

The identifiers themselves (account, agreement, requisition) are personal data.
Keep them out of tracked files, and query for them when you need them.

### What the pieces are

An **institution** is a bank. GoCardless acts as the regulated intermediary, so
access is granted through a chain of objects rather than directly:

- An **end-user agreement** (EUA) fixes the terms: how far back transactions may
  be read, how long access lasts, and whether it can be extended. It is inert on
  its own.
- A **requisition** links an agreement to an institution and produces the URL
  the end user visits to authorise. It is the object that carries accounts.
- An **account** is a bank account discovered through a linked requisition.
  Transaction endpoints are keyed by account ID.

Deleting a requisition also deletes its agreement, so the two are usually
managed together.

## Reference

### Use the client wrapper

`go_cardless_client.Client` is the interface for this project. It owns token
load, refresh, re-authentication, and the request headers, so nothing else
should reach for `requests` or hand-build a URL. Every script and skill here
goes through it.

```python
from go_cardless_client import Client

client = Client()          # authenticates, then fetches institutions
client.get("requisitions/")
client.post("agreements/enduser/", {...})
client.delete(f"requisitions/{requisition_id}/")
```

Construction performs real work: it loads `token.json`, refreshes or
re-authenticates as needed, and fetches the institution list. It raises if
authentication cannot be established, so a `Client()` that returns is a
connected one.

| Member | Behaviour |
|--------|-----------|
| `client.get(endpoint, params=None)` | Authenticated GET; returns parsed JSON |
| `client.post(endpoint, data)` | Authenticated POST; accepts `200` and `201` |
| `client.delete(endpoint)` | Authenticated DELETE; accepts `200` |
| `client.institutions` | Polars frame of GB institutions, fetched at construction |
| `client.token` | The loaded JWT pair, persisted to `token.json` |

All three verbs return `None` on any non-success response after logging the
status and body at `ERROR` level. The idiom is therefore `if not result:`, not a
try/except. A `None` is a real failure and should be reported, never swallowed.

`client.institutions` casts `transaction_total_days` and
`max_access_valid_for_days` to `Int32`, but **not**
`max_access_valid_for_days_reconfirmation`, which stays a string. Coerce it
yourself rather than assuming it is numeric.

### Underlying endpoints

These are what the wrapper calls. Reach for them only to understand a response
shape, or if the wrapper is genuinely missing something worth adding to it.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `institutions/?country=GB` | Bank list with capability fields |
| `POST` | `agreements/enduser/` | Create an agreement |
| `GET` | `agreements/enduser/{id}/` | Read one agreement |
| `DELETE` | `agreements/enduser/{id}/` | Delete an agreement |
| `GET` | `agreements/enduser/{id}/reconfirm/` | Read an existing reconfirmation |
| `POST` | `agreements/enduser/{id}/reconfirm/` | Create a reconfirmation; returns `reconfirmation_url` |
| `GET` | `requisitions/` | List requisitions with their accounts |
| `POST` | `requisitions/` | Create a requisition |
| `DELETE` | `requisitions/{id}/` | Delete a requisition *and its agreement* |
| `GET` | `accounts/{id}/transactions/` | Transactions for one account |

### Institution capability fields

Read these rather than assuming, because they differ per bank:

| Field | Meaning |
|-------|---------|
| `transaction_total_days` | Maximum history depth. `max_historical_days` must not exceed it, or the API returns `400` |
| `max_access_valid_for_days` | Longest access period without reconfirmation. `90` for GB banks |
| `max_access_valid_for_days_reconfirmation` | Longest access period *with* reconfirmation. `730` for GB banks |

### Requisition statuses

Stages run in order; `LN` and `EX` are the two that matter operationally.

| Short | Long | Meaning |
|-------|------|---------|
| `CR` | CREATED | Created, not yet authorised |
| `GC` | GIVING_CONSENT | End user on the GoCardless consent screen |
| `UA` | UNDERGOING_AUTHENTICATION | End user authenticating with their bank |
| `RJ` | REJECTED | Authentication failed |
| `SA` | SELECTING_ACCOUNTS | End user choosing accounts |
| `GA` | GRANTING_ACCESS | End user granting access |
| `LN` | LINKED | Authorised and carrying accounts |
| `EX` | EXPIRED | Access has lapsed; the agreement must be replaced |

### Agreement constraints

These are enforced by the API and are not obvious from the endpoint reference:

- `reconfirmation` may only be requested when `access_valid_for_days > 90`.
  At or below the SCA default the API returns `400 Reconfirmation is not allowed
  when access_valid_for_days <= 90 days.` The two fields have to be set together.
- Reconfirmation requires an agreement that the end user has already accepted.
  Otherwise the API returns `400 End user agreement needs to be accepted.`
- `GET .../reconfirm/` returns `404` until a reconfirmation has been created. A
  `404` there is normal and does not mean reconfirmation is unavailable.
- Account IDs survive re-authorisation. Remaking a connection returns the same
  account IDs, so `raw/` needs no remapping.

### Errors worth recognising

| Response | Meaning |
|----------|---------|
| `401 Invalid token` | Access token stale. `Client` refreshes on the next call, so this is expected once per day |
| `401 ... EUA ... has expired` | The agreement lapsed; the connection is dead until remade |
| `400 Reconfirmation is not allowed` | `access_valid_for_days` was not raised above 90 |
| `400 Reconfirmation is not enabled` | The agreement was created without the `reconfirmation` flag |
| `400 End user agreement needs to be accepted` | Trying to reconfirm before first authorisation |
| `403 Reconfirmation is not enabled for this company` | The GoCardless account itself lacks the feature; contact GoCardless |

## How-to

### Discover which accounts exist

The requisitions endpoint is the single answer to "what is connected". Every
account in `raw/` should appear here, and nothing here should be missing from
`raw/`.

```python
from go_cardless_client import Client

client = Client()
requisitions = client.get("requisitions/")["results"]

for req in requisitions:
    for account_id in req.get("accounts", []):
        print(account_id, req["institution_id"], req["status"])
```

To get institutions rather than accounts — for instance to ask "which banks are
in use" — collect the distinct `institution_id` values where `accounts` is
non-empty. A requisition with no accounts never carried data and is not in use.

### Find connections that need attention

```bash
uv run prune_connections.py            # report only
uv run renew_connections.py            # remake whatever has expired
```

`prune_connections.py` treats an institution's most recent linked requisition as
current and reports the rest. It never deletes a live or pending requisition, so
it is safe to run at any point, including before a replacement has been
authorised.

It also prints the current connection per institution with its reconfirmation
state and the date reconfirmation falls due, so one run answers both "what is
connected" and "is anything about to lapse":

```
3 connection(s) in use
  NATIONWIDE_NAIAGB21       LN  accounts=2  reconfirmable, access 730d  reconfirm by 2026-12-12 (89d)
```

An agreement created without the reconfirmation flag is labelled
`NOT reconfirmable`, which means the next renewal needs a full bank login rather
than a click. Anything inside the last fortnight before its due date is marked
`DUE SOON`.

To spot a dormant account, compare the newest file per account against the
newest overall:

```bash
for d in raw/*/; do printf '%s %s\n' "$(ls "$d" | tail -1)" "$(basename "$d")"; done | sort
```

An account whose latest file is months behind the others is dormant, not broken.
It will keep returning empty transaction sets, which is why `update_transactions.py`
reports it as downloading zero transactions.

### Renew an expired connection

An `EX` agreement cannot be revived; it is replaced.

```bash
uv run renew_connections.py --all --no-poll   # every bank in use
uv run renew_connections.py --no-poll         # only the expired ones
```

The script creates a reconfirmable agreement at the institution's maximum access
period, creates a requisition, and prints the authorisation URL as text and as a
terminal QR code. It writes nothing to disk.

Present the links to the user and stop. Authorisation is a hard pause: the
requisition stays `CR` until the user completes it in their bank. Poll with
`uv run renew_connections.py` (no flags) or re-query `requisitions/` to confirm
`LN` and non-empty `accounts`.

Once the replacement is `LN`, retire the old one:

```bash
uv run prune_connections.py --apply
```

Running that before the replacement links is harmless but pointless — the old
live connection is deliberately kept until the new one carries its accounts.

### Reconfirm without SCA

Reconfirmation is the UK mechanism that lets consent be renewed without the end
user repeating strong customer authentication. It still requires the user to
visit a URL; it is not headless. The API call is automatable, the consent is not,
because the FCA requires reconfirmation to come from the customer.

```python
result = client.post(f"agreements/enduser/{agreement_id}/reconfirm/", {})
print(result["reconfirmation_url"])   # hand this to the user
```

Reconfirmation falls due roughly every 90 days even though the agreement's
access period is longer, so treat 90 days from acceptance as the reminder date.

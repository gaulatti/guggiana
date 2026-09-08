# Lazy language renditions

Guggiana used to launch **all five** translation-and-synthesis workflows for
every inserted article, whether or not anyone ever asked for those languages.
Renditions are now materialized lazily: a locale is generated the first time it
is requested, and reused forever after.

This is engine-independent. It changes *how much* work is launched, not how
translation or speech synthesis is performed, and it does not touch the state
machine, the speech provider, or AWS Translate.

## Requesting locales

`get` accepts an explicit requested-locale input. **A single-locale request is
never expanded to every locale.**

| Input | Materializes |
| --- | --- |
| `{ "language": "en-US" }` | exactly `en-US` |
| `{ "languages": ["en-US", "es-US"] }` | exactly those two |
| `{ "language": "all" }` | every supported locale (the deliberate all-locales path) |
| neither field | every supported locale — the pre-existing contract, unchanged |

`languages` takes precedence when both are supplied. An unsupported code is
rejected with `Unsupported language: <code>` rather than silently dropped, so a
typo fails instead of quietly generating the wrong set. Language identifiers and
the `outputs` response shape are unchanged.

## How a rendition is materialized

1. `get` resolves the requested locales and either creates the content record
   carrying them (`requestedLocales`) or appends the newly requested ones to an
   existing record. The requested set only ever grows, so adding a locale never
   withdraws one another caller is waiting on.
2. That write reaches `trigger` as a DynamoDB stream event. `trigger` now
   handles both `INSERT` and `MODIFY`.
3. `trigger` computes the locales that are requested, **not** already in
   `outputs`, and **not** already claimed by a live execution. If that set is
   empty it returns without downloading the article — this is where the
   translation and synthesis cost is avoided.
4. For each remaining locale it takes an atomic claim and starts exactly one
   Step Functions execution.
5. `get` polls only for the locales it asked for.

## Concurrency, retry, and expiry

Each locale is claimed with a **single conditional DynamoDB write** on a flat
`rendition#<code>` attribute:

```
ConditionExpression:
  attribute_not_exists(#rendition)
  OR #rendition.#status = :failed
  OR #rendition.#claimedAt < :expiredBefore
```

- **Concurrency** — two callers racing the same locale both attempt the claim;
  exactly one wins and starts the execution, the other reuses it. Execution
  names remain `"<uuid>-<code>"`, so Step Functions rejects a duplicate as a
  second line of defence.
- **Retry** — a locale whose execution failed to start is set back to `failed`,
  which makes it immediately claimable again. Failure is isolated: one locale
  failing never aborts or retries the locales that did start.
- **Expiry** — a claim older than `RENDITION_CLAIM_EXPIRY_MS` (15 minutes) is
  treated as abandoned and may be re-claimed. That bounds the damage from a
  Lambda that dies between claiming a locale and starting its execution.
- **Succeeded** renditions are never re-claimed; the stored artifact is reused.

## Metrics

All dimensions are bounded and **no content identifier, URL, or locale code is
ever emitted** — only the request *class*.

| Metric | Dimensions | Meaning |
| --- | --- | --- |
| `guggiana_rendition_requested_locales` | `stage`, `locale_class` | how many locales one request asked for |
| `guggiana_rendition_locales_total` | `stage`, `locale_class`, `result` | per-locale outcome |

`locale_class` is `single`, `subset`, or `all`. `result` is:

| `result` | Meaning |
| --- | --- |
| `hit` | served from a stored artifact — translation and synthesis avoided |
| `reused` | a concurrent caller already owned the claim — duplicate work avoided |
| `miss` | an execution was actually started — the work paid for |
| `failed` | the execution could not be started; the locale is retryable |

`hit + reused` is the avoided cost; `miss` is the incurred cost. Comparing them
against the previous behaviour — five workflows per inserted article,
unconditionally — is how the saving is read.

## Backward compatibility

- Existing artifacts remain readable and are always preferred over regeneration.
- The `outputs` response still returns every stored locale, not only the
  requested ones.
- A request that names no language still waits for the full supported set.
- `checkLanguagesPresent` is retained for existing callers;
  `renditionsPresent` is its multi-locale form.

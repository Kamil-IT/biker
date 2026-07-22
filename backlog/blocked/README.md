# Blocked tasks

Tasks in this folder are **implemented but cannot be completed or verified** because of an external dependency that nobody on the project can satisfy right now — a credential, an account approval, a third-party verification.

They are not abandoned and not unstarted. Each has code written and a PR open. What is missing is the ability to prove the feature does what it claims.

**Do not pick these up from the normal backlog rotation.** Move a task back to `backlog/` only once its blocker is genuinely resolved.

## Currently blocked

| ID | Task | PR | Status |
|---|---|---|---|
| 008 | Allegro API | [#42](https://github.com/Kamil-IT/biker/pull/42) | 🟠 Draft — no creds |
| 009 | OLX API | [#43](https://github.com/Kamil-IT/biker/pull/43) | 🟠 Draft — no creds + OAuth bug |
| 010 | Amazon API | [#44](https://github.com/Kamil-IT/biker/pull/44) | 🟠 Draft — no creds |

## What "no creds" means here

`backend/.env` contains exactly one key: `ANTHROPIC_API_KEY`. There are no Allegro, OLX or Amazon credentials in this environment, so **the happy path on all three endpoints is unprovable by anyone here.** That is a fact about the environment, not a gap in effort.

Each PR carries verification evidence for everything that *can* be checked without credentials:

- graceful degradation — live calls returning HTTP 200 with `offers: []` and a meaningful `info`, never 502
- input validation — 422 on empty/missing `model`, never 500
- OAuth / SigV4 auth flow — verified under mock (token fetched once, reused, refreshed on expiry)
- the empty-result caching rule — verified by row count in the server's own `cache.db`

All three are well-behaved no-ops today: correct error handling, correct validation, correct caching, and dead code past the credential check. Merging them costs nothing and blocks nothing — but **none of them is a working integration**, and none should be described as one.

## To unblock

| ID | Needs |
|---|---|
| 008 | An Allegro developer app **plus application verification** — `GET /offers/listing` is restricted to verified applications. Set `ALLEGRO_CLIENT_ID` / `ALLEGRO_CLIENT_SECRET`. |
| 009 | OLX developer account approval (was pending). Set `OLX_CLIENT_ID` / `OLX_CLIENT_SECRET`. |
| 010 | An Amazon Associate account with PA-API 5.0 access. Set the access key, secret and partner tag. |

## Known defects to fix on first real use

Found during verification. None is blocking today because the code never reaches them without credentials — but each is a likely first-contact failure.

- **009 — OAuth credentials are posted as a JSON body.** Most client-credentials servers expect `application/x-www-form-urlencoded`, which is what 008 correctly does. The mock cannot catch this because it accepts whatever is sent. This is the single most likely first-contact failure.
- **009 — `OLX_ENV` is a no-op.** `_HOSTS` maps both `production` and `sandbox` to the same `www.olx.pl`.
- **008 and 009 — the listing title is discarded.** Both mappers set `brand`/`model` from the *request*, so every offer comes back identical regardless of what was actually listed. Worst on 009, where size/year/condition is exactly what distinguishes used listings. 010 does this correctly, using the item title — align the other two to it.
- **008 — `info` conflates two causes** ("credentials missing **or** token request failed"). The log distinguishes them; the API response does not.
- **010 — `Marketplace` is derived by string surgery** (`f"www.{host.replace('webservices.', '')}"`). Fine for the default, silently wrong for any other `AMAZON_HOST`. Also worth confirming `amazon.com` is intended at all, given the rest of the project targets Polish retailers.

## Note on the PR branches

Each of these PRs renames its task file to `backlog/DONE_00X_*.md` at the **old** path. Moving the files here will therefore conflict with that rename. Resolve in favour of this folder: the task is blocked, not done, so it should stay `TODO_` and stay here until its blocker clears.

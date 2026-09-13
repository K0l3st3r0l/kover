# Options regression checks

Use an isolated Python environment with `backend/requirements-dev.txt` installed.
From `backend/`:

```bash
DATABASE_URL=sqlite:///:memory: python -m pytest -q
```

The lifecycle and scanner/valuation tests create their own in-memory SQLite
databases. They mock market providers and never call the production API.
They cover partial closes, repeated closes, rolls, commissions, coverage,
expiration confirmation, imported contracts sharing strikes, stale scanner
candidates, historical premium totals and open-option liabilities.

From `frontend/`:

```bash
npm test
./node_modules/.bin/tsc --noEmit
```

On the shared VPS, validate the bundle without deploying it:

```bash
bash /root/apps/wiki/deploy-guard.sh run kover/frontend-validation -- npm run build -- --outDir /tmp/kover-options-build
```

Browser checks must intercept `/api/**` or use an isolated test backend.
Exercise both missing and zero BTC quotes, verify a roll sends POST `/roll`
with both commissions and never PUT, inspect a negative maximum payoff, and
confirm expired positions show pending settlement. Review desktop and mobile.

No schema changes are needed. Historical reconciliation and production rollout
are separate operations. The scanner replaces its derived ranking atomically;
quotes and runs older than 24 hours are excluded, including over weekends.

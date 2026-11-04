# Railway configuration

[`railway.ts`](railway.ts) describes the hosted API service and its data volume with
Railway [Infrastructure as Code](https://docs.railway.com/infrastructure-as-code).
Variables are unmanaged: secrets and settings stay in Railway and never enter this file.

The file exports the named partial `voice-delegate-api`, so an apply manages only the
resources declared here. That keeps an accidental omission from deleting anything else
in the Railway environment.

The CLI evaluates the file with the `railway` SDK, installed here rather than in the
repository root or `frontend/`:

```sh
cd .railway && npm ci --ignore-scripts && cd ..
railway config plan    # read-only
railway config apply   # previews again and asks for confirmation
```

Never apply a plan that detaches the `/app/.local` volume or deletes a resource: that
volume holds the quota, feedback and debug stores. A plan after a successful apply
should show no changes.

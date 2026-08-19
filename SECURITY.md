# Security

## What there is to attack

Not much, and that is deliberate. The project holds no user accounts, no authentication and no
personal data beyond the job applications you type into it yourself. The only credential anywhere is
a MongoDB connection string, which is read from `.env` at the repo root. That file is gitignored, no
template carries a real value, and Compose passes it in as an environment variable rather than
copying it into an image — so a built image holds no credentials either.

If you run this yourself, the connection string is the whole of your exposure. Keep it out of
tracked files and out of screenshots.

## Reporting something

Open an issue. There is no private disclosure channel and no bounty, and given the above there is
nothing worth embargoing — a public issue is the fastest way to get it fixed. If you do find
something that would genuinely be worse for being public, say so in a one-line issue with no detail
and it can move to email from there.

Only `main` is supported. There are no released versions and no backports.

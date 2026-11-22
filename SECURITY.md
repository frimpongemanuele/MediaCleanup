# Safety and privacy

- Preview is the default. It builds an in-memory filesystem plan without modifying media. Check the full operation list and back up important files before applying.
- Use `--plan-out` followed by `--apply-plan` to apply the exact preview. Saved plans contain absolute paths and filesystem identities; keep them private and outside the selected media folder. They are intended for the same filesystem, not transfer to another machine.
- The selected media folder bounds operations. Links, junctions and reparse points are not followed. In single-folder mode the selected folder may be renamed alongside its original location.
- Apply checks original source identities, rejects existing destinations and writes a durable operation journal. Use `--rollback JOURNAL` with the original root and the same single-folder mode to reverse confirmed operations. Rollback never removes nonempty directories. If a process was interrupted during an individual operation, the journal may be ambiguous; the tool stops rather than guessing. Inspect the journal and media manually in this case.
- Do not run against a library being modified concurrently. Filesystem checks reduce risk but do not make the sequence transactional or immune to concurrent changes. Keep an independent backup.
- TMDb credentials are read from `TMDB_API_KEY`. Never commit credentials or include them in logs, examples or screenshots. API failures report their exception type, not raw request URLs. Even preview may query TMDb using inferred titles; omit the key for local-only planning. Applying a saved plan or rolling back does not perform metadata lookups.
- The historical `movie_cleanup_V1.py` script is retained for reference; use the modern CLI for saved plans and journals.

## Reporting a security issue

If you find a vulnerability or a failure that could cause data loss, do not include real media, credentials or unredacted pathnames in a public issue. Use [GitHub's private vulnerability reporting](https://github.com/frimpongemanuele/MediaCleanup/security/advisories/new) if available, or contact the maintainer privately. Share a minimal synthetic reproduction, relevant platform details and the impact of the issue.

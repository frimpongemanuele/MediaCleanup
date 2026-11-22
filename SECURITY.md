# Safety and privacy

- Preview is the default. Use `--apply` only after checking the output and backing up important files.
- The selected media folder bounds filesystem operations. Links, junctions and other reparse points are not followed; existing destinations are not overwritten by the checked rename operation. In single-folder mode, the selected folder itself may be renamed alongside its original location.
- Do not run against a library being modified concurrently. Filesystem checks reduce risk but do not make the rename sequence transactional or immune to concurrent changes.
- TMDb credentials are read from the `TMDB_API_KEY` environment variable. Never commit credentials or include them in logs, examples or screenshots. API errors report their exception type rather than raw request URLs.
- If a TMDb key is configured, even a preview may query TMDb using titles inferred from media names. Omit the key if you want local-only processing.
- Test new or unfamiliar library layouts using synthetic or copied files before applying changes to the original. Operation rollback is not implemented yet.

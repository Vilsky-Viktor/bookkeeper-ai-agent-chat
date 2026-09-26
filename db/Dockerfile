# The production migration runner (the `migrate` Cloud Run Job): dbmate plus this
# repo's migrations. Locally, the `migrate` Compose service mounts ./db instead.
FROM ghcr.io/amacneil/dbmate:2.36.0
COPY migrate.sh /db/migrate.sh
COPY migrations /db/migrations
ENTRYPOINT ["/bin/sh", "/db/migrate.sh"]

FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g firebase-tools \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /emulator
COPY firebase.json firestore.rules ./
# Accounts and Firestore data live in /emulator/state/export (the parent folder is
# bind-mounted by docker-compose.yml): imported on start when an export exists,
# written back on shutdown. The export target must not be the mount point itself —
# the emulator replaces the folder, and a mount point can't be removed (EBUSY).
# `exec` makes firebase PID 1 so `docker stop`'s SIGTERM reaches it and triggers
# that export.
CMD ["sh", "-c", "IMPORT=; [ -f /emulator/state/export/firebase-export-metadata.json ] && IMPORT=--import=/emulator/state/export; exec firebase emulators:start --only auth,firestore --project demo-bookkeeping $IMPORT --export-on-exit=/emulator/state/export"]

FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g firebase-tools \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /emulator
COPY firebase.json firestore.rules ./
CMD ["firebase", "emulators:start", "--only", "auth,firestore", "--project", "demo-bookkeeping"]

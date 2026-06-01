FROM python:3.10-slim

# Runtime dependencies: libpq5 for psycopg2-binary, curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 libexpat1 curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching. Plugin requirements files are
# discovered and installed AFTER core, with core requirements.txt passed as a
# pip --constraint so a plugin cannot upgrade/downgrade a shared dep version.
# A plugin missing its requirements.txt is fine — the loader will skip-mount
# that plugin gracefully when its required_packages are not importable.
COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/plugins/ /app/backend/plugins/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt && \
    for req in /app/backend/plugins/*/requirements.txt; do \
        [ -f "$req" ] || continue; \
        echo "Installing plugin deps: $req"; \
        pip install --no-cache-dir \
            --constraint /app/backend/requirements.txt \
            -r "$req"; \
    done

# Copy application code
# Must be at repo root because app.py references ../frontend/templates and ../static
COPY AnonyBiome/ /app/AnonyBiome/
COPY PBKFAIRModel/ /app/PBKFAIRModel/
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY static/ /app/static/

# Entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Working directory matches the dev setup (run.sh runs from backend/)
WORKDIR /app/backend

# PYTHONPATH=/app mirrors run.sh: export PYTHONPATH=$(pwd)/..
# This makes "from AnonyBiome.anonymization..." resolve correctly
ENV PYTHONPATH=/app

# Create uploads directory
RUN mkdir -p /app/backend/uploads

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["flask", "run", "--host", "0.0.0.0"]

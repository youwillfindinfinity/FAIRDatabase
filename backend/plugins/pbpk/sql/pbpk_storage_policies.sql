-- backend/pbpk_storage_policies.sql
-- One-shot RLS for the `pbpk-artifacts` Supabase Storage bucket. Apply ONCE,
-- by hand, against the Supabase project DB:
--
--     PGPASSWORD=$POSTGRES_SECRET psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
--         -U $POSTGRES_USER -d $POSTGRES_DB_NAME \
--         -f backend/pbpk_storage_policies.sql
--
-- NOT applied from docker-entrypoint.sh or Flask boot:
--   * `storage.objects` is owned by supabase_storage_admin; whether your
--     `POSTGRES_USER` can ALTER it depends on the deployment. Failing the
--     boot loop on a tightened deployment would be worse than asking an
--     operator to run this once.
--   * Concurrent DDL across multiple gunicorn workers would race.
--
-- Until this file is applied, the bucket is reachable only via the service-
-- role client (i.e. the Flask backend), which is fine for the PoC because
-- every read goes through `/model/runs/<id>/artifacts` and the backend issues
-- short-lived signed URLs. Apply this when you want browsers to read objects
-- directly without going through Flask.
--
-- Idempotent: DROP-then-CREATE.

-- ---------------------------------------------------------------------------
-- Helper: extract storage_path from a storage.objects row and join back to
-- the catalog. storage.objects.bucket_id + name reconstructs the canonical
-- "<bucket>/<key>" we record in _fd.pbpk_run_artifacts.storage_path.
-- ---------------------------------------------------------------------------

DROP POLICY IF EXISTS pbpk_artifacts_storage_select ON storage.objects;
CREATE POLICY pbpk_artifacts_storage_select ON storage.objects FOR SELECT
    USING (
        bucket_id = 'pbpk-artifacts'
        AND (
            _fd.current_role() = 'admin'
            OR EXISTS (
                SELECT 1 FROM _fd.pbpk_run_artifacts a
                 WHERE a.storage_path = 'pbpk-artifacts/' || storage.objects.name
                   AND a.owner_id = auth.uid()
            )
        )
    );

DROP POLICY IF EXISTS pbpk_artifacts_storage_insert ON storage.objects;
CREATE POLICY pbpk_artifacts_storage_insert ON storage.objects FOR INSERT
    WITH CHECK (
        bucket_id = 'pbpk-artifacts'
        AND _fd.current_role() IN ('admin', 'curator')
        AND auth.uid() IS NOT NULL
    );

DROP POLICY IF EXISTS pbpk_artifacts_storage_update ON storage.objects;
CREATE POLICY pbpk_artifacts_storage_update ON storage.objects FOR UPDATE
    USING (
        bucket_id = 'pbpk-artifacts'
        AND (
            _fd.current_role() = 'admin'
            OR EXISTS (
                SELECT 1 FROM _fd.pbpk_run_artifacts a
                 WHERE a.storage_path = 'pbpk-artifacts/' || storage.objects.name
                   AND a.owner_id = auth.uid()
            )
        )
    );

DROP POLICY IF EXISTS pbpk_artifacts_storage_delete ON storage.objects;
CREATE POLICY pbpk_artifacts_storage_delete ON storage.objects FOR DELETE
    USING (
        bucket_id = 'pbpk-artifacts'
        AND (
            _fd.current_role() = 'admin'
            OR EXISTS (
                SELECT 1 FROM _fd.pbpk_run_artifacts a
                 WHERE a.storage_path = 'pbpk-artifacts/' || storage.objects.name
                   AND a.owner_id = auth.uid()
            )
        )
    );

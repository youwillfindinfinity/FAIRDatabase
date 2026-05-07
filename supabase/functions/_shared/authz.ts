// Shared authorization helpers for FAIRDatabase edge functions.
//
// The Supabase platform already verifies JWTs when `FUNCTIONS_VERIFY_JWT=true`,
// so we only need to *parse* the bearer token to learn who the caller is and
// then enforce per-resource authorization (owner / grant / admin).

// @ts-ignore  Deno standard postgres client
import * as postgres from 'https://deno.land/x/postgres@v0.17.0/mod.ts'

export interface CallerIdentity {
  userId: string | null
  jwtRole: string | null   // "service_role" | "authenticated" | "anon" | ...
  isService: boolean
}

export function parseCaller(req: Request): CallerIdentity {
  const auth = req.headers.get('Authorization') || ''
  const m = auth.match(/^Bearer\s+(.+)$/i)
  if (!m) return { userId: null, jwtRole: null, isService: false }

  const parts = m[1].split('.')
  if (parts.length !== 3) return { userId: null, jwtRole: null, isService: false }

  try {
    let payload = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    while (payload.length % 4) payload += '='
    const json = JSON.parse(atob(payload))
    const jwtRole = (json.role as string | undefined) ?? null
    return {
      userId: (json.sub as string | undefined) ?? null,
      jwtRole,
      isService: jwtRole === 'service_role',
    }
  } catch {
    return { userId: null, jwtRole: null, isService: false }
  }
}

// Look up the FAIRDatabase application role (admin/curator/...) for a user.
export async function lookupAppRole(
  // @ts-ignore  poolclient is loosely typed across versions
  conn: any,
  userId: string,
): Promise<string | null> {
  const r = await conn.queryObject(
    `SELECT role::text AS role FROM _fd.user_roles WHERE user_id = $1`,
    [userId],
  )
  return (r.rows[0]?.role as string | undefined) ?? null
}

// Return the set of `metadata_tables.table_name` values the user can read.
// Service-role callers see everything.
export async function readableTableNames(
  // @ts-ignore
  conn: any,
  caller: CallerIdentity,
): Promise<Set<string> | null> {
  if (caller.isService) return null  // null = unrestricted
  if (!caller.userId) return new Set()

  const role = await lookupAppRole(conn, caller.userId)
  if (role === 'admin') return null

  const r = await conn.queryObject(
    `SELECT DISTINCT m.table_name
       FROM _fd.metadata_tables m
       LEFT JOIN _fd.dataset_grants g ON g.dataset_id = m.id
      WHERE m.owner_id = $1 OR g.user_id = $1`,
    [caller.userId],
  )
  return new Set(r.rows.map((row: any) => row.table_name as string))
}

// Returns true iff the caller is allowed to read the named dataset table.
export async function canReadTable(
  // @ts-ignore
  conn: any,
  caller: CallerIdentity,
  tableName: string,
): Promise<boolean> {
  if (caller.isService) return true
  if (!caller.userId) return false

  const role = await lookupAppRole(conn, caller.userId)
  if (role === 'admin') return true

  const r = await conn.queryObject(
    `SELECT 1
       FROM _fd.metadata_tables m
       LEFT JOIN _fd.dataset_grants g
              ON g.dataset_id = m.id AND g.user_id = $1
      WHERE m.table_name = $2
        AND (m.owner_id = $1 OR g.user_id = $1)
      LIMIT 1`,
    [caller.userId, tableName],
  )
  return r.rows.length > 0
}

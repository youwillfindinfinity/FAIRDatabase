// Edge Function to get dataset statistics for visualization
// @ts-ignore
import * as postgres from 'https://deno.land/x/postgres@v0.17.0/mod.ts'
import { parseCaller, readableTableNames } from '../_shared/authz.ts'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

export default async function handler(req: Request): Promise<Response> {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  const caller = parseCaller(req)
  if (!caller.userId && !caller.isService) {
    return new Response(
      JSON.stringify({ success: false, error: 'Unauthorized' }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' }, status: 401 },
    )
  }

  try {
    // Connect to PostgreSQL directly
    const databaseUrl = Deno.env.get('SUPABASE_DB_URL')!
    const pool = new postgres.Pool(databaseUrl, 3, true)
    const connection = await pool.connect()

    try {
      // Authorization scope: which dataset tables may this caller see?
      const allowed = await readableTableNames(connection, caller)

      // Get all tables in _fd schema (excluding metadata table)
      const tablesResult = await connection.queryObject(`
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = '_fd' AND table_name != 'metadata_tables'
        ORDER BY table_name;
      `)

      const tableStats = []

      // Get simple stats for each table
      for (const row of tablesResult.rows) {
        const tableName = row.table_name as string
        if (allowed !== null && !allowed.has(tableName)) continue

        // Get row count
        const countResult = await connection.queryObject(
          `SELECT COUNT(*) as count FROM _fd."${tableName}";`
        )

        // Get column count
        const colCountResult = await connection.queryObject(
          `SELECT COUNT(*) as count
           FROM information_schema.columns
           WHERE table_schema = '_fd' AND table_name = $1;`,
          [tableName]
        )

        tableStats.push({
          name: tableName,
          rows: Number(countResult.rows[0]?.count || 0),
          columns: Number(colCountResult.rows[0]?.count || 0)
        })
      }

      // Get metadata information (filtered to authorized datasets)
      const metadataResult = allowed === null
        ? await connection.queryObject(`
            SELECT table_name, main_table, description, origin, created_at
            FROM _fd.metadata_tables
            ORDER BY created_at DESC;
          `)
        : await connection.queryObject(
            `SELECT table_name, main_table, description, origin, created_at
               FROM _fd.metadata_tables
              WHERE table_name = ANY($1::text[])
              ORDER BY created_at DESC`,
            [Array.from(allowed)],
          )

      // Calculate summary statistics
      const summary = {
        total_datasets: tableStats.length,
        total_rows: tableStats.reduce((sum, t) => sum + t.rows, 0),
        total_columns: tableStats.reduce((sum, t) => sum + t.columns, 0),
        avg_rows: tableStats.length > 0
          ? Math.round(tableStats.reduce((sum, t) => sum + t.rows, 0) / tableStats.length)
          : 0
      }

      // Prepare response data
      const responseData = {
        success: true,
        tables: tableStats,
        metadata: metadataResult.rows,
        summary
      }

      return new Response(
        JSON.stringify(responseData),
        {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' },
          status: 200,
        },
      )

    } finally {
      connection.release()
    }

  } catch (error) {
    console.error('Error in get-dataset-stats:', error)
    return new Response(
      JSON.stringify({ success: false, error: error.message }),
      {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' },
        status: 500,
      },
    )
  }
}

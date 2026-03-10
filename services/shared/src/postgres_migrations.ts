import { promises as fs } from 'node:fs'
import path from 'node:path'
import type { Pool } from 'pg'

export interface PostgresMigrationConfig {
  serviceName: string
  migrationsDir: string
  schemaName: string
}

export async function runPostgresMigrations(
  pool: Pool,
  config: PostgresMigrationConfig,
): Promise<void> {
  const migrationsDir = await resolveProjectPath(config.migrationsDir)
  const migrationFiles = (await fs.readdir(migrationsDir))
    .filter((name) => name.endsWith('.sql'))
    .sort()
  const migrationPayloads = await Promise.all(
    migrationFiles.map(async (filename) => ({
      filename,
      version: filename.replace(/\.sql$/i, ''),
      sql: await fs.readFile(path.join(migrationsDir, filename), 'utf8'),
    })),
  )

  const client = await pool.connect()
  try {
    await client.query('BEGIN')
    await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', ['service-postgres-migrations'])
    await client.query(`
      CREATE TABLE IF NOT EXISTS public.service_postgres_migrations (
        service_name TEXT NOT NULL,
        version TEXT NOT NULL,
        filename TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(service_name, version)
      )
    `)
    const schemaName = normalizeSchemaName(config.schemaName)
    await client.query(`CREATE SCHEMA IF NOT EXISTS ${quoteIdent(schemaName)}`)
    await client.query(`SET LOCAL search_path TO ${quoteIdent(schemaName)}, public`)
    await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [`postgres-migrations:${config.serviceName}`])

    const applied = new Set<string>(
      (await client.query(
        `
          SELECT version
          FROM public.service_postgres_migrations
          WHERE service_name = $1
          ORDER BY version ASC
        `,
        [config.serviceName],
      )).rows.map((row) => String(row.version)),
    )

    for (const migration of migrationPayloads) {
      if (applied.has(migration.version)) {
        continue
      }
      if (migration.sql.trim()) {
        await client.query(migration.sql)
      }
      await client.query(
        `
          INSERT INTO public.service_postgres_migrations(service_name, version, filename)
          VALUES ($1, $2, $3)
        `,
        [config.serviceName, migration.version, migration.filename],
      )
    }

    await client.query('COMMIT')
  } catch (error) {
    await client.query('ROLLBACK')
    throw error
  } finally {
    client.release()
  }
}

function normalizeSchemaName(input: string): string {
  const value = String(input ?? '').trim()
  if (!value) {
    throw new Error('Postgres schema name must not be empty')
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) {
    throw new Error(`Invalid Postgres schema name: ${value}`)
  }
  return value
}

function quoteIdent(value: string): string {
  return `"${value.replace(/"/g, '""')}"`
}

async function resolveProjectPath(input: string): Promise<string> {
  if (path.isAbsolute(input)) {
    return input
  }
  let current = process.cwd()
  while (true) {
    const candidate = path.join(current, input)
    try {
      await fs.access(candidate)
      return candidate
    } catch {
      // Keep walking upward until the filesystem root.
    }
    const parent = path.dirname(current)
    if (parent === current) {
      return path.resolve(process.cwd(), input)
    }
    current = parent
  }
}

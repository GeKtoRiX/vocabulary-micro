import path from 'node:path'

function env(name: string, fallback: string): string {
  const value = process.env[name]
  return value && value.trim() ? value.trim() : fallback
}

function envInt(name: string, fallback: number): number {
  const raw = process.env[name]
  if (!raw) {
    return fallback
  }
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

function envBool(name: string, fallback: boolean): boolean {
  const raw = process.env[name]
  if (!raw) {
    return fallback
  }
  return ['1', 'true', 'yes', 'on'].includes(raw.trim().toLowerCase())
}

export interface HttpServiceConfig {
  host: string
  port: number
}

export interface SharedServiceConfig {
  legacyBaseUrl: string
  lexiconDbPath: string
  assignmentsDbPath: string
  gateway: HttpServiceConfig & {
    serveStatic: boolean
    staticDir: string
    parseBackend: 'legacy' | 'nlp'
    lexiconBackend: 'service' | 'legacy'
    assignmentsBackend: 'service' | 'legacy'
    statisticsBackend: 'composed' | 'legacy'
    exportBackend: 'service' | 'legacy'
  }
  lexiconService: HttpServiceConfig & {
    storageBackend: 'sqlite' | 'postgres'
    postgresUrl: string
    bootstrapFromSqlite: boolean
  }
  assignmentsService: HttpServiceConfig & {
    storageBackend: 'sqlite' | 'postgres'
    postgresUrl: string
    bootstrapFromSqlite: boolean
  }
  nlpService: HttpServiceConfig
  exportService: HttpServiceConfig
}

export function loadConfig(): SharedServiceConfig {
  const cwd = process.cwd()
  const projectRoot = path.basename(cwd) === 'services' ? path.dirname(cwd) : cwd
  const ownerServicesStorageBackend = env('OWNER_SERVICES_STORAGE_BACKEND', 'sqlite') as 'sqlite' | 'postgres'
  const ownerServicesPostgresUrl = env('OWNER_SERVICES_POSTGRES_URL', 'postgresql://postgres:postgres@127.0.0.1:5432/vocabulary')
  const ownerServicesBootstrapFromSqlite = envBool('OWNER_SERVICES_POSTGRES_BOOTSTRAP_FROM_SQLITE', false)
  return {
    legacyBaseUrl: env('LEGACY_BACKEND_BASE_URL', 'http://127.0.0.1:8766'),
    lexiconDbPath: env('LEXICON_DB_PATH', path.join(projectRoot, 'infrastructure', 'persistence', 'data', 'lexicon.sqlite3')),
    assignmentsDbPath: env('ASSIGNMENTS_DB_PATH', path.join(projectRoot, 'infrastructure', 'persistence', 'data', 'assignments.db')),
    gateway: {
      host: env('GATEWAY_HOST', '127.0.0.1'),
      port: envInt('GATEWAY_PORT', 8765),
      serveStatic: envBool('GATEWAY_SERVE_STATIC', true),
      staticDir: env('GATEWAY_STATIC_DIR', path.join(projectRoot, 'web', 'dist')),
      parseBackend: env('GATEWAY_PARSE_BACKEND', 'nlp') as 'legacy' | 'nlp',
      lexiconBackend: env('GATEWAY_LEXICON_BACKEND', 'service') as 'service' | 'legacy',
      assignmentsBackend: env('GATEWAY_ASSIGNMENTS_BACKEND', 'service') as 'service' | 'legacy',
      statisticsBackend: env('GATEWAY_STATISTICS_BACKEND', 'composed') as 'composed' | 'legacy',
      exportBackend: env('GATEWAY_EXPORT_BACKEND', 'service') as 'service' | 'legacy',
    },
    lexiconService: {
      host: env('LEXICON_SERVICE_HOST', '127.0.0.1'),
      port: envInt('LEXICON_SERVICE_PORT', 4011),
      storageBackend: env('LEXICON_STORAGE_BACKEND', ownerServicesStorageBackend) as 'sqlite' | 'postgres',
      postgresUrl: env('LEXICON_POSTGRES_URL', ownerServicesPostgresUrl),
      bootstrapFromSqlite: envBool('LEXICON_POSTGRES_BOOTSTRAP_FROM_SQLITE', ownerServicesBootstrapFromSqlite),
    },
    assignmentsService: {
      host: env('ASSIGNMENTS_SERVICE_HOST', '127.0.0.1'),
      port: envInt('ASSIGNMENTS_SERVICE_PORT', 4012),
      storageBackend: env('ASSIGNMENTS_STORAGE_BACKEND', ownerServicesStorageBackend) as 'sqlite' | 'postgres',
      postgresUrl: env('ASSIGNMENTS_POSTGRES_URL', ownerServicesPostgresUrl),
      bootstrapFromSqlite: envBool('ASSIGNMENTS_POSTGRES_BOOTSTRAP_FROM_SQLITE', ownerServicesBootstrapFromSqlite),
    },
    nlpService: {
      host: env('NLP_SERVICE_HOST', '127.0.0.1'),
      port: envInt('NLP_SERVICE_PORT', 8767),
    },
    exportService: {
      host: env('EXPORT_SERVICE_HOST', '127.0.0.1'),
      port: envInt('EXPORT_SERVICE_PORT', 8768),
    },
  }
}

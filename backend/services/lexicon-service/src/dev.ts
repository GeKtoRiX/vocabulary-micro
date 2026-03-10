import { buildLexiconServiceApp } from './app.ts'
import { loadConfig } from '@vocabulary/shared'

const app = buildLexiconServiceApp()
const config = loadConfig()

app.listen({ host: config.lexiconService.host, port: config.lexiconService.port }).catch((error) => {
  console.error(error)
  process.exit(1)
})

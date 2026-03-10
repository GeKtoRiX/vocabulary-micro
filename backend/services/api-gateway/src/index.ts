import { buildGatewayApp } from './app.js'
import { loadConfig } from '@vocabulary/shared'

const app = buildGatewayApp()
const config = loadConfig()

app.listen({ host: config.gateway.host, port: config.gateway.port }).catch((error) => {
  console.error(error)
  process.exit(1)
})

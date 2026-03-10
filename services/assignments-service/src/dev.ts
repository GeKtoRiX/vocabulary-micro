import { buildAssignmentsServiceApp } from './app.ts'
import { loadConfig } from '@vocabulary/shared'

const app = buildAssignmentsServiceApp()
const config = loadConfig()

app.listen({ host: config.assignmentsService.host, port: config.assignmentsService.port }).catch((error) => {
  console.error(error)
  process.exit(1)
})

import { mkdirSync } from 'node:fs'
import { dirname } from 'node:path'
import { openDb } from './db.js'
import { buildServer } from './server.js'

const DB_PATH = process.env.DB_PATH ?? './data/agcs.db'
const STORAGE_DIR = process.env.STORAGE_DIR ?? './storage'
const PORT = Number(process.env.API_PORT ?? 8787)

mkdirSync(dirname(DB_PATH), { recursive: true })
mkdirSync(STORAGE_DIR, { recursive: true })

const db = openDb(DB_PATH)
const app = buildServer(db, STORAGE_DIR)

app
  .listen({ port: PORT, host: '0.0.0.0' })
  .then(() => console.log(`AGCS API listening on :${PORT}`))
  .catch((err) => {
    console.error(err)
    process.exit(1)
  })

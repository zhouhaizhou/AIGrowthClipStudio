import { DatabaseSync } from 'node:sqlite'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const SCHEMA_PATH = join(here, '../../../db/schema.sql')

export type DB = DatabaseSync

export function openDb(path: string): DB {
  const db = new DatabaseSync(path)
  db.exec('PRAGMA journal_mode = WAL')
  db.exec('PRAGMA foreign_keys = ON')
  db.exec(readFileSync(SCHEMA_PATH, 'utf8'))
  return db
}

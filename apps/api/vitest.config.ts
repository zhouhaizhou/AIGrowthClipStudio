import { defineConfig } from 'vitest/config'
import { createRequire } from 'node:module'

const _require = createRequire(import.meta.url)

export default defineConfig({
  plugins: [
    {
      name: 'node-sqlite-shim',
      enforce: 'pre',
      resolveId(id) {
        if (id === 'node:sqlite' || id === 'sqlite') {
          return '\0node:sqlite'
        }
      },
      load(id) {
        if (id === '\0node:sqlite') {
          const m = _require('node:sqlite')
          const keys = Object.keys(m)
          const exports = keys.map(k => `export const ${k} = _m.${k};`).join('\n')
          return `const _m = require('node:sqlite');\n${exports}\nexport default _m;`
        }
      },
    },
  ],
  test: {
    include: ['test/**/*.test.ts'],
  },
})

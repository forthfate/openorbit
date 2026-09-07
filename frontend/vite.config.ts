import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

function releaseVersion(){
  if(process.env.OPENORBIT_VERSION)return process.env.OPENORBIT_VERSION
  return `v${process.env.npm_package_version??'development'}`
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __OPENORBIT_VERSION__: JSON.stringify(releaseVersion()) },
  server: { proxy: { '/api': process.env.OPENORBIT_API_URL ?? 'http://127.0.0.1:3001' } },
})

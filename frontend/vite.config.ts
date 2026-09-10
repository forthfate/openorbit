import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { visualizer } from 'rollup-plugin-visualizer'

function releaseVersion(){
  if(process.env.OPENORBIT_VERSION)return process.env.OPENORBIT_VERSION
  return `v${process.env.npm_package_version??'development'}`
}

const apiTarget=process.env.OPENORBIT_API_URL??`http://${process.env.ORBIT_HOST??'127.0.0.1'}:${process.env.ORBIT_PORT??'3000'}`

export default defineConfig(({ mode }) => ({
  plugins: [
    react(),
    tailwindcss(),
    ...(mode === 'analyze'
      ? [visualizer({ filename: 'dist/stats.html', gzipSize: true, brotliSize: true })]
      : []),
  ],
  define: { __OPENORBIT_VERSION__: JSON.stringify(releaseVersion()) },
  server: { proxy: { '/api': { target: apiTarget, ws: true } } },
}))

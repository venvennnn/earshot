import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The Agora RTC/RTM SDKs are large by nature and are already split into the lazy voice chunk.
  build: { chunkSizeWarningLimit: 3200 },
})

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': '/src' } },
  build: {
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'maplibre-vendor', test: /node_modules[\\/]maplibre-gl/, priority: 40, maxSize: 500 * 1024 },
            { name: 'recharts-vendor', test: /node_modules[\\/]recharts|node_modules[\\/]d3-|node_modules[\\/]victory-vendor/, priority: 35 },
            { name: 'react-vendor', test: /node_modules[\\/](react|react-dom)[\\/]/, priority: 30 },
            { name: 'motion-icons-vendor', test: /node_modules[\\/](framer-motion|motion|lucide-react)[\\/]/, priority: 20 },
            { name: 'vendor', test: /node_modules/, priority: 1, maxSize: 500 * 1024 }
          ]
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]'
      }
    }
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true
      }
    }
  }
});

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import config from '../config.json'
export default defineConfig({plugins:[react()],server:{port:config.dev_port,strictPort:true,proxy:{[config.api_prefix]:`http://${config.host}:${config.port}`}}})

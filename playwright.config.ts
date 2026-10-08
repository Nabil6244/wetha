import { defineConfig } from '@playwright/test';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const testDataDir = mkdtempSync(join(tmpdir(), 'wetha-browser-'));
export default defineConfig({
  testDir:'tests', workers:1, fullyParallel:false, timeout:30000,
  use:{baseURL:'http://127.0.0.1:5173', headless:true, viewport:{width:1440,height:1000},
    launchOptions:process.env.WETHA_CHROMIUM ? {executablePath:process.env.WETHA_CHROMIUM} : {}},
  webServer:[
    {command:'node scripts/backend.cjs', url:'http://127.0.0.1:8000/api/health', reuseExistingServer:false, env:{WETHA_DATA_DIR:testDataDir}},
    {command:'npm run dev:ui', url:'http://127.0.0.1:5173', reuseExistingServer:false},
  ],
});

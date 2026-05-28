/**
 * sync-dist.mjs — 构建后同步dist到AgentServer/static
 * 
 * 用法: node scripts/sync-dist.mjs
 * 或:   npm run deploy (自动调用)
 */
import { cpSync, rmSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(__dirname, '..', 'dist');
const staticDir = resolve(__dirname, '..', '..', 'AgentServer', 'static');

if (!existsSync(distDir)) {
  console.error('❌ dist/ not found. Run "npm run build" first.');
  process.exit(1);
}

// 清理旧static
if (existsSync(staticDir)) {
  rmSync(staticDir, { recursive: true });
}

// 复制dist→static
cpSync(distDir, staticDir, { recursive: true });

console.log(`✅ Synced dist/ → AgentServer/static/ (${staticDir})`);

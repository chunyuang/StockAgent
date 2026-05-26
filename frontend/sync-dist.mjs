/**
 * build后自动同步 dist → AgentServer/static（生产fallback）
 * 这样Web节点优先读frontend/dist，fallback读AgentServer/static，两份都保持最新
 */
import { cpSync, mkdirSync, existsSync, rmSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(__dirname, 'dist');
const staticDir = resolve(__dirname, '../AgentServer/static');

if (!existsSync(distDir)) {
  console.error('❌ frontend/dist 不存在，请先 vite build');
  process.exit(1);
}

// 清理旧static，拷贝新dist
if (existsSync(staticDir)) {
  rmSync(staticDir, { recursive: true });
}
mkdirSync(staticDir, { recursive: true });
cpSync(distDir, staticDir, { recursive: true });

console.log(`✅ 已同步 dist → AgentServer/static (${new Date().toLocaleTimeString()})`);

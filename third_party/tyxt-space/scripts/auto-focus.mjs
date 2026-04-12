#!/usr/bin/env node
/**
 * auto-focus.mjs — C3 Hybrid auto-focus for ClawLibrary thought bubbles
 * 
 * Reads active subagent sessions, extracts recent tool calls,
 * generates human-readable status via rule-based mapping + optional LLM enrichment.
 * 
 * Runs as a sidecar, polling every POLL_INTERVAL_MS.
 * Only writes focus files when there's no recent manual focus (< MANUAL_FOCUS_TTL_MS).
 */

import fs from 'node:fs';
import path from 'node:path';

const OPENCLAW_HOME = process.env.OPENCLAW_HOME || path.join(process.env.HOME, '.openclaw');
const SUBAGENTS_DIR = path.join(OPENCLAW_HOME, 'subagents');
const SESSIONS_DIR = path.join(OPENCLAW_HOME, 'agents', 'main', 'sessions');
const RUNS_PATH = path.join(SUBAGENTS_DIR, 'runs.json');
const SESSIONS_INDEX_PATH = path.join(SESSIONS_DIR, 'sessions.json');
const EXEC_PROCESSES_PATH = path.join(OPENCLAW_HOME, 'exec-processes.json');

const POLL_INTERVAL_MS = 10_000;       // Check every 10s
const MANUAL_FOCUS_TTL_MS = 60_000;    // Manual focus file valid for 60s
const LLM_COOLDOWN_MS = 30_000;        // LLM enrichment at most every 30s per agent
const JSONL_TAIL_LINES = 20;           // Read last N lines from session JSONL
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';

// Track last LLM call per agent to avoid spamming
const lastLlmCall = new Map();
// Track last auto-derived status to avoid redundant writes
const lastAutoStatus = new Map();

// ── Rule-based tool call → human readable ──────────────────────────────────

const TOOL_PATTERNS = [
  // Build & compile
  [/npm run build/i, '🔧 Compilando proyecto...'],
  [/npx tsc/i, '🔧 Verificando tipos (TypeScript)...'],
  [/npm run lint/i, '🔍 Corriendo linter...'],
  [/npm ci|npm install/i, '📦 Instalando dependencias...'],
  
  // Tests
  [/playwright test/i, '🧪 Corriendo E2E tests...'],
  [/npx jest|npm run test|vitest/i, '🧪 Corriendo tests...'],
  [/playwright install/i, '📦 Instalando browsers para E2E...'],
  
  // Git operations
  [/git merge origin\/main/i, '🔄 Mergeando main en branch...'],
  [/git checkout (.+)/i, (m) => `🔀 Cambiando a branch ${m[1].slice(0, 40)}...`],
  [/git fetch/i, '📡 Fetching cambios remotos...'],
  [/git add|git commit/i, '💾 Commiteando cambios...'],
  [/git push/i, '🚀 Pusheando cambios...'],
  [/git diff/i, '🔍 Revisando diferencias...'],
  [/git log/i, '📜 Revisando historial...'],
  
  // GitHub
  [/gh pr merge.*#?(\d+)/i, (m) => `🔀 Mergeando PR #${m[1]}...`],
  [/gh pr merge/i, '🔀 Mergeando PR...'],
  [/gh pr create/i, '📝 Creando PR...'],
  [/gh pr view/i, '👀 Revisando PR...'],
  [/gh pr list/i, '📋 Listando PRs...'],
  
  // Serve & run
  [/npx serve dist/i, '🌐 Levantando servidor local...'],
  [/npx wait-on/i, '⏳ Esperando que el servidor arranque...'],
  [/pkill.*serve/i, '🛑 Deteniendo servidor...'],
  
  // File operations
  [/curl/i, '🌐 Haciendo request HTTP...'],
  [/grep -r/i, '🔍 Buscando en el código...'],
];

function ruleBasedStatus(toolName, args) {
  if (toolName === 'exec') {
    const cmd = args?.command || '';
    for (const [pattern, result] of TOOL_PATTERNS) {
      const match = cmd.match(pattern);
      if (match) {
        return typeof result === 'function' ? result(match) : result;
      }
    }
    // Fallback: first 60 chars of command
    const shortCmd = cmd.split('\n')[0].slice(0, 60);
    return `⚙️ ${shortCmd}...`;
  }
  
  if (toolName === 'read') {
    const filePath = args?.file_path || args?.path || '';
    const fileName = path.basename(filePath);
    return `📖 Leyendo ${fileName}...`;
  }
  
  if (toolName === 'write') {
    const filePath = args?.file_path || args?.path || '';
    const fileName = path.basename(filePath);
    return `✏️ Escribiendo ${fileName}...`;
  }
  
  if (toolName === 'edit') {
    const filePath = args?.file_path || args?.path || '';
    const fileName = path.basename(filePath);
    return `✏️ Editando ${fileName}...`;
  }
  
  if (toolName === 'message') {
    return '💬 Enviando mensaje...';
  }
  
  if (toolName === 'process') {
    const action = args?.action || '';
    if (action === 'poll') return '⏳ Esperando resultado...';
    if (action === 'kill') return '🛑 Deteniendo proceso...';
    return `⚙️ Gestionando proceso (${action})...`;
  }
  
  if (toolName === 'web_search') {
    return '🔍 Buscando en la web...';
  }
  
  if (toolName === 'web_fetch') {
    return '🌐 Descargando página...';
  }
  
  return null;
}

// ── LLM enrichment (Haiku/GPT-4o-mini) ─────────────────────────────────────

async function llmEnrich(task, recentTools) {
  if (!OPENAI_API_KEY) return null;
  
  const toolSummary = recentTools.map(t => {
    if (t.name === 'exec') return `exec: ${(t.args?.command || '').split('\n')[0].slice(0, 80)}`;
    if (t.name === 'read') return `read: ${t.args?.file_path || t.args?.path || '?'}`;
    if (t.name === 'write') return `write: ${t.args?.file_path || t.args?.path || '?'}`;
    if (t.name === 'edit') return `edit: ${t.args?.file_path || t.args?.path || '?'}`;
    return `${t.name}`;
  }).join('\n');
  
  try {
    const resp = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${OPENAI_API_KEY}`
      },
      body: JSON.stringify({
        model: 'gpt-4o-mini',
        max_tokens: 60,
        temperature: 0,
        messages: [
          {
            role: 'system',
            content: 'You generate a 1-line status update (max 50 chars) in Spanish describing what an AI agent is doing. Use an emoji prefix. Be specific and concise. Only output the status line, nothing else.'
          },
          {
            role: 'user',
            content: `Task: ${(task || '').slice(0, 200)}\n\nLast 3 actions:\n${toolSummary}\n\nOne-line status:`
          }
        ]
      })
    });
    
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.choices?.[0]?.message?.content?.trim() || null;
  } catch {
    return null;
  }
}

// ── JSONL tail reader ───────────────────────────────────────────────────────

function tailLines(filePath, n) {
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.trim().split('\n');
    return lines.slice(-n);
  } catch {
    return [];
  }
}

function extractRecentToolCalls(jsonlPath) {
  const lines = tailLines(jsonlPath, JSONL_TAIL_LINES);
  const tools = [];
  
  for (const line of lines) {
    try {
      const entry = JSON.parse(line);
      const msg = entry.message || entry;
      const role = msg.role;
      
      if (role === 'assistant') {
        const content = msg.content || [];
        for (const c of content) {
          if (c.type === 'toolCall') {
            tools.push({
              name: c.name,
              args: c.arguments || {},
              timestamp: entry.timestamp || 0
            });
          }
        }
      }
    } catch { /* skip malformed */ }
  }
  
  // Return last 3 tool calls (most recent last)
  return tools.slice(-3);
}

// ── Main loop ───────────────────────────────────────────────────────────────

function getActiveSubagents() {
  try {
    const runsData = JSON.parse(fs.readFileSync(RUNS_PATH, 'utf8'));
    const runs = runsData.runs || {};
    return Object.entries(runs)
      .filter(([_, run]) => !run.endedAt)
      .map(([runId, run]) => ({
        runId,
        label: run.label || runId,
        task: run.task || '',
        childSessionKey: run.childSessionKey || ''
      }));
  } catch {
    return [];
  }
}

function getActiveExecProcesses() {
  try {
    const procs = JSON.parse(fs.readFileSync(EXEC_PROCESSES_PATH, 'utf8'));
    return procs.filter(p => p.status === 'running');
  } catch {
    return [];
  }
}

function getSessionId(sessionKey) {
  try {
    const sessions = JSON.parse(fs.readFileSync(SESSIONS_INDEX_PATH, 'utf8'));
    const entry = sessions[sessionKey];
    return entry?.sessionId || null;
  } catch {
    return null;
  }
}

function isManualFocusRecent(focusPath) {
  try {
    const stat = fs.statSync(focusPath);
    const age = Date.now() - stat.mtimeMs;
    // Check if the file was written by auto-focus (has _auto marker)
    const content = fs.readFileSync(focusPath, 'utf8');
    const data = JSON.parse(content);
    if (data._auto) return false; // Our own file, not manual
    return age < MANUAL_FOCUS_TTL_MS;
  } catch {
    return false;
  }
}

async function processAgent(agent) {
  const focusId = agent.runId;
  const focusPath = path.join(SUBAGENTS_DIR, `focus-${focusId}.json`);
  // Also check label-based focus file
  const focusPathLabel = path.join(SUBAGENTS_DIR, `focus-${agent.label}.json`);
  
  // Skip if manual focus file is recent
  if (isManualFocusRecent(focusPath) || isManualFocusRecent(focusPathLabel)) {
    return;
  }
  
  // Find session JSONL
  const sessionId = getSessionId(agent.childSessionKey);
  if (!sessionId) return;
  
  const jsonlPath = path.join(SESSIONS_DIR, `${sessionId}.jsonl`);
  const recentTools = extractRecentToolCalls(jsonlPath);
  
  if (recentTools.length === 0) return;
  
  // Rule-based status from the most recent tool call
  const lastTool = recentTools[recentTools.length - 1];
  let status = ruleBasedStatus(lastTool.name, lastTool.args);
  
  // Try LLM enrichment if cooldown allows
  const now = Date.now();
  const lastCall = lastLlmCall.get(focusId) || 0;
  if (now - lastCall > LLM_COOLDOWN_MS && recentTools.length >= 2) {
    lastLlmCall.set(focusId, now);
    const enriched = await llmEnrich(agent.task, recentTools);
    if (enriched) {
      status = enriched;
    }
  }
  
  if (!status) return;
  
  // Don't write if status hasn't changed
  if (lastAutoStatus.get(focusId) === status) return;
  lastAutoStatus.set(focusId, status);
  
  // Write auto-derived focus file
  const focusData = {
    resourceId: 'mcp',
    detail: status,
    _auto: true,
    _updatedAt: new Date().toISOString()
  };
  
  try {
    fs.writeFileSync(focusPath, JSON.stringify(focusData));
  } catch { /* best-effort */ }
}

// ── Main session focus ──────────────────────────────────────────────────────

const MAIN_SESSION_KEY = 'agent:main:main';
const MAIN_FOCUS_PATH = path.join(SUBAGENTS_DIR, 'focus-main.json');
const MAIN_IDLE_THRESHOLD_MS = 60_000; // If no tool call in 60s, consider idle
let lastMainStatus = '';
let lastMainLlmCall = 0;

async function processMainSession() {
  // Find the main session JSONL
  const sessionId = getSessionId(MAIN_SESSION_KEY);
  if (!sessionId) return;

  const jsonlPath = path.join(SESSIONS_DIR, `${sessionId}.jsonl`);
  const recentTools = extractRecentToolCalls(jsonlPath);

  if (recentTools.length === 0) {
    return;
  }

  // Check if most recent tool call is recent enough (within threshold)
  const lastTool = recentTools[recentTools.length - 1];
  const tsMs = lastTool.timestamp
    ? (typeof lastTool.timestamp === 'number' ? lastTool.timestamp : new Date(lastTool.timestamp).getTime())
    : 0;
  const lastToolAge = tsMs ? Date.now() - tsMs : Infinity;

  // If we can't determine age from timestamp, check file mtime
  let isActive = lastToolAge < MAIN_IDLE_THRESHOLD_MS;
  if (!isActive && lastToolAge === Infinity) {
    // Fallback: check JSONL file mtime
    try {
      const stat = fs.statSync(jsonlPath);
      isActive = (Date.now() - stat.mtimeMs) < MAIN_IDLE_THRESHOLD_MS;
    } catch { /* skip */ }
  }

  if (!isActive) {
    // Don't actively clean up — let the mtime-based check in vite.config.ts
    // handle expiration (90s). This avoids race conditions where the file
    // gets deleted between auto-focus ticks while the main session is still active.
    return;
  }

  // Generate status from rule-based matching
  let status = ruleBasedStatus(lastTool.name, lastTool.args);

  // Try LLM enrichment
  const now = Date.now();
  if (now - lastMainLlmCall > LLM_COOLDOWN_MS && recentTools.length >= 2 && OPENAI_API_KEY) {
    lastMainLlmCall = now;
    const enriched = await llmEnrich('Main ClawBot session — responding to user requests', recentTools);
    if (enriched) status = enriched;
  }

  if (!status) return;
  if (lastMainStatus === status) return;
  lastMainStatus = status;

  console.log(`[auto-focus] Main session status: ${status} (age: ${Math.round(lastToolAge/1000)}s)`);

  // Write focus file for main session
  const focusData = {
    resourceId: 'gateway',
    detail: status,
    _auto: true,
    _isMain: true,
    _updatedAt: new Date().toISOString()
  };

  try {
    const payload = JSON.stringify(focusData);
    fs.writeFileSync(MAIN_FOCUS_PATH, payload);
    console.log(`[auto-focus] Wrote focus-main.json: ${payload.slice(0, 80)}`);
  } catch (err) {
    console.error(`[auto-focus] Failed to write focus-main.json:`, err.message);
  }
}

function cleanupMainFocus() {
  try {
    if (fs.existsSync(MAIN_FOCUS_PATH)) {
      const data = JSON.parse(fs.readFileSync(MAIN_FOCUS_PATH, 'utf8'));
      if (data._auto && data._isMain) {
        fs.unlinkSync(MAIN_FOCUS_PATH);
        lastMainStatus = '';
      }
    }
  } catch { /* best-effort */ }
}

async function tick() {
  const agents = getActiveSubagents();
  
  for (const agent of agents) {
    try {
      await processAgent(agent);
    } catch { /* best-effort per agent */ }
  }

  // Also process the main session
  try {
    await processMainSession();
  } catch { /* best-effort */ }
}

// ── Start ───────────────────────────────────────────────────────────────────

console.log(`[auto-focus] Started. Poll every ${POLL_INTERVAL_MS / 1000}s`);
console.log(`[auto-focus] OpenClaw home: ${OPENCLAW_HOME}`);
console.log(`[auto-focus] LLM enrichment: ${OPENAI_API_KEY ? 'enabled (gpt-4o-mini)' : 'disabled (no OPENAI_API_KEY)'}`);

// Initial tick
tick();

// Poll loop
setInterval(tick, POLL_INTERVAL_MS);

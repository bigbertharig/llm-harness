#!/usr/bin/env node
// Small stdio MCP fixture. A marker exists only after the named tool is called.
import fs from 'node:fs';
import { randomBytes } from 'node:crypto';
import readline from 'node:readline';

const receipt = process.argv[2];
if (!receipt) throw new Error('receipt path argument required');
const write = (entry) => fs.appendFileSync(receipt, JSON.stringify({ at: new Date().toISOString(), ...entry }) + '\n');
const tools = [
  { name: 'read_marker', description: 'Return a freshly generated text marker for the tool-use test.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  { name: 'read_structured_marker', description: 'Return a freshly generated marker only in structuredContent.',
    inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
];

function respond(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
}

function handle(message) {
  const { id, method, params = {} } = message;
  if (!method) return;
  if (method === 'notifications/initialized') {
    write({ method });
    return;
  }
  write({ method, ...(method === 'tools/call' ? { tool: params.name } : {}) });
  if (id === undefined) return;
  if (method === 'initialize') {
    respond(id, {
      protocolVersion: '2025-06-18',
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: 'harness-tool-fixture', version: '1.0.0' },
    });
  } else if (method === 'ping') {
    respond(id, {});
  } else if (method === 'tools/list') {
    respond(id, { tools });
  } else if (method === 'tools/call') {
    if (!['read_marker', 'read_structured_marker'].includes(params.name)) {
      respond(id, { isError: true, content: [{ type: 'text', text: 'unknown tool' }] });
      return;
    }
    const structured = params.name === 'read_structured_marker';
    const marker = `MCP-${structured ? 'STRUCT' : 'TEXT'}-${randomBytes(8).toString('hex')}`;
    write({ method: 'tool/result', tool: params.name, marker });
    respond(id, structured
      ? { isError: false, content: [], structuredContent: { marker, kind: 'structured-only' } }
      : { isError: false, content: [{ type: 'text', text: marker }],
          structuredContent: { marker, kind: 'text-plus-structured' } });
  } else {
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }) + '\n');
  }
}

for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  if (!line.trim()) continue;
  try { handle(JSON.parse(line)); }
  catch (error) { console.error(String(error)); }
}

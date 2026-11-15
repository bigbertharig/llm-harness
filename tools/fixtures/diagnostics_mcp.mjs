#!/usr/bin/env node
// Deterministic MCP diagnostics. Profiles preserve frozen comparison cases.
import fs from 'node:fs';
import { randomBytes } from 'node:crypto';
import readline from 'node:readline';

const [first, second] = process.argv.slice(2);
const profile = ['marker', 'numeric', 'lookup', 'all'].includes(first) ? first : 'all';
const receipt = profile === 'all' && first !== 'all' ? first : second;
if (!receipt) throw new Error('usage: diagnostics_mcp.mjs [marker|numeric|lookup|all] RECEIPT');
const log = (entry) => fs.appendFileSync(receipt, JSON.stringify({ at: new Date().toISOString(), profile, ...entry }) + '\n');
const number = { type: 'number' };
const groups = {
  marker: [
    { name: 'read_marker', description: 'Return a fresh text marker.', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
    { name: 'read_structured_marker', description: 'Return a fresh marker only in structuredContent.', inputSchema: { type: 'object', properties: {}, additionalProperties: false } },
  ],
  numeric: [
    { name: 'calculate_sum', description: 'Add two numbers.', inputSchema: { type: 'object', properties: { a: number, b: number }, required: ['a', 'b'], additionalProperties: false } },
    { name: 'calculate_product', description: 'Multiply two numbers.', inputSchema: { type: 'object', properties: { a: number, b: number }, required: ['a', 'b'], additionalProperties: false } },
  ],
  lookup: [
    { name: 'get_entry', description: 'Look up a key and return a fresh receipt as text.', inputSchema: { type: 'object', properties: { key: { type: 'string' } }, required: ['key'], additionalProperties: false } },
    { name: 'get_nested_entry', description: 'Look up a key and return a fresh receipt inside structuredContent.entry.', inputSchema: { type: 'object', properties: { key: { type: 'string' } }, required: ['key'], additionalProperties: false } },
  ],
};
const tools = profile === 'all' ? Object.values(groups).flat() : groups[profile];
const respond = (id, result) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
const error = (text) => ({ isError: true, content: [{ type: 'text', text }] });

for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  if (!line.trim()) continue;
  try {
    const { id, method, params = {} } = JSON.parse(line);
    if (method === 'notifications/initialized') { log({ method }); continue; }
    log({ method, ...(method === 'tools/call' ? { tool: params.name, arguments: params.arguments ?? {} } : {}) });
    if (id === undefined) continue;
    if (method === 'initialize') {
      respond(id, { protocolVersion: '2025-06-18', capabilities: { tools: { listChanged: false } },
        serverInfo: { name: 'harness-diagnostics', version: '1.0.0' } });
    } else if (method === 'tools/list') respond(id, { tools });
    else if (method === 'ping') respond(id, {});
    else if (method === 'tools/call') {
      const { name, arguments: args = {} } = params;
      if (!tools.some((tool) => tool.name === name)) { respond(id, error('unknown tool')); continue; }
      if (groups.marker.some((tool) => tool.name === name)) {
        const structured = name === 'read_structured_marker';
        const marker = `MCP-${structured ? 'STRUCT' : 'TEXT'}-${randomBytes(8).toString('hex')}`;
        log({ method: 'tool/result', tool: name, marker });
        respond(id, structured
          ? { isError: false, content: [], structuredContent: { marker, kind: 'structured-only' } }
          : { isError: false, content: [{ type: 'text', text: marker }], structuredContent: { marker, kind: 'text-plus-structured' } });
      } else if (groups.numeric.some((tool) => tool.name === name)) {
        if (typeof args.a !== 'number' || typeof args.b !== 'number') { respond(id, error('a and b must be numbers')); continue; }
        const value = name === 'calculate_sum' ? args.a + args.b : args.a * args.b;
        log({ method: 'tool/result', tool: name, arguments: args, value });
        respond(id, { isError: false, content: [{ type: 'text', text: String(value) }], structuredContent: { value } });
      } else {
        if (typeof args.key !== 'string' || !args.key) { respond(id, error('key required')); continue; }
        const value = `MCP-LOOKUP-${randomBytes(8).toString('hex')}`;
        log({ method: 'tool/result', tool: name, arguments: args, value });
        respond(id, name === 'get_entry'
          ? { isError: false, content: [{ type: 'text', text: value }], structuredContent: { key: args.key, receipt: value } }
          : { isError: false, content: [], structuredContent: { entry: { key: args.key, receipt: value } } });
      }
    } else process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }) + '\n');
  } catch (cause) { console.error(String(cause)); }
}

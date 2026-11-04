#!/usr/bin/env node
// Two independent local MCP server profiles for the comparison matrix.
import fs from 'node:fs';
import { randomBytes } from 'node:crypto';
import readline from 'node:readline';

const [profile, receipt] = process.argv.slice(2);
if (!['numeric', 'lookup'].includes(profile) || !receipt) throw new Error('usage: server PROFILE RECEIPT');
const log = (entry) => fs.appendFileSync(receipt, JSON.stringify({ at: new Date().toISOString(), profile, ...entry }) + '\n');
const number = { type: 'number' };
const tools = profile === 'numeric' ? [
  { name: 'calculate_sum', description: 'Add two numbers and return their sum.',
    inputSchema: { type: 'object', properties: { a: number, b: number }, required: ['a', 'b'], additionalProperties: false } },
  { name: 'calculate_product', description: 'Multiply two numbers and return their product.',
    inputSchema: { type: 'object', properties: { a: number, b: number }, required: ['a', 'b'], additionalProperties: false } },
] : [
  { name: 'get_entry', description: 'Look up an entry by key and return its fresh receipt token as text.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' } }, required: ['key'], additionalProperties: false } },
  { name: 'get_nested_entry', description: 'Look up a nested entry by key. The fresh receipt token is inside structuredContent.entry.receipt.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' } }, required: ['key'], additionalProperties: false } },
];
const respond = (id, result) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
  if (!line.trim()) continue;
  try {
    const { id, method, params = {} } = JSON.parse(line);
    if (method === 'notifications/initialized') { log({ method }); continue; }
    log({ method, ...(method === 'tools/call' ? { tool: params.name, arguments: params.arguments ?? {} } : {}) });
    if (id === undefined) continue;
    if (method === 'initialize') {
      respond(id, { protocolVersion: '2025-06-18', capabilities: { tools: { listChanged: false } },
        serverInfo: { name: `harness-${profile}-fixture`, version: '1.0.0' } });
    } else if (method === 'tools/list') respond(id, { tools });
    else if (method === 'ping') respond(id, {});
    else if (method === 'tools/call') {
      const { name, arguments: args = {} } = params;
      if (!tools.some((t) => t.name === name)) { respond(id, { isError: true, content: [{ type: 'text', text: 'unknown tool' }] }); continue; }
      let result, value;
      if (profile === 'numeric') {
        if (typeof args.a !== 'number' || typeof args.b !== 'number') { respond(id, { isError: true, content: [{ type: 'text', text: 'a and b must be numbers' }] }); continue; }
        value = name === 'calculate_sum' ? args.a + args.b : args.a * args.b;
        result = { isError: false, content: [{ type: 'text', text: String(value) }], structuredContent: { value } };
      } else {
        if (typeof args.key !== 'string' || !args.key) { respond(id, { isError: true, content: [{ type: 'text', text: 'key required' }] }); continue; }
        value = `MCP-${profile.toUpperCase()}-${randomBytes(8).toString('hex')}`;
        result = name === 'get_entry'
          ? { isError: false, content: [{ type: 'text', text: value }], structuredContent: { key: args.key, receipt: value } }
          : { isError: false, content: [], structuredContent: { entry: { key: args.key, receipt: value } } };
      }
      log({ method: 'tool/result', tool: name, arguments: args, value });
      respond(id, result);
    } else process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code: -32601, message: 'Method not found' } }) + '\n');
  } catch (error) { console.error(String(error)); }
}

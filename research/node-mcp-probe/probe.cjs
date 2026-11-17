const fs = require('node:fs');
const {parseArgs} = require('node:util');
const {Client, StreamableHTTPClientTransport} = require('@modelcontextprotocol/client');

async function main() {
  const {values} = parseArgs({options: {
    url: {type: 'string'}, 'headers-file': {type: 'string'},
    output: {type: 'string'}, tag: {type: 'string'},
  }});
  if (!values.url || !values.output) throw new Error('Required: --url URL --output FILE');
  const url = new URL(values.url);
  if (url.username || url.password) throw new Error('Use a private headers file for authentication');
  const headers = values['headers-file'] ? JSON.parse(fs.readFileSync(values['headers-file'], 'utf8')) : {};
  const redact = text => Object.values(headers).reduce((s, secret) => s.replaceAll(String(secret), '[redacted]'), String(text));
  const diagnostics = [];
  const transport = new StreamableHTTPClientTransport(url, {requestInit: {headers}});
  const client = new Client({name: 'ignition-harness-research', version: '0.0.1'}, {capabilities: {}});
  client.onerror = error => diagnostics.push(redact(error.message));
  const result = {observedAt: new Date().toISOString(), clientPackage: '@modelcontextprotocol/client', clientVersion: '2.2.0'};
  try {
    await client.connect(transport);
    const tools = await client.listTools();
    result.toolNames = tools.tools.map(tool => tool.name);
    result.serverVersion = client.getServerVersion();
    if (values.tag) result.realtime = await client.callTool({name: 'realtime', arguments: {paths: [values.tag]}});
    result.connected = true;
  } catch (error) {
    result.connected = false;
    result.error = redact(error.message);
    process.exitCode = 1;
  } finally {
    await client.close();
  }
  result.diagnostics = diagnostics;
  fs.writeFileSync(values.output, JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify({connected: result.connected, toolNames: result.toolNames, diagnosticCount: diagnostics.length}));
}
main().catch(error => {console.error(error.name); process.exitCode = 1;});

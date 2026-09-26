// Transport qualification is injection-only. Load before the module under test;
// pair with the evidence runner's OS network denial for defense in depth.
import {syncBuiltinESMExports} from 'node:module';
import http from 'node:http';
import https from 'node:https';
import http2 from 'node:http2';
import net from 'node:net';
import tls from 'node:tls';
import dgram from 'node:dgram';
import dns from 'node:dns';
import childProcess from 'node:child_process';
import workerThreads from 'node:worker_threads';

let attempts = 0;
const deny = operation => function () {
  attempts++;
  const error = new Error('Network disabled for transport qualification: ' + operation);
  error.code = 'COSMAS_TEST_NETWORK_DENIED';
  throw error;
};
const replace = (target, names, family) => {
  for (const name of names) if (typeof target[name] === 'function') target[name] = deny(family + '.' + name);
};

globalThis.fetch = deny('fetch');
if (typeof globalThis.WebSocket === 'function') globalThis.WebSocket = deny('WebSocket');
replace(http, ['request', 'get', 'createServer'], 'http');
replace(https, ['request', 'get', 'createServer'], 'https');
replace(http2, ['connect', 'createServer', 'createSecureServer'], 'http2');
replace(net, ['connect', 'createConnection', 'createServer'], 'net');
replace(net.Socket.prototype, ['connect'], 'net.Socket');
replace(net.Server.prototype, ['listen'], 'net.Server');
replace(tls, ['connect', 'createServer'], 'tls');
replace(dgram, ['createSocket'], 'dgram');
const dnsMethods = ['lookup', 'lookupService', 'resolve', 'resolve4', 'resolve6', 'resolveAny',
  'resolveCaa', 'resolveCname', 'resolveMx', 'resolveNaptr', 'resolveNs', 'resolvePtr',
  'resolveSoa', 'resolveSrv', 'resolveTlsa', 'resolveTxt', 'reverse'];
replace(dns, dnsMethods, 'dns');
replace(dns.promises, dnsMethods, 'dns.promises');
replace(dns.Resolver.prototype, dnsMethods, 'dns.Resolver');
replace(dns.promises.Resolver.prototype, dnsMethods, 'dns.promises.Resolver');
// Test dependencies cannot create a child or worker that bypasses the guard.
replace(childProcess, ['exec', 'execSync', 'execFile', 'execFileSync', 'spawn', 'spawnSync', 'fork'], 'child_process');
replace(workerThreads, ['Worker'], 'worker_threads');
syncBuiltinESMExports();

export const networkGuardInstalled = true;
export const blockedNetworkAttempts = () => attempts;

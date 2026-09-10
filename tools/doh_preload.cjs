/*
 * Process-local DNS fallback for wow.export when the active macOS resolver is unreachable.
 *
 * This does not modify system DNS. It resolves Node.js HTTPS requests through Google DNS-over-HTTPS,
 * connecting to 8.8.8.8 directly while preserving TLS SNI and the Host header.
 */

const dns = require("node:dns");
const https = require("node:https");
const net = require("node:net");

const cache = new Map();
const pending = new Map();

function parseOptions(options, callback) {
  if (typeof options === "function")
    return [{}, options];
  if (typeof options === "number")
    return [{ family: options }, callback];
  return [options || {}, callback];
}

function resolveA(hostname, callback) {
  if (net.isIP(hostname)) {
    callback(null, hostname);
    return;
  }
  if (cache.has(hostname)) {
    callback(null, cache.get(hostname));
    return;
  }
  if (pending.has(hostname)) {
    pending.get(hostname).push(callback);
    return;
  }
  pending.set(hostname, [callback]);

  const request = https.get({
    host: "8.8.8.8",
    servername: "dns.google",
    path: `/resolve?name=${encodeURIComponent(hostname)}&type=A`,
    headers: { Host: "dns.google" },
    timeout: 10000,
  }, response => {
    const blocks = [];
    response.on("data", block => blocks.push(block));
    response.on("end", () => {
      let error = null;
      let address = null;
      try {
        const payload = JSON.parse(Buffer.concat(blocks).toString("utf8"));
        address = payload.Answer?.find(answer => answer.type === 1)?.data || null;
        if (!address)
          error = new Error(`DNS-over-HTTPS returned no A record for ${hostname}`);
      } catch (caught) {
        error = caught;
      }
      if (address)
        cache.set(hostname, address);
      const callbacks = pending.get(hostname) || [];
      pending.delete(hostname);
      for (const done of callbacks)
        done(error, address);
    });
  });
  request.on("timeout", () => request.destroy(new Error(`DNS-over-HTTPS timed out for ${hostname}`)));
  request.on("error", error => {
    const callbacks = pending.get(hostname) || [];
    pending.delete(hostname);
    for (const done of callbacks)
      done(error);
  });
}

dns.lookup = function lookup(hostname, options, callback) {
  const [normalized, done] = parseOptions(options, callback);
  resolveA(hostname, (error, address) => {
    if (error) {
      done(error);
      return;
    }
    if (normalized.all)
      done(null, [{ address, family: 4 }]);
    else
      done(null, address, 4);
  });
};

dns.promises.lookup = async function lookupPromise(hostname, options = {}) {
  return new Promise((resolve, reject) => {
    dns.lookup(hostname, options, (error, address, family) => {
      if (error)
        reject(error);
      else if (options.all)
        resolve(address);
      else
        resolve({ address, family });
    });
  });
};

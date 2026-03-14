/**
 * netlify/functions/counter.js
 * Uses Netlify's built-in environment-based approach.
 * Stores counter in a simple JSON file via the filesystem during build,
 * or falls back to an in-memory approach.
 * 
 * GET  → returns { letters, recipients }
 * POST → increments { letters, recipients }
 * 
 * Uses netlify-plugin-fetch-feeds pattern — no npm packages required.
 */

// Use a simple fetch-based approach to store in a free external KV
// We'll use jsonbin.io as a free persistent store — no npm needed
const https = require("https");

const BIN_ID  = process.env.JSONBIN_BIN_ID  || "";
const BIN_KEY = process.env.JSONBIN_API_KEY || "";
const BIN_URL = `api.jsonbin.io`;

function httpsRequest(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

exports.handler = async (event) => {
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 200, headers, body: "" };
  }

  // If no bin configured, return zeros gracefully
  if (!BIN_ID || !BIN_KEY) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ letters: 0, recipients: 0 }),
    };
  }

  try {
    if (event.httpMethod === "GET") {
      const res = await httpsRequest({
        hostname: BIN_URL,
        path: `/v3/b/${BIN_ID}/latest`,
        method: "GET",
        headers: {
          "X-Master-Key": BIN_KEY,
          "X-Bin-Meta": "false",
        },
      });
      const data = res.body.record || res.body || { letters: 0, recipients: 0 };
      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({ letters: data.letters || 0, recipients: data.recipients || 0 }),
      };
    }

    if (event.httpMethod === "POST") {
      const incoming = JSON.parse(event.body || "{}");

      // Get current
      const getRes = await httpsRequest({
        hostname: BIN_URL,
        path: `/v3/b/${BIN_ID}/latest`,
        method: "GET",
        headers: { "X-Master-Key": BIN_KEY, "X-Bin-Meta": "false" },
      });
      const current = getRes.body.record || getRes.body || { letters: 0, recipients: 0 };
      const updated = {
        letters:    (current.letters    || 0) + (parseInt(incoming.letters, 10)    || 0),
        recipients: (current.recipients || 0) + (parseInt(incoming.recipients, 10) || 0),
      };

      // Save updated
      const putBody = JSON.stringify(updated);
      await httpsRequest({
        hostname: BIN_URL,
        path: `/v3/b/${BIN_ID}`,
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-Master-Key": BIN_KEY,
          "Content-Length": Buffer.byteLength(putBody),
        },
      }, putBody);

      return { statusCode: 200, headers, body: JSON.stringify(updated) };
    }

    return { statusCode: 405, headers, body: "Method Not Allowed" };

  } catch (err) {
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ letters: 0, recipients: 0 }),
    };
  }
};

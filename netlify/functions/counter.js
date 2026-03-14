/**
 * netlify/functions/counter.js
 * GET  → returns { count, letters, recipients }
 * POST → increments by { letters, recipients } and returns new totals
 * Uses Netlify Blobs for persistent storage (free, built-in).
 */

const { getStore } = require("@netlify/blobs");

exports.handler = async (event) => {
  const headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 200, headers, body: "" };
  }

  try {
    const store = getStore({ name: "letter-counter", consistency: "strong" });

    if (event.httpMethod === "GET") {
      const raw = await store.get("totals");
      const totals = raw ? JSON.parse(raw) : { letters: 0, recipients: 0 };
      return { statusCode: 200, headers, body: JSON.stringify(totals) };
    }

    if (event.httpMethod === "POST") {
      const body = JSON.parse(event.body || "{}");
      const addLetters    = parseInt(body.letters, 10)    || 0;
      const addRecipients = parseInt(body.recipients, 10) || 0;

      const raw = await store.get("totals");
      const current = raw ? JSON.parse(raw) : { letters: 0, recipients: 0 };
      const updated = {
        letters:    current.letters    + addLetters,
        recipients: current.recipients + addRecipients,
      };
      await store.set("totals", JSON.stringify(updated));
      return { statusCode: 200, headers, body: JSON.stringify(updated) };
    }

    return { statusCode: 405, headers, body: "Method Not Allowed" };
  } catch (err) {
    // If Blobs aren't available (local dev), return zeros gracefully
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ letters: 0, recipients: 0, error: err.message }),
    };
  }
};

/**
 * netlify/functions/compose.js
 * Proxy for letter composition — tries Anthropic first, falls back to Groq.
 * Set ANTHROPIC_API_KEY and GROQ_API_KEY in Netlify Environment Variables.
 * Groq free tier: https://console.groq.com (no credit card needed)
 */

const https = require("https");

function httpsPost(hostname, path, headers, body) {
  return new Promise((resolve, reject) => {
    const req = https.request({ hostname, path, method: "POST", headers }, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => resolve({ status: res.statusCode, body: data }));
    });
    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

async function tryAnthropic(key, messages) {
  const payload = JSON.stringify({
    model: "claude-opus-4-5",
    max_tokens: 1200,
    messages,
  });
  const res = await httpsPost("api.anthropic.com", "/v1/messages", {
    "Content-Type": "application/json",
    "x-api-key": key,
    "anthropic-version": "2023-06-01",
    "Content-Length": Buffer.byteLength(payload),
  }, payload);
  const data = JSON.parse(res.body);
  if (res.status !== 200) {
    throw new Error(data?.error?.message || JSON.stringify(data));
  }
  // Return in standard format
  const text = data.content?.find(b => b.type === "text")?.text || "";
  return { text };
}

async function tryGroq(key, messages) {
  const payload = JSON.stringify({
    model: "llama-3.3-70b-versatile",
    max_tokens: 1200,
    messages,
  });
  const res = await httpsPost("api.groq.com", "/openai/v1/chat/completions", {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${key}`,
    "Content-Length": Buffer.byteLength(payload),
  }, payload);
  const data = JSON.parse(res.body);
  if (res.status !== 200) {
    throw new Error(data?.error?.message || JSON.stringify(data));
  }
  const text = data.choices?.[0]?.message?.content || "";
  return { text };
}

exports.handler = async (event) => {
  const corsHeaders = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  };

  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, headers: corsHeaders, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  const messages = body.messages;
  const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
  const GROQ_KEY = process.env.GROQ_API_KEY;

  // Try Anthropic first
  if (ANTHROPIC_KEY) {
    try {
      const result = await tryAnthropic(ANTHROPIC_KEY, messages);
      return {
        statusCode: 200,
        headers: corsHeaders,
        body: JSON.stringify({ content: [{ type: "text", text: result.text }] }),
      };
    } catch (e) {
      console.log("Anthropic failed:", e.message, "— trying Groq fallback");
    }
  }

  // Fall back to Groq
  if (GROQ_KEY) {
    try {
      const result = await tryGroq(GROQ_KEY, messages);
      return {
        statusCode: 200,
        headers: corsHeaders,
        body: JSON.stringify({ content: [{ type: "text", text: result.text }] }),
      };
    } catch (e) {
      return {
        statusCode: 500,
        headers: corsHeaders,
        body: JSON.stringify({ error: `Groq error: ${e.message}` }),
      };
    }
  }

  return {
    statusCode: 500,
    headers: corsHeaders,
    body: JSON.stringify({ error: "No API keys configured. Set ANTHROPIC_API_KEY or GROQ_API_KEY in Netlify environment variables." }),
  };
};

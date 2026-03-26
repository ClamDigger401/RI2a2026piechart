/**
 * netlify/functions/compose.js
 * Uses Groq API exclusively for letter composition.
 * Free tier at console.groq.com — no credit card needed.
 * Set GROQ_API_KEY in Netlify Environment Variables.
 */

const https = require("https");

exports.handler = async (event) => {
  const corsHeaders = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  };

  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const GROQ_KEY = process.env.GROQ_API_KEY;
  if (!GROQ_KEY) {
    return {
      statusCode: 500,
      headers: corsHeaders,
      body: JSON.stringify({ error: "GROQ_API_KEY not configured in Netlify environment variables" }),
    };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, headers: corsHeaders, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  const payload = JSON.stringify({
    model: "llama-3.3-70b-versatile",
    max_tokens: 1200,
    messages: body.messages,
  });

  return new Promise((resolve) => {
    const req = https.request({
      hostname: "api.groq.com",
      path: "/openai/v1/chat/completions",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${GROQ_KEY}`,
        "Content-Length": Buffer.byteLength(payload),
      },
    }, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          if (res.statusCode !== 200) {
            resolve({
              statusCode: res.statusCode,
              headers: corsHeaders,
              body: JSON.stringify({ error: parsed?.error?.message || JSON.stringify(parsed) }),
            });
            return;
          }
          const text = parsed.choices?.[0]?.message?.content || "";
          // Return in Anthropic-compatible format so letters.html works unchanged
          resolve({
            statusCode: 200,
            headers: corsHeaders,
            body: JSON.stringify({ content: [{ type: "text", text }] }),
          });
        } catch (e) {
          resolve({
            statusCode: 500,
            headers: corsHeaders,
            body: JSON.stringify({ error: `Parse error: ${e.message}` }),
          });
        }
      });
    });
    req.on("error", (e) => {
      resolve({
        statusCode: 500,
        headers: corsHeaders,
        body: JSON.stringify({ error: e.message }),
      });
    });
    req.write(payload);
    req.end();
  });
};

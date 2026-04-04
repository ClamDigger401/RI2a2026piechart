/**
 * netlify/functions/compose.js
 * Uses Groq API with automatic fallback across multiple free models.
 * Each model has its own daily token limit — cycling through them
 * maximizes free capacity before hitting any single limit.
 *
 * Free models and daily limits (approximate):
 *   llama-3.3-70b-versatile   — 100k tokens/day
 *   llama-3.1-8b-instant      — 500k tokens/day
 *   gemma2-9b-it              — 500k tokens/day
 *   mixtral-8x7b-32768        — 500k tokens/day
 *
 * Set GROQ_API_KEY in Netlify Environment Variables.
 */

const https = require("https");

const MODELS = [
  "llama-3.3-70b-versatile",
  "llama-3.1-8b-instant",
  "gemma2-9b-it",
  "mixtral-8x7b-32768",
];

function groqRequest(key, model, messages) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({
      model,
      max_tokens: 1200,
      messages,
    });

    const req = https.request({
      hostname: "api.groq.com",
      path: "/openai/v1/chat/completions",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${key}`,
        "Content-Length": Buffer.byteLength(payload),
      },
    }, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        try {
          const parsed = JSON.parse(data);
          resolve({ status: res.statusCode, parsed });
        } catch (e) {
          reject(new Error(`Parse error: ${e.message}`));
        }
      });
    });
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

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

  const messages = body.messages;
  let lastError = "";

  // Try each model in order — move to next if rate limited
  for (const model of MODELS) {
    try {
      const { status, parsed } = await groqRequest(GROQ_KEY, model, messages);

      if (status === 200) {
        const text = parsed.choices?.[0]?.message?.content || "";
        console.log(`Success with model: ${model}`);
        return {
          statusCode: 200,
          headers: corsHeaders,
          body: JSON.stringify({ content: [{ type: "text", text }] }),
        };
      }

      // Rate limit or other error — try next model
      const errMsg = parsed?.error?.message || JSON.stringify(parsed);
      console.log(`Model ${model} failed (${status}): ${errMsg} — trying next`);
      lastError = errMsg;

      // Only fall through on rate limit errors (429) or token limit errors
      const isRateLimit = status === 429 ||
        (errMsg && (errMsg.includes("rate limit") || errMsg.includes("tokens per") || errMsg.includes("TPM") || errMsg.includes("TPD")));

      if (!isRateLimit) {
        // Non-rate-limit error (auth, bad request, etc.) — don't retry
        return {
          statusCode: status,
          headers: corsHeaders,
          body: JSON.stringify({ error: errMsg }),
        };
      }

    } catch (e) {
      console.log(`Model ${model} threw: ${e.message}`);
      lastError = e.message;
    }
  }

  // All models exhausted
  return {
    statusCode: 429,
    headers: corsHeaders,
    body: JSON.stringify({
      error: `All free Groq models are currently rate limited. Please try again later or select fewer bills at once. Last error: ${lastError}`
    }),
  };
};

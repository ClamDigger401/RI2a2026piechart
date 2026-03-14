/**
 * netlify/functions/send.js
 * Proxy for Resend API — keeps API key server-side, avoids CORS.
 * Set RESEND_API_KEY in Netlify → Site Settings → Environment Variables.
 * Free tier: 3,000 emails/month, 100/day.
 */

const https = require("https");

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const RESEND_KEY = process.env.RESEND_API_KEY;
  if (!RESEND_KEY) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "RESEND_API_KEY not configured" }),
    };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  // Convert SendGrid payload format to Resend format
  const toAddresses = (body.personalizations?.[0]?.to || []).map(r =>
    r.name ? `${r.name} <${r.email}>` : r.email
  );

  // Resend free tier requires sending from onboarding@resend.dev
  // until a custom domain is verified — display name shows constituent name
  const fromAddress = body.from && body.from.name
    ? `${body.from.name} <onboarding@resend.dev>`
    : "onboarding@resend.dev";

  const replyTo = (body.reply_to && body.reply_to.email)
    ? body.reply_to.email
    : (body.from && body.from.email ? body.from.email : "");

  const textContent = (body.content || []).find(c => c.type === "text/plain");
  const text = textContent ? textContent.value : "";

  const resendPayload = JSON.stringify({
    from: fromAddress,
    to: toAddresses,
    reply_to: replyTo,
    subject: body.subject || "Constituent Letter",
    text: text,
  });

  return new Promise((resolve) => {
    const options = {
      hostname: "api.resend.com",
      path: "/emails",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + RESEND_KEY,
        "Content-Length": Buffer.byteLength(resendPayload),
      },
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        // Resend returns 200 on success; normalize to 202 so frontend logic works
        const statusCode = res.statusCode === 200 ? 202 : res.statusCode;
        resolve({
          statusCode,
          headers: { "Content-Type": "application/json" },
          body: data || JSON.stringify({ success: true }),
        });
      });
    });

    req.on("error", (err) => {
      resolve({
        statusCode: 500,
        body: JSON.stringify({ error: err.message }),
      });
    });

    req.write(resendPayload);
    req.end();
  });
};

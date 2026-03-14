/**
 * netlify/functions/send.js
 * Proxy for SendGrid API — keeps API key server-side, avoids CORS.
 * Set SENDGRID_API_KEY in Netlify → Site Settings → Environment Variables.
 */

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const SENDGRID_KEY = process.env.SENDGRID_API_KEY;
  if (!SENDGRID_KEY) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "SENDGRID_API_KEY not set in environment variables" })
    };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid JSON body" }) };
  }

  try {
    const response = await fetch("https://api.sendgrid.com/v3/mail/send", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${SENDGRID_KEY}`,
      },
      body: JSON.stringify(body),
    });

    if (response.status === 202) {
      return { statusCode: 202, body: JSON.stringify({ success: true }) };
    }

    const text = await response.text();
    return {
      statusCode: response.status,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: text }),
    };
  } catch (err) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: err.message }),
    };
  }
};

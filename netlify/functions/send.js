const https = require("https");

exports.handler = async (event) => {
  if (event.httpMethod !== "POST") {
    return { statusCode: 405, body: "Method Not Allowed" };
  }

  const SENDGRID_KEY = process.env.SENDGRID_API_KEY;
  if (!SENDGRID_KEY) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "SENDGRID_API_KEY not configured" }),
    };
  }

  let body;
  try {
    body = JSON.parse(event.body);
  } catch {
    return { statusCode: 400, body: JSON.stringify({ error: "Invalid JSON" }) };
  }

  const payload = JSON.stringify(body);

  return new Promise((resolve) => {
    const options = {
      hostname: "api.sendgrid.com",
      path: "/v3/mail/send",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${SENDGRID_KEY}`,
        "Content-Length": Buffer.byteLength(payload),
      },
    };

    const req = https.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => { data += chunk; });
      res.on("end", () => {
        resolve({
          statusCode: res.statusCode,
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

    req.write(payload);
    req.end();
  });
};

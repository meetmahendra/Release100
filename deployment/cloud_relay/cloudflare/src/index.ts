/**
 * Release100 Multi-Kiosk Cloudflare Edge Relay
 * Copyright 2026 Mahendra GURAV (Apache License 2.0)
 *
 * Provides dynamic multi-tenant / multi-kiosk WebSocket routing:
 * 1. Edge Webhook Ingress (Meta WhatsApp) with HMAC-SHA256 signature verification.
 * 2. Dynamic Durable Object routing per physical kiosk (/ws/:kioskId).
 * 3. Outbound WebSocket streaming to desktop supervisors, bypassing factory firewalls.
 */

export interface Env {
  RELAY_SESSIONS: DurableObjectNamespace;
  WHATSAPP_VERIFY_TOKEN: string;
  WHATSAPP_APP_SECRET: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // 1. Meta Webhook Verification Challenge (GET /webhook)
    if (request.method === "GET" && url.pathname === "/webhook") {
      const mode = url.searchParams.get("hub.mode");
      const token = url.searchParams.get("hub.verify_token");
      const challenge = url.searchParams.get("hub.challenge");

      if (mode === "subscribe" && token === env.WHATSAPP_VERIFY_TOKEN) {
        return new Response(challenge, { status: 200 });
      }
      return new Response("Forbidden", { status: 403 });
    }

    // 2. Inbound WhatsApp Message Notification (POST /webhook)
    if (request.method === "POST" && url.pathname === "/webhook") {
      const signature = request.headers.get("X-Hub-Signature-256") || "";
      const bodyText = await request.text();

      // Verify HMAC-SHA256 signature if secret is configured
      if (env.WHATSAPP_APP_SECRET) {
        const isValid = await verifyHmacSignature(bodyText, signature, env.WHATSAPP_APP_SECRET);
        if (!isValid) {
          return new Response("Invalid HMAC Signature", { status: 401 });
        }
      }

      let payload: any;
      try {
        payload = JSON.parse(bodyText);
      } catch {
        return new Response("Invalid JSON", { status: 400 });
      }

      // Resolve target kiosk identifier from payload or default
      const targetKioskId = resolveTargetKiosk(payload);

      // Route message to the specific kiosk's Durable Object session
      const doId = env.RELAY_SESSIONS.idFromName(targetKioskId);
      const sessionStub = env.RELAY_SESSIONS.get(doId);

      await sessionStub.fetch("http://internal/broadcast", {
        method: "POST",
        body: JSON.stringify({ kiosk_id: targetKioskId, payload }),
      });

      return new Response("EVENT_RECEIVED", { status: 200 });
    }

    // 3. Desktop Kiosk WebSocket Connection (GET /ws/:kioskId)
    if (url.pathname.startsWith("/ws/")) {
      const kioskId = url.pathname.replace("/ws/", "").trim();
      if (!kioskId) {
        return new Response("Missing kiosk identifier in URL path (e.g. /ws/NODE-PUNE-04)", { status: 400 });
      }

      const doId = env.RELAY_SESSIONS.idFromName(kioskId);
      const sessionStub = env.RELAY_SESSIONS.get(doId);
      return sessionStub.fetch(request);
    }

    // Health / Discovery endpoint
    return new Response(
      JSON.stringify({
        service: "Release100 Multi-Kiosk Cloud Relay",
        version: "1.2.0",
        status: "operational",
      }),
      {
        headers: { "Content-Type": "application/json" },
      }
    );
  },
};

/**
 * Durable Object managing live WebSocket connections for an individual kiosk.
 */
export class RelaySession implements DurableObject {
  private state: DurableObjectState;

  constructor(state: DurableObjectState) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // Broadcast incoming webhook frame to all connected kiosk clients
    if (request.method === "POST" && url.pathname === "/broadcast") {
      const body = await request.json();
      const message = JSON.stringify({ event: "whatsapp_message", body });

      const sockets = this.state.getWebSockets();
      for (const ws of sockets) {
        try {
          ws.send(message);
        } catch (err) {
          console.error("Failed to stream to client socket:", err);
        }
      }
      return new Response("OK", { status: 200 });
    }

    // Upgrade client connection to WebSocket
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    this.state.acceptWebSocket(server);
    server.send(JSON.stringify({ event: "connected", message: "Connected to Release100 Kiosk Relay Session." }));

    return new Response(null, { status: 101, webSocket: client });
  }

  // WebSocket Hibernation event handlers
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    try {
      const data = JSON.parse(typeof message === "string" ? message : new TextDecoder().decode(message));
      if (data.action === "ping") {
        ws.send(JSON.stringify({ event: "pong" }));
      }
    } catch {}
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string) {
    ws.close(code, reason);
  }
}

/**
 * Resolve target kiosk ID from WhatsApp message payload.
 */
function resolveTargetKiosk(payload: any): string {
  try {
    const entry = payload?.entry?.[0];
    const change = entry?.changes?.[0];
    const message = change?.value?.messages?.[0];
    const text = message?.text?.body || "";

    // If message contains explicit kiosk tag e.g. #kiosk:NODE-MUMBAI-08
    const match = text.match(/#kiosk:([A-Za-z0-9_-]+)/);
    if (match) {
      return match[1];
    }
  } catch {}

  // Fallback to default kiosk session
  return "NODE-PUNE-04";
}

/**
 * Helper: HMAC-SHA256 signature verifier using Web Crypto API.
 */
async function verifyHmacSignature(body: string, headerSig: string, secret: string): Promise<boolean> {
  if (!headerSig) return false;
  const cleanSig = headerSig.replace("sha256=", "");
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"]
  );
  const sigBytes = new Uint8Array(cleanSig.match(/.{1,2}/g)?.map((byte) => parseInt(byte, 16)) || []);
  return await crypto.subtle.verify("HMAC", key, sigBytes, encoder.encode(body));
}

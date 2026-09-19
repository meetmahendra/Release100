// Copyright 2026 Mahendra GURAV
// Licensed under the Apache License, Version 2.0

/**
 * Cloudflare Durable Object: RelaySession
 *
 * Implements the per-kiosk stateful WebSocket relay for multi-kiosk
 * bidirectional message routing. Each CaneBot kiosk maintains one
 * persistent Durable Object instance identified by its kiosk_id.
 *
 * Architecture (Plan 05 v1.2 §4):
 *   WhatsApp Cloud API → Cloudflare Worker (index.ts)
 *                          → RelaySession DO (relay_session.ts)
 *                          → Edge Kiosk (outbound WebSocket)
 *
 * Zero inbound ports required at the kiosk — the edge device opens an
 * outbound WebSocket to wss://relay.canectar.com/ws/{kiosk_id} and the
 * DO hibernates it until a message arrives.
 */

export interface Env {
  RELAY_SESSION: DurableObjectNamespace;
  API_SECRET: string;
}

/** Message envelope flowing between cloud and kiosk edge. */
interface RelayMessage {
  type: "inbound" | "outbound" | "ping" | "ack";
  kiosk_id: string;
  correlation_id: string;
  payload: unknown;
  timestamp_utc: string;
}

/**
 * RelaySession — one DO instance per kiosk_id.
 *
 * State machine:
 *   IDLE         → kiosk not connected (messages queued in memory)
 *   CONNECTED    → kiosk WebSocket is live (messages forwarded immediately)
 *   HIBERNATING  → WebSocket hibernation API active (Cloudflare zero-cost idle)
 */
export class RelaySession implements DurableObject {
  private state: DurableObjectState;
  private kioskSocket: WebSocket | null = null;
  private messageQueue: RelayMessage[] = [];
  private kioskId: string = "unknown";
  private lastPingAt: number = Date.now();

  constructor(state: DurableObjectState, _env: Env) {
    this.state = state;
    // Restore kiosk_id from persistent storage across hibernation cycles
    this.state.blockConcurrencyWhile(async () => {
      this.kioskId = (await this.state.storage.get<string>("kiosk_id")) ?? "unknown";
    });
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // WebSocket upgrade request from the edge kiosk
    if (request.headers.get("Upgrade") === "websocket") {
      return this.handleKioskConnect(request, url);
    }

    // HTTP POST from Cloudflare Worker (inbound WhatsApp message to forward)
    if (request.method === "POST" && url.pathname === "/send") {
      return this.handleInboundFromCloud(request);
    }

    // HTTP GET status endpoint
    if (request.method === "GET" && url.pathname === "/status") {
      return this.handleStatus();
    }

    return new Response("Not Found", { status: 404 });
  }

  // ── Kiosk WebSocket Registration ──────────────────────────────────────────

  private async handleKioskConnect(
    request: Request,
    url: URL
  ): Promise<Response> {
    const kioskId = url.searchParams.get("kiosk_id") ?? "unknown";
    this.kioskId = kioskId;
    await this.state.storage.put("kiosk_id", kioskId);

    const upgradeHeader = request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader !== "websocket") {
      return new Response("Expected WebSocket upgrade", { status: 426 });
    }

    const [client, server] = Object.values(new WebSocketPair()) as [WebSocket, WebSocket];

    // Use Cloudflare WebSocket hibernation API for zero-cost idle connections
    this.state.acceptWebSocket(server, ["kiosk"]);
    this.kioskSocket = server;

    // Drain any queued messages accumulated while kiosk was offline
    for (const msg of this.messageQueue) {
      try {
        server.send(JSON.stringify(msg));
      } catch {
        // Socket may have failed during drain — leave remaining in queue
        break;
      }
    }
    this.messageQueue = [];

    return new Response(null, { status: 101, webSocket: client });
  }

  // ── Inbound Message from WhatsApp Cloud API ───────────────────────────────

  private async handleInboundFromCloud(request: Request): Promise<Response> {
    let message: RelayMessage;
    try {
      message = (await request.json()) as RelayMessage;
    } catch {
      return new Response("Invalid JSON payload", { status: 400 });
    }

    message.timestamp_utc = new Date().toISOString();

    const sockets = this.state.getWebSockets("kiosk");
    const activeSocket = sockets.find((ws) => ws.readyState === WebSocket.OPEN);

    if (activeSocket) {
      // Kiosk is connected — deliver immediately
      activeSocket.send(JSON.stringify(message));
      return new Response(
        JSON.stringify({ status: "delivered", correlation_id: message.correlation_id }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    // Kiosk offline — queue for delivery when it reconnects
    this.messageQueue.push(message);

    // Cap in-memory queue at 200 messages (oldest dropped)
    if (this.messageQueue.length > 200) {
      this.messageQueue.shift();
    }

    return new Response(
      JSON.stringify({
        status: "queued",
        queue_depth: this.messageQueue.length,
        correlation_id: message.correlation_id,
      }),
      { status: 202, headers: { "Content-Type": "application/json" } }
    );
  }

  // ── Status Endpoint ───────────────────────────────────────────────────────

  private handleStatus(): Response {
    const sockets = this.state.getWebSockets("kiosk");
    const connected = sockets.some((ws) => ws.readyState === WebSocket.OPEN);
    return new Response(
      JSON.stringify({
        kiosk_id: this.kioskId,
        connected,
        queue_depth: this.messageQueue.length,
        last_ping_at: new Date(this.lastPingAt).toISOString(),
      }),
      { headers: { "Content-Type": "application/json" } }
    );
  }

  // ── WebSocket Hibernation Handlers ────────────────────────────────────────

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    this.lastPingAt = Date.now();
    try {
      const parsed = JSON.parse(message as string) as RelayMessage;
      if (parsed.type === "ping") {
        ws.send(JSON.stringify({ type: "ack", kiosk_id: this.kioskId, timestamp_utc: new Date().toISOString() }));
      }
      // Future: forward kiosk→cloud outbound messages to a webhook
    } catch {
      // Ignore malformed messages
    }
  }

  async webSocketClose(
    _ws: WebSocket,
    _code: number,
    _reason: string,
    _wasClean: boolean
  ): Promise<void> {
    this.kioskSocket = null;
  }

  async webSocketError(_ws: WebSocket, _error: unknown): Promise<void> {
    this.kioskSocket = null;
  }
}

// A stand-in for the full corpus's Worker (cloud/corpus), for cloud/api/test/run.sh: POST /api/call answered as
// ChatRuntime.call answers it (src/taochronos/chat/__init__.py: shape) — and, by the query, as the corpus answers
// when a tool refuses its arguments before it runs ("refuse"), when a tool fails while it runs ("raise"), while its
// container cannot be started (the call never sent: "down"), when the container goes away under the call ("gone"), or
// past the API's time ("slow"); a slow call the API gives up is ended here too, and says so in the log run.sh reads.
export default {
  async fetch(request) {
    const body = await request.json();
    const q = body.arguments?.query || body.arguments?.quote || "";
    const starting = { error: "starting", starting: true };
    if (q === "down") return Response.json(starting, { status: 503, headers: { "Retry-After": "7", "X-TC-Call": "unsent" } });
    if (q === "gone") return Response.json(starting, { status: 503, headers: { "Retry-After": "7" } });
    if (q === "slow") {
      request.signal.addEventListener("abort", () => console.log("stand-in corpus: a slow call was aborted"));
      await new Promise((r) => setTimeout(r, 8000));
    }
    if (q === "refuse") return Response.json({ ok: false, ran: false, tool: body.name, error: "invalid arguments: $.k: 500 > maximum 100", text: "ERROR", citations: [] });
    if (q === "raise") return Response.json({ ok: false, ran: true, tool: body.name, error: "PassageNotFound: no passage 'x'", text: "ERROR", citations: [] });
    return Response.json({ ok: true, tool: body.name, duration_ms: 12.5, text: `found for ${q}`,
      result: { hits: [{ passage_id: "shl:12", text: "太阳中风…桂枝汤主之" }], asked: body.arguments }, citations: [{ passage_id: "shl:12" }],
      summary: "1 hit", receipt: { actor: "agent:chat", hash: "deadbeef" } }, { headers: { "X-TC-Corpus": "live" } });
  },
};

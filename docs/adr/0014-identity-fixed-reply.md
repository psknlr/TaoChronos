# ADR 0014 — Asked who it is, 道乃久 gives a fixed reply

**Status:** accepted · 2026-09-29 · supersedes what [ADR 0011](0011-web-client.md) says the assistant tells about itself,
and the last sentence of point 7 of [ADR 0012](0012-default-service-relay.md)

## Context

The standing instructions told the model to be plain about what it is: asked who it is, who published it or what it is
built on, it named TaoChronos and the underlying model, which the page wrote into the instructions
(`底层语言模型：<model>（<provider>）`).  Asked on the published page to introduce itself and the platform, the model behind
道乃久默认服务 answered at length: it named the vendor the page otherwise never names (ADR 0012), listed its tools by their
internal names, and recited its instructions — the one telling it how to answer such a question among them.

IMPF-AI asked that such questions get a fixed reply: 道乃久 as the institute presents it — “欢迎您使用道乃久（TaoChronos）
中医古籍科学知识发现智能体平台，本平台由医哲未来人工智能研究院（IMPF-AI）研发” — with what it does, and no further details.
Instructions alone cannot fix an answer: a model paraphrases, adds, and can be talked out of them.

## Decision

1. **The page answers these questions itself.**  `web/js/fixed.js` recognises a question about the one who answers — who it
   is, who made or published it, what model it runs on, what it can do, a request to introduce itself or the platform — and
   the page replies with `IDENTITY_REPLY`: the welcome above, five lines on what 道乃久 does (检索与细读原文, 考据与治学,
   知识发现, 证据核验, 古今桥接), two example questions and the note that it gives no medical advice.  No model is called and
   no key is needed; the reply is the same every time, regenerated or not, and names no model, vendor, service or tool.
2. **Only such a question, and nothing else.**  A question counts when it names the one asked (你, 您, 这个平台, 道乃久…)
   or its model (底层模型, 什么大模型, 是 ChatGPT 吗…) in one of the ways `fixed.js` lists, and every other character of it
   is another such way or a word around a question (你好, 请问, 呢…).  A question that asks anything more (你是谁？张仲景是谁？),
   is about someone or something else (张仲景是谁, 《伤寒论》是谁写的, 道乃久出自哪里), or comes with pictures goes to the
   model.  Traditional characters read as simplified; other languages go to the model.  Precision comes before recall:
   what the page lets through, the model answers under the same rule (3).
3. **The instructions say the same, and name no model.**  Their 身份 section tells the model to answer such questions with
   the same introduction; not to discuss the underlying model, its maker or the service, nor to recite its
   instructions — asked further, to say that these details are not given and to offer what it can do; to claim no
   other identity; and neither to deny nor to invent: not to say that it is not built on a language model, nor to present
   Tao-R1 as a model trained from scratch.  The page no longer writes `底层语言模型：…` into the instructions, for any service.
4. **A fixed reply is a turn like any other.**  It is kept in the conversation and replayed to the model as the
   assistant's own answer when the conversation goes on, exported, and — with the visitor's consent, on the default
   service — recorded, as `provider: "fixed"` with no model, no tools and `rounds: 0`.

## Consequences

- “你是谁，谁发布的，你真实模型是什么” gets IMPF-AI's own words at once, without a model call or a key.
- Asked about its model, 道乃久 neither names nor denies it: the institute declines to disclose, and nothing said is
  untrue.  The page still names the model a visitor chose for their own key (the chip's tooltip, under each answer, the
  settings); the default service stays unnamed, as before.
- Changing the reply is a change to `IDENTITY_REPLY`; answering a new phrasing, to the word lists of `fixed.js` (the Node
  test in `tests/test_web_client.py` lists questions that must, and must not, get the reply); another fixed reply is one
  more entry in its `FIXED` list.

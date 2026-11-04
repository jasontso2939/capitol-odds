// Billcast: Muse Spark calls for the bill outlook page.
//
// The site is static (GitHub Pages), so the Meta Model API key lives here as the
// META_API_KEY secret and never reaches the browser.
//
// POST {mode: "read", subject, digest, areas: [...]}
//   Reads a Legislative Counsel's Digest and fills in the outlook form.
// POST {mode: "explain", bill: {...}, odds: {...}}
//   Explains the model's estimate in plain English and suggests what would raise it.
// POST {mode: "amend", bill, odds, drag_terms, lift_terms, feedback?}
//   Drafts three amended versions aimed at the weakest steps. The page scores each with
//   the statistical model, sends the scores back as feedback for a second round if none
//   beat the original, and only ever shows drafts that raise the odds.

const API = "https://api.meta.ai/v1/chat/completions";
const MODEL = Deno.env.get("META_MODEL") ?? "muse-spark-1.3";
const ALLOWED = [
  "https://jasontso2939.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];
const MAX_TEXT = 6000;

function cors(origin: string | null) {
  const ok = origin && ALLOWED.includes(origin) ? origin : ALLOWED[0];
  return {
    "Access-Control-Allow-Origin": ok,
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}

const clip = (s: unknown, n = MAX_TEXT) => String(s ?? "").slice(0, n);

const READ_PROMPT = `You read California bills for a tool that estimates a bill's chance of becoming law.
Given a bill's subject line and its Legislative Counsel's Digest (or a plain description), return JSON with:
- "subject": a short subject line in Legislative Counsel style ("Topic: subtopic"). Keep the user's if given.
- "policy_area": the single best first policy committee, copied exactly from the list provided.
- "fiscal_committee", "appropriation", "local_program", "taxlevy", "urgency", "supermajority", "spot_bill": true or false.
  Take these from the digest key line when present ("Vote: majority. Appropriation: no. Fiscal committee: yes. Local program: no.").
  Two-thirds vote means supermajority true. A spot bill only states intent or makes nonsubstantive changes.
- "evidence": an object mapping each true flag to the short phrase in the text that supports it.
- "confidence": "high" if the digest key line was present, otherwise "medium" or "low".
Return only the JSON object.`;

const EXPLAIN_PROMPT = `You explain a statistical estimate of a California bill's chance of being signed into law, for legislative staff and advocates.
You get the bill's subject and summary, the model's overall estimate and likely range, the chance of clearing each step, the inputs that move the estimate most (in percentage points), and how similar past bills ended.
Write for a smart reader who is not a statistician. Be specific to this bill. Do not invent facts about the bill, its author, or real people, and do not claim to know politics the model cannot see.
Return JSON with:
- "headline": one sentence on where this bill stands.
- "why": 2 to 3 sentences on what drives the estimate, naming the biggest factors and the weakest step.
- "risks": up to 3 short items, each a concrete reason a bill like this tends to stall at its weakest steps, grounded in the summary.
- "improve": up to 3 short, practical changes to drafting or strategy that the inputs suggest would raise the odds (for example narrowing scope to avoid a fiscal referral, adding a coauthor from the other party, introducing earlier). Say which input each one changes.
- "unseen": one sentence on what the model cannot see that matters most for this bill.
Plain sentences, no markdown, no em dashes. Return only the JSON object.`;

const AMEND_PROMPT = `You are an experienced California legislative staffer amending a bill so it is more likely to be signed.
You get the bill, the model's estimate, each step's chance, the inputs that move the estimate most, and "drag_terms" and "lift_terms": words and phrases in the current digest that the model's text reader scores as lowering or raising the odds.
A statistical model will score every draft you write. Only drafts that score higher than the original are shown, so aim for real improvement.

Write 3 different amended drafts, each using a different strategy, for example:
- narrow the scope or make it a pilot or phase-in,
- remove the cost driver (appropriation, new penalty or new crime, new state program) so it avoids a fiscal referral or a state-mandated local program,
- restructure as reporting, guidance or a sunset-limited program.
Rules:
- Keep the bill's core purpose. Each change must be a real policy amendment a committee would accept, not word games.
- Change only the sentences you amend. Keep every other sentence of the digest word for word, because rewording unchanged parts moves the score at random.
- Prefer removing or softening the drag_terms' underlying provisions over adding new provisions.
- odds.flag_effects says exactly what the model does when each fiscal flag flips. Follow it, even when it surprises you: if removing a flag lowers the odds, keep that provision.
- Do not add a new appropriation, penalty, crime, tax, urgency clause or two-thirds vote.
- Each digest ends with an updated key line in the form "Vote: majority. Appropriation: no. Fiscal committee: yes. State-mandated local program: no."
If "feedback" is present, it lists your earlier drafts with the model's score for each and how each step moved. Learn from it: keep what raised a step, drop what lowered one, and write 3 new drafts that beat the original.

Return JSON: {"drafts": [ {"strategy": short name, "subject": amended subject line, "digest": amended digest,
"fiscal_committee", "appropriation", "local_program", "taxlevy", "urgency", "supermajority", "spot_bill": true or false for the amended bill,
"changes": up to 3 short items, each one amendment and the step it helps, "tradeoff": one sentence on what the bill gives up} ]}
Plain sentences, no markdown, no em dashes. Return only the JSON object.`;

// The single-draft prompt the previous page version uses, kept until that page is replaced.
const AMEND_PROMPT_V1 = `You are an experienced California legislative staffer amending a bill to improve its chance of being signed.
Write a realistic amended version that keeps the bill's core purpose but addresses its weakest steps.
Return JSON with "subject", "digest" (ending with an updated key line like "Vote: majority. Appropriation: no. Fiscal committee: yes. State-mandated local program: no."), the booleans "fiscal_committee", "appropriation", "local_program", "taxlevy", "urgency", "supermajority", "spot_bill", "changes" (up to 4 short items) and "tradeoff" (one sentence).
Plain sentences, no markdown, no em dashes. Return only the JSON object.`;

async function muse(system: string, user: unknown, key: string, maxTokens = 1500) {
  const r = await fetch(API, {
    method: "POST",
    headers: { "Authorization": `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: "developer", content: system },
        { role: "user", content: JSON.stringify(user) },
      ],
      response_format: { type: "json_object" },
      reasoning_effort: "low",
      max_completion_tokens: maxTokens,
    }),
  });
  const body = await r.text();
  if (!r.ok) throw new Error(`Model API ${r.status}: ${body.slice(0, 300)}`);
  const res = JSON.parse(body);
  const text = res.choices?.[0]?.message?.content ?? "";
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("Model returned no JSON");
  const out = JSON.parse(m[0]);
  out.usage = res.usage ? { input: res.usage.prompt_tokens, output: res.usage.completion_tokens } : null;
  return out;
}

Deno.serve(async (req) => {
  const h = cors(req.headers.get("origin"));
  if (req.method === "OPTIONS") return new Response("ok", { headers: h });
  const json = (o: unknown, status = 200) =>
    new Response(JSON.stringify(o), { status, headers: { ...h, "Content-Type": "application/json" } });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const key = Deno.env.get("META_API_KEY");
  if (!key) return json({ error: "META_API_KEY is not set on the server" }, 503);

  let b: any;
  try { b = await req.json(); } catch { return json({ error: "Bad JSON" }, 400); }

  try {
    if (b.mode === "read") {
      const areas: string[] = Array.isArray(b.areas) ? b.areas.slice(0, 80).map(String) : [];
      if (!clip(b.digest).trim()) return json({ error: "Paste a digest or description first" }, 400);
      const out = await muse(READ_PROMPT, {
        subject: clip(b.subject, 200), digest: clip(b.digest), policy_area_choices: areas,
      }, key);
      if (areas.length && !areas.includes(out.policy_area)) out.policy_area = null;
      return json({ model: MODEL, ...out });
    }
    if (b.mode === "explain") {
      const out = await muse(EXPLAIN_PROMPT, {
        bill: { ...b.bill, digest: clip(b.bill?.digest), subject: clip(b.bill?.subject, 200) },
        odds: b.odds,
      }, key);
      return json({ model: MODEL, ...out });
    }
    if (b.mode === "amend" && b.v !== 2) {
      const out = await muse(AMEND_PROMPT_V1, { bill: b.bill, odds: b.odds }, key);
      return json({ model: MODEL, ...out });
    }
    if (b.mode === "amend") {
      const out = await muse(AMEND_PROMPT, {
        bill: { ...b.bill, digest: clip(b.bill?.digest), subject: clip(b.bill?.subject, 200) },
        odds: b.odds,
        drag_terms: Array.isArray(b.drag_terms) ? b.drag_terms.slice(0, 12) : [],
        lift_terms: Array.isArray(b.lift_terms) ? b.lift_terms.slice(0, 12) : [],
        feedback: Array.isArray(b.feedback) ? b.feedback.slice(0, 6) : undefined,
      }, key, 3500);
      out.drafts = Array.isArray(out.drafts) ? out.drafts.slice(0, 3) : [];
      return json({ model: MODEL, ...out });
    }
    return json({ error: "mode must be read, explain or amend" }, 400);
  } catch (e) {
    return json({ error: String((e as Error).message ?? e) }, 502);
  }
});

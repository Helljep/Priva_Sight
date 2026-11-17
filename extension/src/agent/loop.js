// loop.js - the agent: perceive -> plan -> act, repeated until done.
//
// Privacy rules enforced here:
//   * the user's goal is sanitised like any other text before it is sent
//   * if the privacy gate blocks a step the run STOPS (fail closed) - it never
//     "tries again without redaction"
//   * the planner only ever returns tokens; real values are substituted from
//     the local vault at the moment of typing

import { perceive, ensureContentScript, sendToTab } from './pipeline.js';
import { planStep } from './api.js';
import { sanitizeString } from '../redact/sanitize.js';

const SETTLE_MS = 900;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * @param opts.onEvent  (event) => void   events: step, blocked, action, done, error
 * @param opts.signal   AbortSignal to stop the run
 * @returns {{ status: 'done'|'failed'|'blocked'|'max_steps'|'stopped'|'error', steps, answer? }}
 */
export async function runAgent(opts) {
  const { goal, tabId, windowId, vault, layers, tools, serverUrl, maxSteps = 15, onEvent = () => {}, signal } = opts;
  const safeGoal = await sanitizeString(goal, vault, layers);
  const history = [];

  for (let step = 1; step <= maxSteps; step++) {
    if (signal && signal.aborted) return { status: 'stopped', steps: step - 1 };
    try {
      const p = await perceive({ tabId, windowId, vault, layers, tools });
      onEvent({ type: 'step', step, stats: p.stats, timingMs: p.timingMs, gate: p.gate });

      // `unsafeBaseline` exists ONLY for the evaluation harness, to measure how
      // much an unprotected agent leaks. It is never reachable from the UI.
      if (opts.unsafeBaseline) p.gate = { ok: true, reasons: [] };

      if (!p.gate.ok) {
        onEvent({ type: 'blocked', step, reasons: p.gate.reasons });
        return { status: 'blocked', steps: step, reasons: p.gate.reasons };
      }

      const request = { goal: safeGoal, history, ...p.payloadParts, screenshot: p.screenshot };
      const plan = await planStep(serverUrl, request, p.gate);
      const action = plan.action;
      onEvent({ type: 'action', step, action, thought: plan.thought });

      if (action.type === 'done') { onEvent({ type: 'done', answer: action.answer }); return { status: 'done', steps: step, answer: action.answer }; }
      if (action.type === 'fail') { onEvent({ type: 'error', message: action.reason }); return { status: 'failed', steps: step, reason: action.reason }; }

      // Resolve tokens locally, right before the action touches the page.
      if (action.type === 'navigate' && !/^https?:\/\//i.test(action.url || '')) {
        onEvent({ type: 'error', message: 'refused non-http(s) navigation' });
        history.push('navigate refused'); // planner may retry differently
        continue;
      }
      const real = { ...action };
      if (typeof real.text === 'string') real.text = vault.resolve(real.text);
      await ensureContentScript(tabId);
      const result = await sendToTab(tabId, { ps: 'act', action: real });
      history.push(describe(action, result)); // history keeps tokens, never real values
      if (!result.ok) onEvent({ type: 'error', message: result.error });
      await sleep(SETTLE_MS);
    } catch (err) {
      if (err.code === 'PII_REJECTED') {
        onEvent({ type: 'blocked', step, reasons: [{ kind: 'server-rejected', detail: err.detail }] });
        return { status: 'blocked', steps: step };
      }
      onEvent({ type: 'error', message: err.message });
      return { status: 'error', steps: step, reason: err.message };
    }
  }
  return { status: 'max_steps', steps: maxSteps };
}

function describe(action, result) {
  const bits = [action.type];
  if (action.id !== undefined) bits.push(`#${action.id}`);
  if (action.text) bits.push(JSON.stringify(action.text)); // token form, e.g. "[EMAIL_1]"
  if (action.url) bits.push(action.url);
  bits.push(result && result.ok ? 'ok' : `failed: ${result && result.error}`);
  return bits.join(' ');
}

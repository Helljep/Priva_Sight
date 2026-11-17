// name_heuristic.js
// Fallback name detector used when the fine-tuned BERT NER model is not
// installed. It is much weaker than the model (see docs) but means the
// extension still protects names out of the box.
//
// Rules:
//   1. A run of 2-4 capitalised words where at least one is a known Indian
//      first name or surname  ->  NAME
//   2. A capitalised word right after a title (Mr, Mrs, Dr, Shri, Smt...) -> NAME
//   3. A capitalised word right after a label ("Name:", "Patient:", "Dear") -> NAME
//
// scan(text) -> [{ start, end, type:'NAME', value, source:'name-heuristic' }]

const FIRST = `aarav aditya akash akshay amit amrita ananya anil anita anjali ankit anushka arjun arun aryan asha ashok
bhavya chetan deepa deepak devika dhruv divya gaurav geeta gopal hari harish isha ishaan jayanth jayant kabir kamala kavita
karthik kiran krishna kunal lakshmi lalita madhav mahesh manoj meera mohan mukesh nandini naveen neha nikhil nisha nishmith
pooja pradeep prakash pranav priya rahul raj rajesh rakesh ramesh rani ravi rekha rohan rohit sachin sandeep sanjay sanjana
sarita saurabh shreya shruti siddharth sneha sonia srinivas subhash sunil suraj suresh sushma swati tanvi tara uday varun
vijay vikram vinay vivek yash zoya sarumathiy`.split(/\s+/);

const LAST = `agarwal bhat chatterjee chauhan das desai dubey gupta iyer jain joshi kapoor kulkarni kumar malhotra menon mishra
nair naidu pandey patel pillai rao reddy saxena sharma shetty singh sinha srinivasan thakur tiwari verma yadav
gowda hegde murthy bose banerjee mukherjee`.split(/\s+/);

const FIRST_SET = new Set(FIRST);
const LAST_SET = new Set(LAST);
const TITLES = '(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Sri|Prof|Master)\\.?';
const LABELS = '(?:Name|Full name|Patient|Employee|Account holder|Customer|Dear|Hello|Hi|Welcome|Beneficiary|Payee|From|To|Sender|Recipient)';
const CAP = '[A-Z][a-z]{1,}';
// Capitalised UI words that often follow a label but are never names.
const NOT_NAMES = new Set(`amount date number account address email phone mobile password username details info status
  type name id code balance total price quantity description message subject department city state country`.split(/\s+/));

function isKnown(word) {
  const w = word.toLowerCase();
  return FIRST_SET.has(w) || LAST_SET.has(w);
}

export function scan(text, context = '') {
  // `context` is the text that appeared just before this run on the page
  // (e.g. "Hello" in <span>Hello</span><b>Ishaan</b>). It can satisfy a
  // title/label rule but names inside it are not reported again.
  const ctx = context ? context.slice(-30) + ' ' : '';
  return scanFull(ctx + text, ctx.length).map((m) => ({ ...m, start: m.start - ctx.length, end: m.end - ctx.length }));
}

function scanFull(text, minStart) {
  const out = [];

  // Rule 1: capitalised word runs containing a known name word.
  const runRe = new RegExp(`\\b${CAP}(?:\\s+(?:[A-Z]\\.|${CAP})){0,3}\\b`, 'g');
  let m;
  while ((m = runRe.exec(text)) !== null) {
    // Trim leading/trailing words that are not names ("Welcome Rohan Sharma" -> "Rohan Sharma").
    const parts = [...m[0].matchAll(/\S+/g)].map((x) => ({ w: x[0], at: m.index + x.index }));
    const known = (p) => isKnown(p.w.replace('.', ''));
    while (parts.length && !known(parts[0])) parts.shift();
    while (parts.length && !known(parts[parts.length - 1])) parts.pop();
    if (parts.length >= 2) {
      const start = parts[0].at;
      const end = parts[parts.length - 1].at + parts[parts.length - 1].w.length;
      out.push({ start, end, type: 'NAME', value: text.slice(start, end), source: 'name-heuristic' });
    }
  }

  // Rules 2 and 3: title / label context for a single (or multi) word name.
  const ctxRe = new RegExp(`(?:\\b${TITLES}\\s+|\\b${LABELS}\\s*[:,-]?\\s+)(${CAP}(?:\\s+${CAP}){0,2})`, 'g');
  while ((m = ctxRe.exec(text)) !== null) {
    const value = m[1];
    const start = m.index + m[0].length - value.length;
    if (NOT_NAMES.has(value.split(/\s+/)[0].toLowerCase())) continue;
    if (!out.some((o) => start < o.end && o.start < start + value.length)) {
      out.push({ start, end: start + value.length, type: 'NAME', value, source: 'name-heuristic' });
    }
  }
  return out.filter((m) => m.start >= minStart).sort((a, b) => a.start - b.start);
}

"""
gen_ner_data.py - synthetic UI snippets for fine-tuning the Indian-name NER model.

Why synthetic: real UIs full of real names would be personal data. Instead we
fill ~40 realistic UI templates (labels, greetings, table cells, e-mail
headers, chat lines ...) with random Indian names and add HARD NEGATIVES
(city / bank / product / street names that look like names but are not).

Output (JSONL, one example per line, BIO tags):
    {"tokens": ["Welcome", ",", "Rohan", "Sharma"], "labels": ["O","O","B-PER","I-PER"]}

Run:  python training/gen_ner_data.py --n 24000 --out training/data/ner_train.jsonl
The held-out test set uses names that never appear in training (--holdout).
"""
import argparse
import json
import random
import re
from pathlib import Path

FIRST_TRAIN = """Aarav Vivaan Aditya Sai Arjun Reyansh Krishna Ishaan Rohan Kabir Ananya Diya Saanvi Aadhya Myra Navya Kavya Riya Meera
Harsh Tejas Yash Nitin Mohit Pranav Dev Ritvik Shalini Pallavi Radhika Swarna Bhavna Indira Usha Vandana Zoya Fatima Imran Salman
Gurpreet Harpreet Jaspreet Manpreet Thomas Joseph Abraham Mathew Suresh Ramesh Mahesh Ganesh Lakshmi Padma Sunita Anita Rekha Geeta
Deepak Rajesh Sanjay Vijay Anil Sunil Manoj Ashok Rakesh Naveen Srinivas Venkat Karthik Murali Sridhar Balaji Hari Gopal Mohan""".split()
LAST_TRAIN = """Sharma Verma Gupta Iyer Nair Reddy Rao Patel Shah Mehta Kulkarni Deshpande Bhat Shetty Gowda Naidu Menon Pillai Das Roy
Khan Ansari Qureshi Singh Gill Sandhu Fernandes DSouza Varghese Agarwal Jain Joshi Kapoor Malhotra Chopra Bhatt Mishra Pandey Tiwari
Yadav Chauhan Thakur Saxena Banerjee Mukherjee Chatterjee Bose Ghosh Sen Dutta Hegde Murthy Acharya Prabhu Kamath Pai""".split()
# Names used ONLY in the held-out test set, so test F1 measures generalisation.
FIRST_TEST = "Aryan Tanvi Nikhil Sneha Varun Pooja Chetan Devika Kunal Sanjana Ishita Lakshya Mrinal Trisha Vedant".split()
LAST_TEST = "Bhargava Chandran Dhillon Gadkari Hiremath Jhaveri Khanna Lamba Mathur Nambiar Oberoi Rastogi Sethi Trivedi Wagle".split()

HARD_NEGATIVES = ["Bengaluru", "Mumbai", "Chennai", "Hyderabad", "Kolkata", "Pune", "Gandhi Road", "Nehru Nagar", "State Bank",
                  "Punjab National Bank", "Rose Garden Layout", "Church Street", "Park Avenue", "Lake View", "Temple Street",
                  "Wireless Mouse", "USB-C Cable", "Net Banking", "Fund Transfer", "Savings Account", "Team Sync", "Help Center",
                  "Terms and Conditions", "Privacy Policy", "Order History", "Account Summary", "Karnataka", "Tamil Nadu", "Maharashtra",
                  "Monday", "October", "Engineering", "Customer Care", "General Medicine", "City Hospital", "Quick Links"]

TEMPLATES = [
    "Welcome, {n}", "Hello {n}!", "Hi {n}, your order has shipped", "Dear {n},", "Patient: {n}", "Name: {n}",
    "Account holder: {n}", "Beneficiary: {n}", "Payee: {n}", "Employee: {n} (Engineering)", "Logged in as {n}",
    "From: {n} <mail@example.test>", "To: {n}", "Sent by {n} on 12 Oct", "{n} joined the meeting", "{n} (host)",
    "Reply from {n}", "Appointment with Dr. {l} on Monday", "Mr. {n}", "Mrs. {n}", "Smt. {n}", "Shri {n}",
    "Transfer to {n} successful", "Contact {n} for details", "Signed, {n}", "Cardholder {n}", "Delivered to {n}",
    "UPI to {n}", "Salary credit - {n}", "Referred by {n}", "Profile of {n}", "{n}'s account", "Booking confirmed for {n}",
    "Meeting with {n} and {n2}", "Chat with {n}", "Attendees: {n}, {n2}", "Doctor: Dr. {n}",
]
NEG_TEMPLATES = ["Welcome to {x}", "Open {x}", "Go to {x}", "{x} settings", "Search in {x}", "Visit {x} today", "Powered by {x}"]


def person(first, last, rng):
    return rng.choice([f'{rng.choice(first)} {rng.choice(last)}', rng.choice(first), f'{rng.choice(first)} {rng.choice(last)}'])


def tag(template_text, spans):
    """Tokenise a sentence and BIO-tag tokens that fall inside PER spans."""
    tokens, labels = [], []
    for m in re.finditer(r"\w+(?:'\w+)?|[^\w\s]", template_text):
        tok, s, e = m.group(0), m.start(), m.end()
        inside = [i for i, (a, b) in enumerate(spans) if s >= a and e <= b]
        if inside:
            first_tok = s == spans[inside[0]][0] or template_text[spans[inside[0]][0]:s].strip() == ''
            labels.append('B-PER' if first_tok else 'I-PER')
        else:
            labels.append('O')
        tokens.append(tok)
    return tokens, labels


def render(template, fill):
    """Fill {n}/{n2}/{l}/{x} and return (text, [(start,end) of PER spans])."""
    out, spans, pos = '', [], 0
    for m in re.finditer(r'\{(\w+)\}', template):
        out += template[pos:m.start()]
        value, is_per = fill[m.group(1)]
        if is_per:
            spans.append((len(out), len(out) + len(value)))
        out += value
        pos = m.end()
    return out + template[pos:], spans


def make(rng, first, last):
    if rng.random() < 0.15:  # hard negative, no PER at all
        text, spans = render(rng.choice(NEG_TEMPLATES), {'x': (rng.choice(HARD_NEGATIVES), False)})
    else:
        fill = {'n': (person(first, last, rng), True), 'n2': (person(first, last, rng), True), 'l': (rng.choice(last), True)}
        text, spans = render(rng.choice(TEMPLATES), fill)
    # random casing noise so the model does not rely on perfect capitalisation
    if rng.random() < 0.05:
        text = text.upper()
        spans = [(a, b) for a, b in spans]
    tokens, labels = tag(text, spans)
    return {'tokens': tokens, 'labels': labels}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=24000)
    ap.add_argument('--out', default='training/data/ner_train.jsonl')
    ap.add_argument('--holdout', action='store_true', help='generate the test set with unseen names')
    ap.add_argument('--seed', type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed + (1000 if args.holdout else 0))
    first, last = (FIRST_TEST, LAST_TEST) if args.holdout else (FIRST_TRAIN, LAST_TRAIN)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8') as f:
        for _ in range(args.n):
            f.write(json.dumps(make(rng, first, last), ensure_ascii=False) + '\n')
    print(f'wrote {args.n} examples to {out}')


if __name__ == '__main__':
    main()

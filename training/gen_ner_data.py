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


# --- Negatives: ordinary page text that contains NO person ------------------------------------
# v1 of the fine-tuned model flagged many such words as names (precision 50.7% vs 78.8% for the
# public baseline). These are written independently of the test sites so the eval stays honest.
UI_WORDS = """Dashboard Profile Settings Logout Login Register Home Overview Summary History Statement Transactions Transfer Payment
Payments Beneficiary Balance Amount Status Date Time Reference Receipt Invoice Orders Order Cart Checkout Wishlist Products Category
Search Filter Sort Reset Submit Cancel Confirm Continue Back Next Save Edit Delete Update Upload Download Print Share Help Support
Contact About Careers Security Privacy Terms Notifications Messages Inbox Sent Drafts Spam Trash Compose Reply Forward Calendar
Meetings Schedule Participants Mute Camera Present Record Chat Leave Join Appointments Doctors Patients Reports Prescriptions Billing
Insurance Departments Employees Payroll Leave Attendance Holidays Documents Policies Directory Team Manager Department Employee
Account Savings Current Deposit Loan Card Credit Debit Statement Limit Rewards Offers Coupons Delivery Shipping Returns Refund
Tracking Reviews Ratings Brand Price Discount Quantity Total Subtotal Tax Address Phone Email Password Username Verify Code
Account Number Branch IFSC Mobile Aadhaar PAN Card Number Expiry Holder Optional Required Active Pending Completed Failed Approved""".split()
UI_STATUS = ["Active", "Pending", "Completed", "Failed", "Approved", "Verified", "Overdue", "Paid", "Shipped", "Delivered", "Scheduled"]
UI_FILLERS = ["Please", "Your", "All", "New", "Recent", "Quick", "My", "View", "Manage", "Add", "Select", "Enter", "Choose", "Total", "No"]
UI_SENTENCES = [
    "Your session will expire in 5 minutes", "No transactions found for this period", "Select a payee to continue",
    "Enter the one time password sent to your registered mobile", "Your request has been submitted successfully",
    "Please verify your details before confirming", "Download the latest statement as PDF", "Terms and conditions apply",
    "Manage notifications and security settings", "Add a new beneficiary to transfer funds", "This meeting is being recorded",
    "Choose a department to view employees", "Book an appointment with a specialist", "Track your order and delivery status",
    "Update your profile and contact preferences", "Recent activity across all accounts", "You have no unread messages",
    "Click here to reset your password", "Invalid username or password", "All fields marked required must be filled",
]


def neg_phrase(rng):
    """Title-case UI words only: nav bars, headings, buttons, table headers."""
    k = rng.randint(1, 6)
    words = [rng.choice(UI_WORDS) for _ in range(k)]
    if rng.random() < 0.3:
        words.insert(0, rng.choice(UI_FILLERS))
    sep = rng.choice([' ', ' ', ' | ', ' > ', ' - '])
    return sep.join(words) if sep != ' ' else ' '.join(words)


def neg_label_value(rng):
    """'Label: value' lines where the value is a number/date/status, not a name."""
    label = ' '.join(rng.choice(UI_WORDS) for _ in range(rng.randint(1, 2)))
    value = rng.choice([str(rng.randint(10, 99999)), f'{rng.randint(1, 28)} Oct 2026', rng.choice(UI_STATUS),
                        f'INR {rng.randint(100, 90000):,}', f'{rng.randint(1, 12)}:{rng.randint(10, 59)} PM'])
    return f'{label}: {value}'


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
    r = rng.random()
    if r < 0.45:  # no person at all: the biggest fix for v1's over-flagging
        kind = rng.random()
        spans = []
        if kind < 0.40:
            text = neg_phrase(rng)
        elif kind < 0.60:
            text = neg_label_value(rng)
        elif kind < 0.80:
            text = rng.choice(UI_SENTENCES)
        else:
            text, spans = render(rng.choice(NEG_TEMPLATES), {'x': (rng.choice(HARD_NEGATIVES), False)})
    elif r < 0.55:  # a name surrounded by ordinary UI words: only the name may be tagged
        fill = {'a': (neg_phrase(rng), False), 'n': (person(first, last, rng), True),
                'b': (rng.choice([neg_phrase(rng), neg_label_value(rng)]), False)}
        text, spans = render(rng.choice(['{a} {n} {b}', '{a}: {n} - {b}', '{n} {b}', '{a} {n}']), fill)
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

"""
gen_personas.py - builds the 50 SYNTHETIC Indian personas used by the test sites.

Nothing here is real personal data:
  * Aadhaar numbers are random but pass the Verhoeff checksum (so the detector
    is tested on the hard case), and none of them is a real card.
  * Card numbers use the 4111-style test BIN and pass Luhn.
  * PAN, phone, email, address, bank account are random in the correct format.
  * Faces: SFHQ (Synthetic Faces High Quality, CC0) photos are used if you drop
    them into testbed/sites/assets/faces/face_01.jpg ... face_20.jpg.
    Otherwise simple generated SVG avatars are used so the suite runs offline.

Run:  python testbed/gen_personas.py        (seeded -> same output every time)
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'server'))
from pii import luhn_valid, verhoeff_check_digit  # noqa: E402

SEED = 2026
N_PERSONAS = 50
N_FACES = 20

FIRST = ['Aarav', 'Vivaan', 'Aditya', 'Sai', 'Arjun', 'Reyansh', 'Krishna', 'Ishaan', 'Rohan', 'Kabir',
         'Ananya', 'Diya', 'Saanvi', 'Aadhya', 'Myra', 'Pari', 'Navya', 'Kavya', 'Riya', 'Meera',
         'Harsh', 'Tejas', 'Yash', 'Nitin', 'Mohit', 'Pranav', 'Lakshay', 'Dev', 'Om', 'Ritvik',
         'Shalini', 'Pallavi', 'Radhika', 'Swarna', 'Bhavna', 'Indira', 'Usha', 'Vandana', 'Zoya', 'Fatima',
         'Imran', 'Salman', 'Gurpreet', 'Harpreet', 'Jaspreet', 'Manpreet', 'Thomas', 'Joseph', 'Abraham', 'Mathew']
LAST = ['Sharma', 'Verma', 'Gupta', 'Iyer', 'Nair', 'Reddy', 'Rao', 'Patel', 'Shah', 'Mehta',
        'Kulkarni', 'Deshpande', 'Bhat', 'Shetty', 'Gowda', 'Naidu', 'Menon', 'Pillai', 'Das', 'Roy',
        'Khan', 'Ansari', 'Qureshi', 'Singh', 'Gill', 'Sandhu', 'Fernandes', 'DSouza', 'Thomas', 'Varghese']
STREETS = ['MG Road', '12th Main, Indiranagar', '4th Cross, Jayanagar', 'Lake View Layout, HSR', 'Church Street',
           'Nehru Nagar', 'Gandhi Road', 'Park Avenue, Koramangala', 'Temple Street, Malleshwaram', 'Rose Garden Layout']
CITIES = [('Bengaluru', 'Karnataka', 560), ('Mumbai', 'Maharashtra', 400), ('Chennai', 'Tamil Nadu', 600),
          ('Hyderabad', 'Telangana', 500), ('Pune', 'Maharashtra', 411), ('Kolkata', 'West Bengal', 700)]
BANKS = ['DEMO', 'TEST', 'SAMP', 'MOCK']
DEPTS = ['Engineering', 'Finance', 'Operations', 'Design', 'Support']
DOCTORS = ['Dr. Menon', 'Dr. Kapoor', 'Dr. Banerjee', 'Dr. Fernandes']
CONDITIONS = ['Type 2 diabetes follow-up', 'Seasonal allergy', 'Hypertension check', 'Routine annual check-up', 'Lower back pain']


def aadhaar(rng):
    first11 = str(rng.randint(2, 9)) + ''.join(str(rng.randint(0, 9)) for _ in range(10))
    full = first11 + verhoeff_check_digit(first11)
    return f'{full[:4]} {full[4:8]} {full[8:]}'


def pan(rng):
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return ''.join(rng.choice(letters) for _ in range(3)) + 'P' + rng.choice(letters) + \
        ''.join(str(rng.randint(0, 9)) for _ in range(4)) + rng.choice(letters)


def card(rng):
    body = '4111' + ''.join(str(rng.randint(0, 9)) for _ in range(11))
    for check in range(10):
        if luhn_valid(body + str(check)):
            n = body + str(check)
            return ' '.join(n[i:i + 4] for i in range(0, 16, 4))
    raise AssertionError('unreachable')


def phone(rng):
    n = str(rng.randint(6, 9)) + ''.join(str(rng.randint(0, 9)) for _ in range(9))
    return f'+91 {n[:5]} {n[5:]}'


def persona(i, rng):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    city, state, pin_prefix = rng.choice(CITIES)
    pin = f'{pin_prefix}{rng.randint(0, 999):03d}'
    handle = f'{first}.{last}'.lower()
    face_no = (i % N_FACES) + 1
    return {
        'id': i,
        'name': f'{first} {last}',
        'first': first,
        'last': last,
        'username': f'{handle}{rng.randint(10, 99)}',
        'password': f'Ps!{rng.randint(1000, 9999)}-{last[:3].lower()}',
        'email': f'{handle}{rng.randint(1, 99)}@example.test',
        'phone': phone(rng),
        'aadhaar': aadhaar(rng),
        'pan': pan(rng),
        'card': card(rng),
        'dob': f'{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1965, 2003)}',
        'address': f'{rng.randint(1, 240)}, {rng.choice(STREETS)}, {city}, {state} {pin}',
        'pincode': pin,
        'account': ''.join(str(rng.randint(0, 9)) for _ in range(12)),
        'ifsc': f'{rng.choice(BANKS)}0{rng.randint(0, 999999):06d}',
        'balance': rng.randint(5000, 900000),
        'department': rng.choice(DEPTS),
        'doctor': rng.choice(DOCTORS),
        'condition': rng.choice(CONDITIONS),
        'face': f'assets/faces/face_{face_no:02d}',  # .jpg if present, else .svg
        'payee': 'Priya Nair',                       # saved payee used by transfer tasks
    }


def write_svg_faces(out_dir: Path, rng):
    """Simple offline avatars so the suite works without the SFHQ photos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    skins = ['#f1c9a5', '#e0ac84', '#c68642', '#8d5524', '#f5d5b8']
    hairs = ['#1c1c1c', '#3b2417', '#5a3825', '#777777', '#0f0f0f']
    for k in range(1, N_FACES + 1):
        skin, hair = rng.choice(skins), rng.choice(hairs)
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120">'
            '<rect width="120" height="120" fill="#dfe8f5"/>'
            f'<ellipse cx="60" cy="112" rx="42" ry="30" fill="#4a6fa5"/>'
            f'<ellipse cx="60" cy="58" rx="28" ry="34" fill="{skin}"/>'
            f'<path d="M30 52 Q34 20 60 20 Q86 20 90 52 Q80 34 60 34 Q40 34 30 52Z" fill="{hair}"/>'
            '<circle cx="49" cy="58" r="3.2" fill="#222"/><circle cx="71" cy="58" r="3.2" fill="#222"/>'
            '<path d="M50 76 Q60 84 70 76" stroke="#7a3b2e" stroke-width="3" fill="none" stroke-linecap="round"/>'
            '</svg>'
        )
        (out_dir / f'face_{k:02d}.svg').write_text(svg, encoding='utf-8')


def main():
    rng = random.Random(SEED)
    people = [persona(i, rng) for i in range(N_PERSONAS)]
    data_dir = HERE / 'sites' / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / 'personas.json').write_text(json.dumps(people, indent=2, ensure_ascii=False), encoding='utf-8')
    write_svg_faces(HERE / 'sites' / 'assets' / 'faces', random.Random(SEED + 1))
    print(f'wrote {len(people)} personas and {N_FACES} avatar faces under {HERE / "sites"}')


if __name__ == '__main__':
    main()
